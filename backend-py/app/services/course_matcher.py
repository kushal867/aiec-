import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from app.db import query_courses
from app.services.lead_scoring import PREFERRED_COUNTRY_ANY, PRIORITY_COUNTRIES, StudentProfile

# "Advanced recommendation system" (brief Phase 3) — a documented, weighted
# fit score per matched course, replacing plain cheapest-first ordering.
# Deliberately rule-based (not a trained ranker): every point is traceable to
# a specific reason, which the AI report and CRM view can both surface
# verbatim instead of an opaque score. Retune weights here; they sum to 100.
MATCH_SCORE_WEIGHTS = {
    "BUDGET_FIT": 40,
    "COUNTRY_PRIORITY": 20,
    "IELTS_HEADROOM": 15,
    "CAREER_RELEVANCE": 25,
}

_STOPWORDS = {"the", "and", "for", "with", "into", "from", "that", "this", "have", "want", "will"}


def _career_goal_tokens(career_goals: str) -> list[str]:
    tokens = re.split(r"[^a-z]+", career_goals.lower())
    return [t for t in tokens if len(t) > 3 and t not in _STOPWORDS]


def _course_val(course: Any, key: str) -> Any:
    return course[key] if isinstance(course, sqlite3.Row) else course.get(key)


def _compute_match_score(course: Any, profile: StudentProfile) -> tuple[int, list[str]]:
    """Pure function — no I/O, no LLM call. Every sub-score is independently
    documented so the reasons list is always literally true, never a guess."""
    reasons: list[str] = []
    score = 0.0

    fee_per_year = _course_val(course, "fee_per_year")
    if fee_per_year is None:
        score += MATCH_SCORE_WEIGHTS["BUDGET_FIT"] * 0.5
    elif fee_per_year <= profile["budget"]:
        score += MATCH_SCORE_WEIGHTS["BUDGET_FIT"]
        reasons.append("Within stated budget")
    else:
        overage_ratio = (fee_per_year - profile["budget"]) / profile["budget"]
        partial = max(0.0, MATCH_SCORE_WEIGHTS["BUDGET_FIT"] * (1 - overage_ratio))
        score += partial
        if partial > 0:
            reasons.append("Above budget, but not by a large margin")

    country = _course_val(course, "country")
    has_specific_country = bool(profile["preferredCountry"]) and profile["preferredCountry"] != PREFERRED_COUNTRY_ANY
    if has_specific_country and country == profile["preferredCountry"]:
        score += MATCH_SCORE_WEIGHTS["COUNTRY_PRIORITY"]
        reasons.append("Matches your preferred country")
    elif country in PRIORITY_COUNTRIES:
        score += MATCH_SCORE_WEIGHTS["COUNTRY_PRIORITY"] * 0.5
        reasons.append("In a priority destination country")

    ielts_required = _course_val(course, "ielts_required")
    if ielts_required is None:
        score += MATCH_SCORE_WEIGHTS["IELTS_HEADROOM"] * 0.5
    else:
        headroom = max(0.0, profile["ielts"] - ielts_required)
        headroom_fraction = min(1.0, headroom / 1.0)
        score += MATCH_SCORE_WEIGHTS["IELTS_HEADROOM"] * (0.5 + 0.5 * headroom_fraction)
        if headroom > 0:
            reasons.append("Comfortably meets the IELTS requirement")

    tokens = _career_goal_tokens(profile["careerGoals"])
    course_name_lower = _course_val(course, "course_name").lower()
    matched_token = next((t for t in tokens if t in course_name_lower), None)
    if matched_token:
        score += MATCH_SCORE_WEIGHTS["CAREER_RELEVANCE"]
        reasons.append(f'Relevant to your stated career goals ("{matched_token}")')

    return round(min(100, score)), reasons


def _row_to_dict(course: Any) -> dict[str, Any]:
    return dict(course) if isinstance(course, sqlite3.Row) else dict(course)


