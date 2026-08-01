from app.services.lead_scoring import (
    MIN_VIABLE_BUDGET_USD,
    PREFERRED_COUNTRY_ANY,
    score_lead,
    student_row_to_profile,
)


def _profile(**overrides):
    base = {
        "gpa": 3.0,
        "ielts": 6.0,
        "budget": 15000,
        "gap": 1,
        "preferredCountry": "Australia",
        "academicBackground": "bachelors",
        "careerGoals": "",
        "migrationIntent": "undecided",
    }
    base.update(overrides)
    return base


def test_strong_profile_is_hot():
    result = score_lead(_profile(gpa=3.8, ielts=7.0, budget=30000, gap=0))
    assert result.status == "Hot"
    assert result.score >= 7.0


def test_weak_profile_is_cold():
    result = score_lead(_profile(gpa=2.0, ielts=5.0, budget=5000, gap=8))
    assert result.status == "Cold"


def test_hot_score_capped_to_warm_below_min_viable_budget():
    """Business-rule override: strong academics but unrealistic budget must
    never classify as Hot, regardless of the point total."""
    result = score_lead(_profile(gpa=4.0, ielts=9.0, budget=MIN_VIABLE_BUDGET_USD - 1, gap=0))
    assert result.status != "Hot"


def test_any_country_scores_lower_than_specific_country():
    specific = score_lead(_profile(preferredCountry="Australia"))
    any_country = score_lead(_profile(preferredCountry=PREFERRED_COUNTRY_ANY))
    assert specific.score > any_country.score


def test_student_row_to_profile_defaults_missing_fields():
    row = {
        "gpa": 3.5, "ielts": 6.5, "budget": 20000, "gap": 0,
        "preferred_country": None, "academic_background": None,
        "career_goals": None, "migration_intent": None,
    }
    profile = student_row_to_profile(row)
    assert profile["preferredCountry"] == PREFERRED_COUNTRY_ANY
    assert profile["academicBackground"] == "bachelors"
    assert profile["migrationIntent"] == "undecided"
