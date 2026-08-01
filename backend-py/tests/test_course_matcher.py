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
    assert "IELTS" in text


# --- regression: the old format crammed everything into one dense run-on
# line per course ("- Name (Level) — Country, partner institution... IELTS
# required: 5.5. Fee: $1000.0/year...") which was genuinely hard to read in
# a narrow chat bubble. Now a numbered, two-line card per course with clean
# number formatting. ---
def test_format_courses_for_prompt_is_readable_multiline_cards(seeded_courses):
    matches = match_courses(seeded_courses, _profile(preferredCountry="Japan", ielts=5.5))
    text = format_courses_for_prompt(matches.primary)
    assert text.startswith("1. ")
    assert "$1000.0" not in text  # old ugly float formatting
    assert "partner institution (specific university not listed)" not in text


def test_format_duration_converts_fractional_years_to_months():
    from app.services.course_matcher import format_duration

    assert format_duration(0.1) == "1 month"
    assert format_duration(1.0) == "1 yr"
    assert format_duration(2.0) == "2 yrs"
    assert format_duration(None) == "duration n/a"


def test_format_fee_uses_thousands_separator_no_trailing_decimal():
    from app.services.course_matcher import format_fee

    assert format_fee(1000) == "$1,000/year"
    assert format_fee(24000.0) == "$24,000/year"
    assert format_fee(None) == "fee n/a"


# --- regression: profile report and study path both repeated "at a partner
# institution (Country)" for every course without a listed university,
# reading very robotic when 3 courses in a row all lacked one ---
def test_format_course_location_omits_partner_institution_filler():
    from app.services.course_matcher import format_course_location

    assert format_course_location({"university": None, "country": "Australia"}) == "Australia"
    assert format_course_location({"university": "University of Melbourne", "country": "Australia"}) == "University of Melbourne, Australia"