def _score_and_sort(courses: list[Any], profile: StudentProfile) -> list[dict[str, Any]]:
    scored = []
    for course in courses:
        match_score, reasons = _compute_match_score(course, profile)
        row = _row_to_dict(course)
        row["matchScore"] = match_score
        row["matchReasons"] = reasons
        scored.append(row)
    scored.sort(key=lambda c: c["matchScore"], reverse=True)
    return scored


PRIMARY_LIMIT = 8
ALTERNATIVE_LIMIT = 6

# Soft eligibility mapping for course_level (real values: Undergraduate,
# Postgraduate, Diploma, PG Diploma, Certificate, Language, Foundation) — a
# bachelor's holder progresses to postgrad study, not back into an
# undergraduate seat, etc. Kept soft (applied, then dropped if it
# under-returns) because a hard gate on top of country/IELTS filtering over a
# 406-row table can easily zero out results.
ELIGIBLE_LEVELS_BY_BACKGROUND = {
    "high_school": ["Foundation", "Language", "Certificate", "Diploma", "Undergraduate"],
    "bachelors": ["Postgraduate", "PG Diploma", "Certificate", "Diploma"],
    "masters": ["Postgraduate", "PG Diploma"],
    "phd": ["Postgraduate", "PG Diploma"],
}

# Below this many results, the academic-background filter is considered to be
# over-constraining (combined with country/IELTS) and is dropped in favor of
# showing the student something rather than a near-empty list.
MIN_RESULTS_FOR_SOFT_FILTER = 3


def _query_with_soft_level_filter(
    conn: sqlite3.Connection,
    academic_background: str | None,
    **filters: Any,
) -> list[sqlite3.Row]:
    if not academic_background:
        return query_courses(conn, **filters)
    levels = ELIGIBLE_LEVELS_BY_BACKGROUND[academic_background]
    filtered = query_courses(conn, course_levels=levels, **filters)
    return filtered if len(filtered) >= MIN_RESULTS_FOR_SOFT_FILTER else query_courses(conn, **filters)


@dataclass
class CourseMatchResult:
    primary: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    primary_countries: list[str] = field(default_factory=list)


def match_courses(conn: sqlite3.Connection, profile: StudentProfile) -> CourseMatchResult:
    """Structured (SQL-filtered, not vector search) course matching. IELTS is a
    hard eligibility gate; budget is NOT a hard cutoff — fee data quality
    varies (some rows in local currency, not USD), so a hard budget filter
    could silently return zero results. Courses sort cheapest-first and the
    AI report explains fee fit explicitly instead."""
    has_specific_country = bool(profile["preferredCountry"]) and profile["preferredCountry"] != PREFERRED_COUNTRY_ANY

    if has_specific_country:
        primary_rows = _query_with_soft_level_filter(
            conn,
            profile["academicBackground"],
            countries=[profile["preferredCountry"]],
            max_ielts=profile["ielts"],
            limit=PRIMARY_LIMIT,
        )

        alt_countries = [c for c in PRIORITY_COUNTRIES if c != profile["preferredCountry"]]
        alt_rows = _query_with_soft_level_filter(
            conn,
            profile["academicBackground"],
            countries=alt_countries,
            max_ielts=profile["ielts"],
            limit=ALTERNATIVE_LIMIT,
        )
        if not alt_rows:
            alt_rows = [
                r
                for r in query_courses(conn, max_ielts=profile["ielts"], limit=ALTERNATIVE_LIMIT)
                if r["country"] != profile["preferredCountry"]
            ]

        return CourseMatchResult(
            primary=_score_and_sort(primary_rows, profile),
            alternatives=_score_and_sort(alt_rows, profile),
            primary_countries=[profile["preferredCountry"]],
        )

    # No specific preference: lead with Australia, Canada, USA.
    primary_rows = _query_with_soft_level_filter(
        conn,
        profile["academicBackground"],
        countries=list(PRIORITY_COUNTRIES),
        max_ielts=profile["ielts"],
        limit=PRIMARY_LIMIT,
    )
    alt_rows = [
        r
        for r in query_courses(conn, max_ielts=profile["ielts"], limit=ALTERNATIVE_LIMIT + PRIMARY_LIMIT)
        if r["country"] not in PRIORITY_COUNTRIES
    ]

    return CourseMatchResult(
        primary=_score_and_sort(primary_rows, profile),
        alternatives=_score_and_sort(alt_rows, profile)[:ALTERNATIVE_LIMIT],
        primary_countries=list(PRIORITY_COUNTRIES),
    )


