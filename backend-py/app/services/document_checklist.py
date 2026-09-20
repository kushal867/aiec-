from dataclasses import dataclass, field
from typing import Any

from app.services.document_verification import DOCUMENT_TYPES

DOCUMENT_LABELS = {
    "citizenship": "Citizenship / ID document",
    "marksheet": "Academic transcript / marksheet",
    "ielts_certificate": "IELTS certificate",
    "pte_certificate": "PTE certificate",
}


@dataclass
class DocumentChecklistItem:
    documentType: str
    label: str
    uploaded: bool
    status: str | None
    issues: list[str]
    uploadedAt: str | None


@dataclass
class DocumentChecklist:
    items: list[DocumentChecklistItem] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    needsAttention: list[str] = field(default_factory=list)
    complete: bool = False


def build_document_checklist(documents: list[dict[str, Any]]) -> DocumentChecklist:
    """Pure aggregation over a student's uploaded-document records. If a type
    was uploaded more than once (e.g. a re-upload after a rejected scan), the
    most recent upload determines its current status."""
    latest_by_type: dict[str, dict[str, Any]] = {}
    for doc in documents:
        existing = latest_by_type.get(doc["documentType"])
        if not existing or doc["uploadedAt"] > existing["uploadedAt"]:
            latest_by_type[doc["documentType"]] = doc

    items = []
    for doc_type in DOCUMENT_TYPES:
        latest = latest_by_type.get(doc_type)
        items.append(
            DocumentChecklistItem(
                documentType=doc_type,
                label=DOCUMENT_LABELS[doc_type],
                uploaded=latest is not None,
                status=latest["status"] if latest else None,
                issues=latest["issues"] if latest else [],
                uploadedAt=latest["uploadedAt"] if latest else None,
            )
        )

    missing = [item.documentType for item in items if not item.uploaded]
    needs_attention = [item.documentType for item in items if item.uploaded and item.status != "valid"]

    return DocumentChecklist(
        items=items,
        missing=missing,
        needsAttention=needs_attention,
        complete=len(missing) == 0 and len(needs_attention) == 0,
    )
