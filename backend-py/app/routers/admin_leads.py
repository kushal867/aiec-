import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import (
    APPLICATION_STATUSES,
    assign_counsellor,
    get_db,
    get_student_by_id,
    get_user_by_id,
    list_counsellors,
    list_students,
    mark_contacted,
    save_followup_suggestion,
    update_application_status,
    update_counsellor_notes,
)
from app.deps_auth import require_auth
from app.services.application_status import explain_application_status
from app.services.conversion_model import predict_conversion
from app.services.crm_assistant import check_inactivity, generate_followup_suggestion
from app.services.document_checklist import build_document_checklist
from app.services.auth import AuthTokenPayload

router = APIRouter()
logger = logging.getLogger("aiec.admin_leads")


def _serialize_student(row: Any) -> dict:
    documents = json.loads(row["documents"]) if row["documents"] else []
    return {
        "id": row["id"],
        "sessionId": row["session_id"],
        "referenceCode": row["reference_code"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "gpa": row["gpa"],
        "ielts": row["ielts"],
        "budget": row["budget"],
        "gap": row["gap"],
        "academicBackground": row["academic_background"],
        "careerGoals": row["career_goals"],
        "migrationIntent": row["migration_intent"],
        "preferredCountry": row["preferred_country"],
        "score": row["score"],
        "status": row["status"],
        "countries": row["countries"],
        "aiResponse": row["ai_response"],
        "nextSteps": json.loads(row["next_steps"]) if row["next_steps"] else [],
        "documents": documents,
        "documentChecklist": build_document_checklist(documents),
        "counsellorNotes": row["counsellor_notes"],
        "applicationStatus": explain_application_status(row["application_status"]),
        "applicationStatusUpdatedAt": row["application_status_updated_at"],
        "assignedCounsellorId": row["assigned_counsellor_id"],
        "suggestedCounsellorId": row["suggested_counsellor_id"],
        "lastContactedAt": row["last_contacted_at"],
        "followupSuggestion": row["followup_suggestion"],
        "followupAction": row["followup_action"],
        "followupTiming": row["followup_timing"],
        "followupGeneratedAt": row["followup_generated_at"],
        "inactivity": check_inactivity(row),
        "conversionPrediction": predict_conversion(row),
        "studyPath": json.loads(row["study_path"]) if row["study_path"] else None,
        "studyPathGeneratedAt": row["study_path_generated_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


# Admins see every lead; counsellors only see leads assigned to them — the
# 4.3 "role-based behavior" requirement from the brief.
@router.get("/admin/leads")
def get_leads(
    status: str | None = None,
    sort: str = "desc",
    inactiveOnly: bool = False,
    user: AuthTokenPayload = Depends(require_auth),
):
    counsellor_id = user["userId"] if user["role"] == "counsellor" else None
    rows = list_students(get_db(), status=status, sort="asc" if sort == "asc" else "desc", counsellor_id=counsellor_id)
    serialized = [_serialize_student(r) for r in rows]
    # Inactivity is time-relative ("now"), so it can't be a SQL WHERE clause —
    # filtered in Python after the (small, single-tenant) result set is fetched.
    if inactiveOnly:
        serialized = [s for s in serialized if s["inactivity"].isInactive]
    return {"leads": serialized}


@router.get("/admin/counsellors")
def get_counsellors(user: AuthTokenPayload = Depends(require_auth)):
    rows = list_counsellors(get_db())
    return {"counsellors": [{"id": c["id"], "name": c["name"], "email": c["email"]} for c in rows]}


class NotesRequest(BaseModel):
    notes: str = Field(max_length=5000)


@router.patch("/admin/leads/{lead_id}/notes")
def patch_notes(lead_id: int, body: NotesRequest, user: AuthTokenPayload = Depends(require_auth)):
    updated = update_counsellor_notes(get_db(), lead_id, body.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": _serialize_student(updated)}


class StatusRequest(BaseModel):
    applicationStatus: str

    def validate_status(self) -> None:
        if self.applicationStatus not in APPLICATION_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid request body")


@router.patch("/admin/leads/{lead_id}/status")
def patch_status(lead_id: int, body: StatusRequest, user: AuthTokenPayload = Depends(require_auth)):
    body.validate_status()
    updated = update_application_status(get_db(), lead_id, body.applicationStatus)
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": _serialize_student(updated)}


class AssignRequest(BaseModel):
    counsellorId: int = Field(gt=0)


# Admins may assign any lead to any counsellor. Counsellors may only claim a
# lead for themselves (self-assign) — they can't reassign to a colleague or
# take a lead someone else already owns. This is the 2.2 "counsellor
# assignment" requirement, gated by the 4.3 role-based behavior rule.
@router.post("/admin/leads/{lead_id}/assign")
def assign_lead(lead_id: int, body: AssignRequest, user: AuthTokenPayload = Depends(require_auth)):
    conn = get_db()

    if user["role"] == "counsellor":
        if body.counsellorId != user["userId"]:
            raise HTTPException(status_code=403, detail="Counsellors may only claim a lead for themselves")
        existing = get_student_by_id(conn, lead_id)
        if existing and existing["assigned_counsellor_id"] and existing["assigned_counsellor_id"] != user["userId"]:
            raise HTTPException(status_code=403, detail="This lead is already assigned to another counsellor")
    else:
        target = get_user_by_id(conn, body.counsellorId)
        if not target or target["role"] != "counsellor":
            raise HTTPException(status_code=400, detail="counsellorId does not refer to a counsellor account")

    updated = assign_counsellor(conn, lead_id, body.counsellorId)
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": _serialize_student(updated)}


@router.post("/admin/leads/{lead_id}/contacted")
def contacted(lead_id: int, user: AuthTokenPayload = Depends(require_auth)):
    updated = mark_contacted(get_db(), lead_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"lead": _serialize_student(updated)}


# On-demand only — never auto-generated in bulk (Claude call, see crm_assistant.py).
@router.post("/admin/leads/{lead_id}/followup")
def followup(lead_id: int, user: AuthTokenPayload = Depends(require_auth)):
    conn = get_db()
    student = get_student_by_id(conn, lead_id)
    if not student:
        raise HTTPException(status_code=404, detail="Lead not found")

    try:
        inactivity = check_inactivity(student)
        suggestion = generate_followup_suggestion(student, inactivity)
        updated = save_followup_suggestion(
            conn, lead_id, suggestion.messageTemplate, suggestion.suggestedAction, suggestion.timing
        )
        return {"lead": _serialize_student(updated) if updated else None}
    except Exception:
        logger.exception("[admin/leads/followup] request failed")
        raise HTTPException(status_code=500, detail="Failed to generate follow-up suggestion. Please try again.")
