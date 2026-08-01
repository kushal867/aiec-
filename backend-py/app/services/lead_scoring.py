from dataclasses import dataclass
from typing import Any, TypedDict

PREFERRED_COUNTRY_ANY = "ANY"
PRIORITY_COUNTRIES = ["USA", "UK", "Australia"]

ACADEMIC_BACKGROUNDS = ["high_school", "bachelors", "masters", "phd"]
ACADEMIC_BACKGROUND_LABELS = {
    "high_school": "High school",
    "bachelors": "Bachelor's degree",
    "masters": "Master's degree",
    "phd": "PhD",
}

MIGRATION_INTENTS = ["study_only", "study_then_work", "migrate_permanently", "undecided"]
MIGRATION_INTENT_LABELS = {
    "study_only": "Study only, then return home",
    "study_then_work": "Study, then work abroad for a period",
    "migrate_permanently": "Migrate/settle permanently",
    "undecided": "Undecided",
}

# ---- Named, documented rubric constants — retune here, nowhere else. ----
# Scale is 0-10 total (matches students.score, a NUMERIC(4,2) CHECK'd between 0 and 10).

GPA_POINTS = {"EXCELLENT": 2.5, "GOOD": 1.8, "FAIR": 1.0, "LOW": 0.3}
GPA_THRESHOLDS = {"EXCELLENT": 3.5, "GOOD": 3.0, "FAIR": 2.5}

IELTS_POINTS = {"EXCELLENT": 2.0, "GOOD": 1.5, "FAIR": 0.8, "LOW": 0.2}
IELTS_THRESHOLDS = {"EXCELLENT": 6.5, "GOOD": 6.0, "FAIR": 5.5}

BUDGET_POINTS = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0, "MINIMAL": 0.2}
BUDGET_THRESHOLDS_USD = {"HIGH": 25000, "MEDIUM": 15000, "LOW": 8000}

GAP_POINTS = {"NONE_TO_ONE": 1.5, "TWO": 1.0, "THREE_TO_FIVE": 0.5, "OVER_FIVE": 0}

COUNTRY_SPECIFICITY_POINTS = {"SPECIFIC": 1.0, "ANY": 0.4}

CLASSIFICATION_THRESHOLDS = {"HOT": 7.0, "WARM": 4.0}

# Business-rule override, independent of the point rubric above: a student
# whose stated budget falls below realistic proof-of-funds/tuition minimums
# is not a realistically convertible "Hot" lead no matter how strong their
# academics are. Caps (never raises) classification.
MIN_VIABLE_BUDGET_USD = BUDGET_THRESHOLDS_USD["LOW"]


class StudentProfile(TypedDict):
    gpa: float
    ielts: float
    budget: float
    gap: int
    preferredCountry: str
    academicBackground: str
    careerGoals: str
    migrationIntent: str


@dataclass
class LeadScoreResult:
    score: float
    status: str
    breakdown: dict[str, float]


def _score_gpa(gpa: float) -> float:
    if gpa >= GPA_THRESHOLDS["EXCELLENT"]:
        return GPA_POINTS["EXCELLENT"]
    if gpa >= GPA_THRESHOLDS["GOOD"]:
        return GPA_POINTS["GOOD"]
    if gpa >= GPA_THRESHOLDS["FAIR"]:
        return GPA_POINTS["FAIR"]
    return GPA_POINTS["LOW"]


def _score_ielts(ielts: float) -> float:
    if ielts >= IELTS_THRESHOLDS["EXCELLENT"]:
        return IELTS_POINTS["EXCELLENT"]
    if ielts >= IELTS_THRESHOLDS["GOOD"]:
        return IELTS_POINTS["GOOD"]
    if ielts >= IELTS_THRESHOLDS["FAIR"]:
        return IELTS_POINTS["FAIR"]
    return IELTS_POINTS["LOW"]


def _score_budget(budget: float) -> float:
    if budget >= BUDGET_THRESHOLDS_USD["HIGH"]:
        return BUDGET_POINTS["HIGH"]
    if budget >= BUDGET_THRESHOLDS_USD["MEDIUM"]:
        return BUDGET_POINTS["MEDIUM"]
    if budget >= BUDGET_THRESHOLDS_USD["LOW"]:
        return BUDGET_POINTS["LOW"]
    return BUDGET_POINTS["MINIMAL"]


def _score_gap(gap: int) -> float:
    if gap <= 1:
        return GAP_POINTS["NONE_TO_ONE"]
    if gap == 2:
        return GAP_POINTS["TWO"]
    if gap <= 5:
        return GAP_POINTS["THREE_TO_FIVE"]
    return GAP_POINTS["OVER_FIVE"]


def _score_country(preferred_country: str) -> float:
    if preferred_country == PREFERRED_COUNTRY_ANY or not preferred_country:
        return COUNTRY_SPECIFICITY_POINTS["ANY"]
    return COUNTRY_SPECIFICITY_POINTS["SPECIFIC"]


def score_lead(profile: StudentProfile) -> LeadScoreResult:
    """Pure function — no I/O, no LLM call. Deterministic and unit-testable."""
    breakdown = {
        "gpa": _score_gpa(profile["gpa"]),
        "ielts": _score_ielts(profile["ielts"]),
        "budget": _score_budget(profile["budget"]),
        "gap": _score_gap(profile["gap"]),
        "countrySpecificity": _score_country(profile["preferredCountry"]),
    }
    raw_score = sum(breakdown.values())
    score = round(raw_score * 100) / 100

    if score >= CLASSIFICATION_THRESHOLDS["HOT"]:
        status = "Hot"
    elif score >= CLASSIFICATION_THRESHOLDS["WARM"]:
        status = "Warm"
    else:
        status = "Cold"

    # Budget-viability override — see MIN_VIABLE_BUDGET_USD doc comment above.
    if status == "Hot" and profile["budget"] < MIN_VIABLE_BUDGET_USD:
        status = "Warm"

    return LeadScoreResult(score=score, status=status, breakdown=breakdown)


def student_row_to_profile(row: Any) -> StudentProfile:
    """Reconstructs a StudentProfile from a persisted row, e.g. to personalize a
    later chat turn or document check against the profile submitted earlier in
    the same session. Defaults are a neutral mid-point, not a real guess, for
    rows predating academic_background/etc."""
    return {
        "gpa": row["gpa"],
        "ielts": row["ielts"],
        "budget": row["budget"],
        "gap": row["gap"],
        "preferredCountry": row["preferred_country"] or PREFERRED_COUNTRY_ANY,
        "academicBackground": row["academic_background"] or "bachelors",
        "careerGoals": row["career_goals"] or "",
        "migrationIntent": row["migration_intent"] or "undecided",
    }
