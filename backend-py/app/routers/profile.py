import json
import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from app.limiter import limiter
from app.config import config
from app.db import get_db, get_student_by_session_id, save_study_path, suggest_counsellor, upsert_student
from app.services.profile_report import generate_structured_profile_report
from app.services.course_matcher import match_courses
from app.services.lead_scoring import (
    ACADEMIC_BACKGROUNDS,
    MIGRATION_INTENTS,
    PREFERRED_COUNTRY_ANY,
    score_lead,
    student_row_to_profile,
)
from app.services.report_export import generate_report_docx, generate_report_pdf
from app.services.study_path_engine import generate_study_path

router = APIRouter()
logger = logging.getLogger("aiec.profile")


def _sanitize_filename_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]+", "_", value)[:60] or "report"


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ProfileRequest(BaseModel):
    fullName: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=30)
    gpa: float = Field(ge=0, le=4.0)
    ielts: float = Field(ge=0, le=9.0)
    budget: float = Field(gt=0, le=1_000_000)
    gap: int = Field(ge=0, le=50)
    academicBackground: str
    careerGoals: str = Field(default="", max_length=1000)
    migrationIntent: str
    preferredCountry: str = Field(default=PREFERRED_COUNTRY_ANY, min_length=1, max_length=100)
    sessionId: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _valid_email_or_empty(cls, v: str) -> str:
        if v and not _EMAIL_RE.match(v):
            raise ValueError("invalid email")
        return v

    @field_validator("academicBackground")
    @classmethod
    def _valid_academic_background(cls, v: str) -> str:
        if v not in ACADEMIC_BACKGROUNDS:
            raise ValueError("invalid academicBackground")
        return v

    @field_validator("migrationIntent")
    @classmethod
    def _valid_migration_intent(cls, v: str) -> str:
        if v not in MIGRATION_INTENTS:
            raise ValueError("invalid migrationIntent")
        return v


@router.post("/profile/analyze")
@limiter.limit(f"{config.profile_rate_limit_max}/minute")
def analyze_profile(request: Request, body: ProfileRequest):
    profile = {
        "gpa": body.gpa,
        "ielts": body.ielts,
        "budget": body.budget,
        "gap": body.gap,
        "academicBackground": body.academicBackground,
        "careerGoals": body.careerGoals,
        "migrationIntent": body.migrationIntent,
        "preferredCountry": body.preferredCountry,
    }

    try:
        result = score_lead(profile)
        conn = get_db()
        matches = match_courses(conn, profile)
        alternatives_allowed = profile["preferredCountry"] == PREFERRED_COUNTRY_ANY or len(matches.primary) == 0

        report = generate_structured_profile_report(conn, profile, matches, alternatives_allowed)

        # Suggestion only — a human (admin/counsellor) still has to confirm the
        # assignment via POST /api/admin/leads/:id/assign.
        suggested = suggest_counsellor(conn)

        saved_student = upsert_student(
            conn,
            {
                "sessionId": body.sessionId,
                "name": body.fullName,
                "email": body.email or None,
                "phone": body.phone or None,
                "gpa": profile["gpa"],
                "ielts": profile["ielts"],
                "budget": profile["budget"],
                "gap": profile["gap"],
                "academicBackground": profile["academicBackground"],
                "careerGoals": profile["careerGoals"] or None,
                "migrationIntent": profile["migrationIntent"],
                "preferredCountry": profile["preferredCountry"],
                "score": result.score,
                "status": result.status,
                "countries": ", ".join(report.recommendedCountries),
                "aiResponse": report.summary,
                "nextSteps": json.dumps(report.nextSteps),
                "suggestedCounsellorId": suggested["id"] if suggested else None,
            },
        )
    except Exception:
        logger.exception("[profile/analyze] request failed")
        raise HTTPException(status_code=500, detail="Failed to analyze profile. Please try again.")

    logger.info("[profile] session=%s status=%s score=%s", body.sessionId, result.status, result.score)

    return {
        "reply": report.summary,
        "status": result.status,
        "score": result.score,
        "recommendedCountries": report.recommendedCountries,
        "nextSteps": report.nextSteps,
        "suggestedCounsellor": {"id": suggested["id"], "name": suggested["name"]} if suggested else None,
        "referenceCode": saved_student["reference_code"],
        "sessionId": body.sessionId,
    }


@router.get("/profile/{session_id}/export")
@limiter.limit("20/minute")
def export_profile(request: Request, session_id: str, format: str = Query(default="pdf")):
    if format not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="Query param 'format' must be 'pdf' or 'docx'")

    student = get_student_by_session_id(get_db(), session_id)
    if not student:
        raise HTTPException(status_code=404, detail="No profile found for that session")

    filename = f"AIEC-Report-{_sanitize_filename_part(student['name'])}.{format}"

    try:
        if format == "pdf":
            buffer = generate_report_pdf(student)
            media_type = "application/pdf"
        else:
            buffer = generate_report_docx(student)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    except Exception:
        logger.exception("[profile/export] request failed")
        raise HTTPException(status_code=500, detail="Failed to generate report. Please try again.")

    return Response(
        content=buffer,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Phase 3 "Personalized study path engine" — a multi-stage roadmap beyond the
# single-recommendation profile report. On-demand only and cached on the
# student row.
@router.post("/profile/{session_id}/study-path")
@limiter.limit(f"{config.profile_rate_limit_max}/minute")
def create_study_path(request: Request, session_id: str):
    conn = get_db()
    student = get_student_by_session_id(conn, session_id)
    if not student:
        raise HTTPException(status_code=404, detail="No profile found for that session")

    try:
        profile = student_row_to_profile(student)
        matches = match_courses(conn, profile)
        study_path = generate_study_path(profile, matches)
        save_study_path(conn, student["id"], json.dumps(study_path.stages))
    except Exception:
        logger.exception("[profile/study-path] request failed")
        raise HTTPException(status_code=500, detail="Failed to generate study path. Please try again.")

    logger.info("[profile] session=%s study-path generated", session_id)

    return {"stages": study_path.stages, "sessionId": session_id}
