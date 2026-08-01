from dataclasses import dataclass

from app.db import APPLICATION_STATUSES

# Rule-based, not a Claude call — there are only 9 fixed statuses, so a
# templated plain-language explanation is cheaper, instant, and perfectly
# consistent, with zero hallucination risk. Retune the copy here, nowhere else.
_STATUS_INFO = {
    "not_started": {
        "label": "Not Started",
        "description": "Your profile has been reviewed, but your formal application hasn't been submitted to an institution yet.",
        "whatHappensNext": "Finish uploading your required documents and confirm your course choice with your counsellor so we can submit your application.",
        "isTerminal": False,
    },
    "documents_pending": {
        "label": "Documents Pending",
        "description": "We're waiting on one or more required documents (ID/citizenship, academic transcript, IELTS certificate) before your application can be submitted.",
        "whatHappensNext": "Check your document checklist and upload whatever is still missing or flagged.",
        "isTerminal": False,
    },
    "submitted": {
        "label": "Submitted",
        "description": "Your application has been submitted to the institution and is in their queue.",
        "whatHappensNext": "No action needed from you right now — we're waiting for the institution to start reviewing it.",
        "isTerminal": False,
    },
    "under_review": {
        "label": "Under Review",
        "description": "The institution is actively reviewing your application and documents.",
        "whatHappensNext": "Keep an eye on your email/phone in case the institution or your counsellor needs more information from you.",
        "isTerminal": False,
    },
    "offer_received": {
        "label": "Offer Received",
        "description": "Congratulations — the institution has made you an offer.",
        "whatHappensNext": "Review the offer conditions with your counsellor, accept it, and begin preparing your visa application.",
        "isTerminal": False,
    },
    "visa_processing": {
        "label": "Visa Processing",
        "description": "Your enrollment is confirmed and your student visa application is being processed.",
        "whatHappensNext": "Respond promptly to any visa office requests (biometrics, proof of funds, interviews) through your counsellor.",
        "isTerminal": False,
    },
    "enrolled": {
        "label": "Enrolled",
        "description": "You're fully enrolled — admission and visa formalities are complete.",
        "whatHappensNext": "Prepare for travel and orientation. Congratulations!",
        "isTerminal": True,
    },
    "rejected": {
        "label": "Not Successful",
        "description": "This particular application was not successful.",
        "whatHappensNext": "Talk to your counsellor about alternative courses or institutions — this outcome doesn't affect any other application.",
        "isTerminal": True,
    },
    "deferred": {
        "label": "Deferred",
        "description": "Your enrollment has been deferred to a later intake.",
        "whatHappensNext": "Confirm the new intake date with your counsellor and check whether any documents (e.g. IELTS) will need to be renewed by then.",
        "isTerminal": False,
    },
}


@dataclass
class ApplicationStatusInfo:
    status: str
    label: str
    description: str
    whatHappensNext: str
    isTerminal: bool


def explain_application_status(status: str) -> ApplicationStatusInfo:
    info = _STATUS_INFO[status]
    return ApplicationStatusInfo(status=status, **info)


def list_all_application_statuses() -> list[ApplicationStatusInfo]:
    return [explain_application_status(s) for s in APPLICATION_STATUSES]
