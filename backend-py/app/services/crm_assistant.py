import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.application_status import explain_application_status
from app.services.document_checklist import DOCUMENT_LABELS, build_document_checklist


def _join_readable(items: list[str]) -> str:
    """["a"] -> "a"; ["a","b"] -> "a and b"; ["a","b","c"] -> "a, b, and c" —
    a document list joined with bare commas ("citizenship, marksheet,
    ielts_certificate") reads like a raw data dump, not a sentence a human
    wrote."""
    if len(items) <= 1:
        return items[0] if items else ""
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _document_labels(doc_types: list[str]) -> list[str]:
    return [DOCUMENT_LABELS[t] for t in doc_types]

# Named, documented thresholds — same rubric philosophy as lead_scoring.py: a
# Hot lead going quiet is far more time-sensitive than a Cold one.
INACTIVITY_THRESHOLD_DAYS = {"Hot": 2, "Warm": 5, "Cold": 14}


@dataclass
class InactivityCheckResult:
    isInactive: bool
    daysSinceContact: int | None  # None = never contacted at all
    thresholdDays: int


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_inactivity(student: Any, now: datetime | None = None) -> InactivityCheckResult:
    """Pure, deterministic — no I/O, no LLM call. A student who has reached the
    terminal "enrolled" status is never flagged."""
    now = now or datetime.now(timezone.utc)
    threshold_days = INACTIVITY_THRESHOLD_DAYS[student["status"]]
    if student["application_status"] == "enrolled":
        return InactivityCheckResult(isInactive=False, daysSinceContact=None, thresholdDays=threshold_days)

    reference_iso = student["last_contacted_at"] or student["created_at"]
    days_since = (now - _parse_iso(reference_iso)).days

    return InactivityCheckResult(
        isInactive=days_since >= threshold_days,
        daysSinceContact=days_since if student["last_contacted_at"] else None,
        thresholdDays=threshold_days,
    )


@dataclass
class FollowupSuggestion:
    timing: str
    suggestedAction: str
    messageTemplate: str


# No LLM here — suggestion + message are built from the same STUDENT RECORD
# fields the Claude version was given, via fixed templates instead of
# free-form writing. Less natural-sounding, but every word is traceable to a
# specific field, same anti-invention principle as the rest of this codebase.


def generate_followup_suggestion(student: Any, inactivity: InactivityCheckResult) -> FollowupSuggestion:
    """On-demand only (never auto-run per row on every dashboard load) —
    matches the original's "explicit regenerate action" behavior, though the
    cost reasoning that motivated that no longer applies without an LLM call."""
    status_info = explain_application_status(student["application_status"])
    documents = json.loads(student["documents"]) if student["documents"] else []
    checklist = build_document_checklist(documents)

    if inactivity.isInactive:
        timing = (
            f"Overdue now — contact within 24 hours ({student['status']} leads are expected to be "
            f"contacted every {inactivity.thresholdDays} day(s))"
        )
    else:
        remaining = inactivity.thresholdDays - (inactivity.daysSinceContact or 0)
        timing = f"On track — next contact due in {remaining} day(s)"

    name = student["name"]

    if checklist.missing:
        missing_labels = _join_readable(_document_labels(checklist.missing))
        action = f"Ask {name} to upload the missing document(s): {missing_labels}."
    elif checklist.needsAttention:
        attention_labels = _join_readable(_document_labels(checklist.needsAttention))
        action = f"Ask {name} to re-upload the flagged document(s): {attention_labels}."
    elif inactivity.isInactive:
        action = f"Reach out to {name} — it's been {inactivity.daysSinceContact if inactivity.daysSinceContact is not None else 'a while'} day(s) since last contact."
    else:
        action = f"No urgent action needed for {name} right now — next contact is on track."

    message_lines = [f"Hi {name},"]
    if checklist.missing:
        missing_labels = _document_labels(checklist.missing)
        pronoun = "it" if len(missing_labels) == 1 else "them"
        message_lines.append(
            f"We're still waiting on your {_join_readable(missing_labels)} — could you upload {pronoun} when you get a chance?"
        )
    elif checklist.needsAttention:
        attention_labels = _document_labels(checklist.needsAttention)
        message_lines.append(
            f"We noticed an issue with your {_join_readable(attention_labels)} — could you re-upload a clearer copy?"
        )
    else:
        message_lines.append(
            f"Just checking in on your application ({status_info.label.lower()}) — let us know if you have any questions."
        )
    message_lines.append("Best, AIEC Global")

    return FollowupSuggestion(timing=timing, suggestedAction=action, messageTemplate="\n".join(message_lines))
