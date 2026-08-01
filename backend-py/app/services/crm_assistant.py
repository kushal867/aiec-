import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.services.application_status import explain_application_status
from app.services.document_checklist import build_document_checklist

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
        action = f"Ask {name} to upload the missing document(s): {', '.join(checklist.missing)}."
    elif checklist.needsAttention:
        action = f"Ask {name} to re-upload the flagged document(s): {', '.join(checklist.needsAttention)}."
    elif inactivity.isInactive:
        action = f"Reach out to {name} — it's been {inactivity.daysSinceContact if inactivity.daysSinceContact is not None else 'a while'} day(s) since last contact."
    else:
        action = f"No urgent action needed for {name} right now — next contact is on track."

    message_lines = [f"Hi {name},"]
    if checklist.missing:
        message_lines.append(
            f"We're still waiting on your {', '.join(checklist.missing)} — could you upload it when you get a chance?"
        )
    elif checklist.needsAttention:
        message_lines.append(
            f"We noticed an issue with your {', '.join(checklist.needsAttention)} — could you re-upload a clearer copy?"
        )
    else:
        message_lines.append(
            f"Just checking in on your application ({status_info.label.lower()}) — let us know if you have any questions."
        )
    message_lines.append("Best, AIEC Global")

    return FollowupSuggestion(timing=timing, suggestedAction=action, messageTemplate="\n".join(message_lines))
