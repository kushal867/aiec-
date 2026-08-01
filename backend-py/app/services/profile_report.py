import sqlite3
from dataclasses import dataclass, field

from app.services.course_matcher import CourseMatchResult, diagnose_no_match
from app.services.lead_scoring import ACADEMIC_BACKGROUND_LABELS, StudentProfile

# No LLM here — the report is assembled from match_courses()'s already-
# structured output (fee/country/matchScore/matchReasons) via fixed
# templates. It won't read as fluidly as Claude's version and won't draw
# connections beyond what's explicitly encoded in matchReasons (see
# course_matcher.py) — deliberately not inventing a narrative the data
# doesn't support. When there's genuinely no eligible course (e.g. IELTS
# below every program's requirement), diagnose_no_match() gives a specific,
# real reason instead of a flat "nothing found."

_NEXT_STEPS = [
    "Upload your citizenship/ID document",
    "Upload your academic transcript",
    "Book or upload your IELTS certificate if you haven't already",
    "Confirm your preferred course with your counsellor",
    "Await counsellor review and application submission",
]

_IELTS_PREP_NEXT_STEPS = [
    "Book an IELTS preparation course to raise your score",
    "Retake the IELTS test once you're ready",
    "Come back and re-submit your profile with your updated score",
    "In the meantime, feel free to chat with us about country/course options for when you're ready",
]


@dataclass
class ProfileReport:
    summary: str
    recommendedCountries: list[str] = field(default_factory=list)
    nextSteps: list[str] = field(default_factory=list)


def _fee_range(courses: list[dict]) -> tuple[float, float] | None:
    fees = [c["fee_per_year"] for c in courses if c.get("fee_per_year") is not None]
    return (min(fees), max(fees)) if fees else None


def _course_line(c: dict) -> str:
    university = c.get("university") or "a partner institution"
    return f"{c['course_name']} at {university} ({c['country']})"


def _no_match_report(conn: sqlite3.Connection, profile: StudentProfile) -> ProfileReport:
    diagnosis = diagnose_no_match(conn, profile)

    if diagnosis.reason == "ielts_below_minimum" and diagnosis.minIelts is not None:
        summary = (
            f"Thanks for sharing your profile! Right now your IELTS score of {profile['ielts']} is below what "
            f"our programs require — the lowest entry requirement we have on file is {diagnosis.minIelts}, so "
            f"nothing currently matches. This is very fixable: an IELTS preparation course to bring your score "
            f"up to at least {diagnosis.minIelts} would open up real options for you. Once you've retaken the "
            f"test, come back and we'll show you exactly what you're eligible for."
        )
        return ProfileReport(summary=summary, recommendedCountries=[], nextSteps=list(_IELTS_PREP_NEXT_STEPS))

    country = profile["preferredCountry"]
    summary = (
        f"Thanks for sharing your profile! We don't currently have any programs on file for {country} — "
        "you're welcome to try a different country, or chat with us and a counsellor can look into options "
        "beyond our current database."
    )
    return ProfileReport(summary=summary, recommendedCountries=[], nextSteps=[])


def generate_structured_profile_report(
    conn: sqlite3.Connection, profile: StudentProfile, matches: CourseMatchResult, alternatives_allowed: bool
) -> ProfileReport:
    primary = matches.primary

    if not primary and not matches.alternatives:
        return _no_match_report(conn, profile)

    background_label = ACADEMIC_BACKGROUND_LABELS.get(profile["academicBackground"], profile["academicBackground"])
    sentences: list[str] = [
        f"Thanks for sharing your profile! Based on your GPA of {profile['gpa']}, IELTS score of {profile['ielts']}, "
        f"and budget of ${profile['budget']:,.0f}/year, here's what looks like a good fit for you."
    ]

    fee_range = _fee_range(primary)
    if fee_range:
        low, high = fee_range
        if high <= profile["budget"]:
            fee_sentence = f"Matched programs in {', '.join(matches.primary_countries)} range from ${low:,.0f} to ${high:,.0f} per year, comfortably within your budget."
        else:
            over_by = high - profile["budget"]
            fee_sentence = (
                f"Matched programs in {', '.join(matches.primary_countries)} range from ${low:,.0f} to ${high:,.0f} "
                f"per year — worth noting the higher end runs about ${over_by:,.0f} over your stated budget."
            )
        sentences.append(fee_sentence)

    if primary:
        top_lines = ", ".join(_course_line(c) for c in primary[:3])
        sentences.append(f"A few of your top matches: {top_lines}.")
    else:
        alt_countries = sorted({c["country"] for c in matches.alternatives})
        sentences.append(
            f"We don't have an exact match in {', '.join(matches.primary_countries)} for your preferences, "
            f"but there are options in {', '.join(alt_countries)} worth a look below."
        )

    if alternatives_allowed and matches.alternatives and primary:
        alt_countries = sorted({c["country"] for c in matches.alternatives})
        sentences.append(f"If you'd like more options, {', '.join(alt_countries)} are also worth considering.")

    if primary:
        sentences.append(
            f"Since you're a {background_label.lower()} applicant, the course levels above reflect what you're eligible for."
        )

    recommended_countries = list(matches.primary_countries) if primary else sorted({c["country"] for c in matches.alternatives})

    return ProfileReport(summary=" ".join(sentences), recommendedCountries=recommended_countries, nextSteps=list(_NEXT_STEPS))
