import json
import logging
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.limiter import limiter
from app.db import get_db, get_student_by_reference_code
from app.services.application_status import explain_application_status
from app.services.document_checklist import build_document_checklist
from app.services.report_export import generate_report_docx, generate_report_pdf

router = APIRouter()
logger = logging.getLogger("aiec.status")


def _sanitize_filename_part(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]+", "_", value)[:60] or "report"


@router.get("/status/{reference_code}")
@limiter.limit("20/minute")
def get_status(request: Request, reference_code: str):
    student = get_student_by_reference_code(get_db(), reference_code.strip().upper())
    if not student:
        raise HTTPException(status_code=404, detail="No application found for that reference code")

    documents = json.loads(student["documents"]) if student["documents"] else []

    # Deliberately minimal, student-safe projection — never expose internal
    # CRM fields (Hot/Warm/Cold score, counsellor notes, assigned counsellor,
    # contact info) through a code-only-gated public endpoint.
    return {
        "referenceCode": student["reference_code"],
        "name": student["name"],
        "applicationStatus": explain_application_status(student["application_status"]),
        "documentChecklist": build_document_checklist(documents),
        "updatedAt": student["application_status_updated_at"] or student["updated_at"],
    }


# Unlike the endpoint above, this returns the student's own full profile + AI
# recommendation — a deliberate "give me my information" action the student
# takes, not the passive minimal status check. Still never includes internal
# CRM-only fields.
@router.get("/status/{reference_code}/export")
@limiter.limit("20/minute")
def export_status(request: Request, reference_code: str, format: str = Query(default="pdf")):
    if format not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="Query param 'format' must be 'pdf' or 'docx'")

    student = get_student_by_reference_code(get_db(), reference_code.strip().upper())
    if not student:
        raise HTTPException(status_code=404, detail="No application found for that reference code")

    filename = f"AIEC-Report-{_sanitize_filename_part(student['name'])}.{format}"

    try:
        if format == "pdf":
            buffer = generate_report_pdf(student)
            media_type = "application/pdf"
        else:
            buffer = generate_report_docx(student)
            media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    except Exception:
        logger.exception("[status/export] request failed")
        raise HTTPException(status_code=500, detail="Failed to generate report. Please try again.")

    return Response(
        content=buffer,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