@dataclass
class NoMatchDiagnosis:
    reason: str  # "ielts_below_minimum" | "no_courses_for_country"
    minIelts: float | None = None


def diagnose_no_match(conn: sqlite3.Connection, profile: StudentProfile) -> NoMatchDiagnosis:
    """When match_courses() returns nothing at all, a flat "no course found"
    is a dead end — this figures out the actual, real reason by re-querying
    without the IELTS gate (the only hard eligibility filter in
    match_courses()) so the report can tell the student a specific, honest
    next step (e.g. the real minimum IELTS score in their target
    country/countries) instead of just shrugging."""
    has_specific_country = bool(profile["preferredCountry"]) and profile["preferredCountry"] != PREFERRED_COUNTRY_ANY
    countries = [profile["preferredCountry"]] if has_specific_country else None

    without_ielts_gate = query_courses(conn, countries=countries, limit=50)
    if not without_ielts_gate:
        return NoMatchDiagnosis(reason="no_courses_for_country")

    ielts_values = [c["ielts_required"] for c in without_ielts_gate if c["ielts_required"] is not None]
    return NoMatchDiagnosis(reason="ielts_below_minimum", minIelts=min(ielts_values) if ielts_values else None)


def format_fee(fee_per_year: float | None) -> str:
    if fee_per_year is None:
        return "fee n/a"
    return f"${fee_per_year:,.0f}/year"


def format_duration(duration_years: float | None) -> str:
    if duration_years is None:
        return "duration n/a"
    if duration_years < 1:
        months = round(duration_years * 12)
        return f"{months} month" + ("" if months == 1 else "s")
    if duration_years == int(duration_years):
        years = int(duration_years)
        return f"{years} yr" + ("" if years == 1 else "s")
    return f"{duration_years} yrs"


def format_course_location(course: Any) -> str:
    """"University, Country" when a specific university is on file, else
    just "Country" — deliberately drops the old "at a partner institution
    (specific university not listed)" filler. Repeating that phrase for
    every course in a list read as robotic and added no information; simply
    omitting it when there's nothing to say is more honest and reads much
    more naturally."""
    d = _row_to_dict(course) if not isinstance(course, dict) else course
    return f"{d['university']}, {d['country']}" if d.get("university") else d["country"]


def format_courses_for_prompt(courses: list[Any]) -> str:
    """Renders courses for direct display in the chat widget — a numbered,
    two-line card per course (name/location, then key facts), not one dense
    run-on sentence. The widget preserves newlines (white-space: pre-wrap)
    but doesn't render markdown, so formatting is plain text only."""
    if not courses:
        return "(no matching courses found)"

    lines = []
    for i, c in enumerate(courses, start=1):
        d = _row_to_dict(c) if not isinstance(c, dict) else c
        location = format_course_location(d)
        ielts = f"IELTS {d['ielts_required']}+" if d.get("ielts_required") is not None else "IELTS n/a"
        facts = " · ".join(
            [d["course_level"], ielts, format_fee(d.get("fee_per_year")), format_duration(d.get("duration_years"))]
        )
        intake = d.get("intake")
        if intake:
            facts += f" · Intake: {intake}"
        lines.append(f"{i}. {d['course_name']} — {location}\n   {facts}")
    return "\n".join(lines)
