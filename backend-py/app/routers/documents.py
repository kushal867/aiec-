import json
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from app.limiter import limiter
from app.config import config
from app.db import append_document_record, ensure_student_stub, get_db, get_student_by_session_id
from app.services.document_checklist import build_document_checklist
from app.services.document_verification import DOCUMENT_TYPES, verify_document
from app.services.lead_scoring import student_row_to_profile

router = APIRouter()
logger = logging.getLogger("aiec.documents")

_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB


def _parse_document_records(documents_json: str | None) -> list[dict]:
    return json.loads(documents_json) if documents_json else []


def _sanitize_for_path(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9-]", "", value)[:100] or "unknown-session"


def _extension_for(mime_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/pdf": "pdf",
    }.get(mime_type, "bin")


@router.post("/documents/upload")
@limiter.limit(f"{config.document_rate_limit_max}/minute")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    documentType: str = Form(...),
    sessionId: str = Form(..., min_length=1, max_length=200),
):
    if documentType not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid request fields")
    if file.content_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: JPEG, PNG, WEBP, PDF.",
        )

    contents = await file.read()
    if len(contents) > _MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    try:
        conn = get_db()
        # Guarantees a row exists before the document is attached to it — see
        # ensure_student_stub()'s docstring for why this matters even though
        # the real UI always submits a profile first.
        student = ensure_student_stub(conn, sessionId)
        profile = student_row_to_profile(student)

        result = verify_document(documentType, contents, file.content_type, profile)

        safe_session_dir = _sanitize_for_path(sessionId)
        upload_dir = config.uploads_dir / safe_session_dir
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{documentType}-{int(time.time() * 1000)}.{_extension_for(file.content_type)}"
        (upload_dir / filename).write_bytes(contents)

        from app.db import now_iso

        record = {
            "documentType": documentType,
            "filename": filename,
            "status": result["status"],
            "issues": result["issues"],
            "extractedSummary": result["extractedSummary"],
            "uploadedAt": now_iso(),
        }
        updated = append_document_record(conn, sessionId, record)
        checklist = build_document_checklist(_parse_document_records(updated["documents"] if updated else None))

        logger.info("[documents] session=%s type=%s status=%s", sessionId, documentType, result["status"])

        return {"documentType": documentType, **result, "sessionId": sessionId, "checklist": checklist}
    except HTTPException:
        raise
    except Exception:
        logger.exception("[documents/upload] request failed")
        raise HTTPException(status_code=500, detail="Failed to verify document. Please try again.")


@router.get("/documents/checklist/{session_id}")
@limiter.limit("30/minute")
def get_checklist(request: Request, session_id: str):
    student = get_student_by_session_id(get_db(), session_id)
    if not student:
        # Not an error — a student who hasn't submitted their profile yet
        # simply has all documents outstanding.
        return {"sessionId": session_id, "checklist": build_document_checklist([])}
    checklist = build_document_checklist(_parse_document_records(student["documents"]))
    return {"sessionId": session_id, "checklist": checklist}
