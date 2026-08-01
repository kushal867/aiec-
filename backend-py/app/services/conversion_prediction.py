import json
from dataclasses import dataclass, field
from typing import Any

from app.services.crm_assistant import check_inactivity
from app.services.document_checklist import build_document_checklist

# Rule-based heuristic — deliberately NOT a trained ML model. A genuine
# predictive classifier needs historical outcomes (leads that actually
# enrolled vs. didn't, over enough volume) to learn from, and this is a
# brand-new system with no such history yet. The numbers below are documented
# starting assumptions, not measured conversion rates — same "named
# constants, retune here" philosophy as lead_scoring.py.
#
# This is now the bootstrap/fallback tier for conversion_model.py, which
# trains a real LogisticRegression on real outcome data once enough
# accumulates (see CONVERSION_MODEL_MIN_TRAINING_ROWS) and calls this
# function verbatim below that threshold. Every input used here is part of
# that model's feature set, so nothing here needs to change as the switchover
# happens automatically.
BASE_RATE_BY_LEAD_STATUS = {"Hot": 55, "Warm": 28, "Cold": 8}

# Multiplies the base rate — further pipeline progress signals a real,
# increasingly committed applicant, independent of the original Hot/Warm/Cold
# score (which only reflects academic/financial fit, not follow-through).
STATUS_STAGE_MULTIPLIER = {
    "not_started": 1.0,
    "documents_pending": 1.05,
    "submitted": 1.3,
    "under_review": 1.5,
    "offer_received": 2.0,
    "visa_processing": 2.3,
    "enrolled": 1.0,  # unreachable — handled as a terminal case below
    "rejected": 1.0,  # unreachable — handled as a terminal case below
    "deferred": 1.4,
}

INACTIVITY_PENALTY_POINTS = 15
DOCUMENT_COMPLETE_BONUS_POINTS = 10

_MIN_PROBABILITY = 1
_MAX_PROBABILITY = 99  # never claim certainty short of the terminal states below


@dataclass
class ConversionPrediction:
    probability: int
    likelihood: str
    factors: list[str] = field(default_factory=list)


def likelihood_band(probability: int) -> str:
    if probability >= 70:
        return "Very Likely"
    if probability >= 40:
        return "Likely"
    if probability >= 15:
        return "Possible"
    return "Unlikely"


def predict_conversion(student: Any) -> ConversionPrediction:
    """Pure function — no I/O, no LLM call. Deterministic and unit-testable,
    same as score_lead()."""
    if student["application_status"] == "enrolled":
        return ConversionPrediction(probability=100, likelihood="Very Likely", factors=["Already enrolled — outcome realized"])
    if student["application_status"] == "rejected":
        return ConversionPrediction(probability=0, likelihood="Unlikely", factors=["Application was not successful"])

    factors: list[str] = []
    base = BASE_RATE_BY_LEAD_STATUS[student["status"]]
    factors.append(f"{student['status']} lead classification (base {base}%)")

    stage_multiplier = STATUS_STAGE_MULTIPLIER[student["application_status"]]
    probability = base * stage_multiplier
    if stage_multiplier > 1:
        factors.append(f'"{student["application_status"]}" pipeline stage increases likelihood')

    inactivity = check_inactivity(student)
    if inactivity.isInactive:
        probability -= INACTIVITY_PENALTY_POINTS
        factors.append(f"Overdue for contact (-{INACTIVITY_PENALTY_POINTS} pts)")

    documents = json.loads(student["documents"]) if student["documents"] else []
    checklist = build_document_checklist(documents)
    if checklist.complete:
        probability += DOCUMENT_COMPLETE_BONUS_POINTS
        factors.append(f"All required documents complete (+{DOCUMENT_COMPLETE_BONUS_POINTS} pts)")
    elif checklist.missing:
        factors.append(f"{len(checklist.missing)} document(s) still missing")

    clamped = round(min(_MAX_PROBABILITY, max(_MIN_PROBABILITY, probability)))
    return ConversionPrediction(probability=clamped, likelihood=likelihood_band(clamped), factors=factors)
