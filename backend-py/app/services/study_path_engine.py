from dataclasses import dataclass, field

from app.db import get_db, query_courses
from app.services.course_matcher import CourseMatchResult, format_course_location, format_duration
from app.services.lead_scoring import PRIORITY_COUNTRIES, StudentProfile

# No LLM here — stage 1 is the top primary course match, stage 2 is the top
# stage-2-eligible course match if one exists, else a fixed migration/work
# pathway sentence keyed off migrationIntent. No narrative connecting them
# beyond that — a real one needs reasoning this system no longer has.

# What a student could realistically move into AFTER their stage-1 eligible
# level, using only course levels that actually exist in the data (mirrors
# course_matcher.py's ELIGIBLE_LEVELS_BY_BACKGROUND for stage 1).
_STAGE_TWO_LEVELS_BY_BACKGROUND = {"high_school": ["Postgraduate", "PG Diploma"]}

_MIGRATION_PATHWAY_TEXT = {
    "study_only": "Complete your studies and return home — no further formal stage is planned.",
    "study_then_work": "After graduating, look into post-study work options in your destination country with your counsellor.",
    "migrate_permanently": "After graduating, discuss permanent migration/PR pathways for your destination country with your counsellor.",
    "undecided": "Once you've completed stage 1, your counsellor can help you decide on next steps based on how your plans develop.",
}


@dataclass
class StudyPath:
    stages: list[dict] = field(default_factory=list)


def generate_study_path(profile: StudentProfile, matches: CourseMatchResult) -> StudyPath:
    stages: list[dict] = []

    if matches.primary:
        top = matches.primary[0]
        stages.append(
            {
                "title": f"{top['course_name']} ({format_course_location(top)})",
                "description": "Your top-matching course based on your stated profile and budget.",
                "estimatedTimeframe": format_duration(top.get("duration_years")),
            }
        )

    stage2_levels = _STAGE_TWO_LEVELS_BY_BACKGROUND.get(profile["academicBackground"])
    stage2_courses = []
    if stage2_levels:
        countries = matches.primary_countries if matches.primary_countries else list(PRIORITY_COUNTRIES)
        stage2_courses = query_courses(
            get_db(), countries=countries, course_levels=stage2_levels, max_ielts=profile["ielts"], limit=5
        )

    if stage2_courses:
        top2 = stage2_courses[0]
        stages.append(
            {
                "title": f"{top2['course_name']} ({format_course_location(top2)})",
                "description": "A natural next step after stage 1, based on the course levels available in our database.",
                "estimatedTimeframe": format_duration(top2["duration_years"]),
            }
        )
    else:
        stages.append(
            {
                "title": "Work / migration pathway",
                "description": _MIGRATION_PATHWAY_TEXT.get(
                    profile["migrationIntent"], _MIGRATION_PATHWAY_TEXT["undecided"]
                ),
                "estimatedTimeframe": "After graduation",
            }
        )

    return StudyPath(stages=stages)
