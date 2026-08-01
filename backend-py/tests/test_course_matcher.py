from app.services.course_matcher import diagnose_no_match, format_courses_for_prompt, match_courses
from app.services.lead_scoring import PREFERRED_COUNTRY_ANY


def _profile(**overrides):
    base = {
        "gpa": 3.5, "ielts": 6.5, "budget": 20000, "gap": 1,
        "preferredCountry": "Australia", "academicBackground": "bachelors",
        "careerGoals": "", "migrationIntent": "undecided",
    }
    base.update(overrides)
    return base


def test_specific_country_preference_is_respected(seeded_courses):
    matches = match_courses(seeded_courses, _profile(preferredCountry="Japan", ielts=5.5))
    assert matches.primary_countries == ["Japan"]
    assert all(c["country"] == "Japan" for c in matches.primary)


def test_any_preference_defaults_to_priority_countries(seeded_courses):
    matches = match_courses(seeded_courses, _profile(preferredCountry=PREFERRED_COUNTRY_ANY))
    assert matches.primary_countries == ["USA", "UK", "Australia"]


def test_ielts_is_a_hard_eligibility_gate(seeded_courses):
    # Bachelor in Nursing (Australia) in the fixture requires IELTS 7.0
    matches = match_courses(seeded_courses, _profile(preferredCountry="Australia", ielts=6.0))
    assert all(c["ielts_required"] is None or c["ielts_required"] <= 6.0 for c in matches.primary)
    names = {c["course_name"] for c in matches.primary}
    assert "Bachelor in Nursing" not in names


def test_diagnose_no_match_when_ielts_below_catalog_minimum(seeded_courses):
    diagnosis = diagnose_no_match(seeded_courses, _profile(preferredCountry="Australia", ielts=1.0))
    assert diagnosis.reason == "ielts_below_minimum"
    assert diagnosis.minIelts == 5.5  # Diploma in Hospitality, the fixture's lowest for Australia


def test_diagnose_no_match_when_country_has_no_courses_at_all(seeded_courses):
    diagnosis = diagnose_no_match(seeded_courses, _profile(preferredCountry="Germany"))
    assert diagnosis.reason == "no_courses_for_country"
    assert diagnosis.minIelts is None


def test_format_courses_for_prompt_handles_empty_list():
    assert format_courses_for_prompt([]) == "(no matching courses found)"


def test_format_courses_for_prompt_includes_key_fields(seeded_courses):
    matches = match_courses(seeded_courses, _profile(preferredCountry="Japan", ielts=5.5))
    text = format_courses_for_prompt(matches.primary)
    assert "Japan" in text
    assert "IELTS required" in text
