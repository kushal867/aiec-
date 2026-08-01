from app.services.course_matcher import match_courses
from app.services.profile_report import generate_structured_profile_report


def _profile(**overrides):
    base = {
        "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1,
        "preferredCountry": "Australia", "academicBackground": "bachelors",
        "careerGoals": "", "migrationIntent": "undecided",
    }
    base.update(overrides)
    return base


def test_healthy_match_produces_real_course_names_and_fee_range(seeded_courses):
    profile = _profile(preferredCountry="Australia", ielts=6.0)
    matches = match_courses(seeded_courses, profile)
    report = generate_structured_profile_report(seeded_courses, profile, matches, alternatives_allowed=True)
    assert "Diploma in Hospitality" in report.summary
    assert report.recommendedCountries == ["Australia"]
    assert len(report.nextSteps) > 0


# --- regression: IELTS below the entire catalog's minimum used to produce a
# flat "we don't have a course that matches" dead end instead of a specific,
# actionable reason ---
def test_ielts_below_catalog_minimum_gives_specific_actionable_reason(seeded_courses):
    profile = _profile(preferredCountry="Australia", ielts=1.0)
    matches = match_courses(seeded_courses, profile)
    assert not matches.primary and not matches.alternatives  # confirms this is genuinely the no-match case

    report = generate_structured_profile_report(seeded_courses, profile, matches, alternatives_allowed=True)
    assert "5.5" in report.summary  # the real minimum from the fixture data, not a made-up number
    assert "IELTS preparation" in " ".join(report.nextSteps)
    assert report.recommendedCountries == []


def test_unmatched_country_falls_back_to_priority_country_alternatives(seeded_courses):
    """Germany has zero courses in the fixture, but match_courses() already
    falls back to the priority countries (USA/UK/Australia) as alternatives
    — this is the normal "no exact match, here are other options" path, not
    the full no-match dead end."""
    profile = _profile(preferredCountry="Germany")
    matches = match_courses(seeded_courses, profile)
    assert not matches.primary
    assert matches.alternatives  # the priority-country fallback found something

    report = generate_structured_profile_report(seeded_courses, profile, matches, alternatives_allowed=True)
    assert "Germany" in report.summary
    assert set(report.recommendedCountries) <= {"USA", "UK", "Australia"}


def test_country_with_truly_nothing_available_gets_the_no_match_message(seeded_courses):
    """Germany with an IELTS low enough to also exclude the priority-country
    alternatives — genuinely nothing anywhere — must fall to the dedicated
    no-match report, not silently show an empty course list."""
    profile = _profile(preferredCountry="Germany", ielts=1.0)
    matches = match_courses(seeded_courses, profile)
    assert not matches.primary and not matches.alternatives

    report = generate_structured_profile_report(seeded_courses, profile, matches, alternatives_allowed=True)
    assert "Germany" in report.summary
    assert "different country" in report.summary or "counsellor" in report.summary
    assert report.recommendedCountries == []
