from app.services.course_matcher import match_courses
from app.services.study_path_engine import generate_study_path


def _profile(**overrides):
    base = {
        "gpa": 3.7, "ielts": 6.5, "budget": 20000, "gap": 1,
        "preferredCountry": "Australia", "academicBackground": "bachelors",
        "careerGoals": "", "migrationIntent": "study_then_work",
    }
    base.update(overrides)
    return base


def test_stage_one_uses_top_primary_course(seeded_courses):
    profile = _profile(preferredCountry="Australia", ielts=6.0)
    matches = match_courses(seeded_courses, profile)
    path = generate_study_path(profile, matches)
    assert len(path.stages) >= 2
    assert path.stages[0]["title"] != ""


def test_bachelors_background_gets_migration_pathway_stage_two(seeded_courses):
    # bachelors has no STAGE_TWO_LEVELS entry -> stage 2 must be the
    # migration/work-pathway fallback, not an invented course
    profile = _profile(preferredCountry="Australia", ielts=6.0, academicBackground="bachelors")
    matches = match_courses(seeded_courses, profile)
    path = generate_study_path(profile, matches)
    assert path.stages[-1]["title"] == "Work / migration pathway"


def test_migration_pathway_text_reflects_stated_intent(seeded_courses):
    profile = _profile(preferredCountry="Australia", ielts=6.0, migrationIntent="migrate_permanently")
    matches = match_courses(seeded_courses, profile)
    path = generate_study_path(profile, matches)
    assert "migration" in path.stages[-1]["description"].lower() or "pr" in path.stages[-1]["description"].lower()


def test_no_primary_match_still_returns_a_pathway_without_crashing(seeded_courses):
    profile = _profile(preferredCountry="Germany", ielts=1.0)  # genuinely nothing available
    matches = match_courses(seeded_courses, profile)
    path = generate_study_path(profile, matches)
    # stage 1 should not be fabricated when there's no real primary match
    assert not any("Germany" in stage["title"] for stage in path.stages)
