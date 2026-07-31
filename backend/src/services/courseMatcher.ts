import { getDb, queryCourses, type CourseRow } from "./db";
import { PREFERRED_COUNTRY_ANY, PRIORITY_COUNTRIES, type AcademicBackground, type StudentProfile } from "./leadScoring";

export interface ScoredCourseRow extends CourseRow {
  /** 0-100. Transparent, rule-based ranking — see computeMatchScore(). Not a black-box ML model. */
  matchScore: number;
  matchReasons: string[];
}

export interface CourseMatchResult {
  /** Courses in the country(ies) that should be presented first, best-fit first. */
  primary: ScoredCourseRow[];
  /** Courses in other countries, offered as alternatives, best-fit first. */
  alternatives: ScoredCourseRow[];
  primaryCountries: string[];
}

// "Advanced recommendation system" (brief Phase 3) — a documented, weighted
// fit score per matched course, replacing plain cheapest-first ordering.
// Deliberately rule-based (not a trained ranker): every point is traceable
// to a specific reason, which the AI report and CRM view can both surface
// verbatim instead of an opaque score. Retune weights here; they sum to 100.
export const MATCH_SCORE_WEIGHTS = {
  BUDGET_FIT: 40,
  COUNTRY_PRIORITY: 20,
  IELTS_HEADROOM: 15,
  CAREER_RELEVANCE: 25,
} as const;

const STOPWORDS = new Set(["the", "and", "for", "with", "into", "from", "that", "this", "have", "want", "will"]);

function careerGoalTokens(careerGoals: string): string[] {
  return careerGoals
    .toLowerCase()
    .split(/[^a-z]+/)
    .filter((token) => token.length > 3 && !STOPWORDS.has(token));
}

/**
 * Pure function — no I/O, no LLM call. Every sub-score is independently
 * documented so the reasons list is always literally true, never a guess.
 */
function computeMatchScore(course: CourseRow, profile: StudentProfile): { score: number; reasons: string[] } {
  const reasons: string[] = [];
  let score = 0;

  // Budget fit: full marks if affordable outright; degrades toward 0 as the
  // fee climbs past budget (reaches 0 once it's roughly double the budget).
  if (course.fee_per_year == null) {
    score += MATCH_SCORE_WEIGHTS.BUDGET_FIT * 0.5;
  } else if (course.fee_per_year <= profile.budget) {
    score += MATCH_SCORE_WEIGHTS.BUDGET_FIT;
    reasons.push("Within stated budget");
  } else {
    const overageRatio = (course.fee_per_year - profile.budget) / profile.budget;
    const partial = Math.max(0, MATCH_SCORE_WEIGHTS.BUDGET_FIT * (1 - overageRatio));
    score += partial;
    if (partial > 0) reasons.push("Above budget, but not by a large margin");
  }

  // Country priority: exact preferred-country match beats a generic
  // priority-country match beats anywhere else.
  const hasSpecificCountry = Boolean(profile.preferredCountry) && profile.preferredCountry !== PREFERRED_COUNTRY_ANY;
  if (hasSpecificCountry && course.country === profile.preferredCountry) {
    score += MATCH_SCORE_WEIGHTS.COUNTRY_PRIORITY;
    reasons.push("Matches your preferred country");
  } else if ((PRIORITY_COUNTRIES as readonly string[]).includes(course.country)) {
    score += MATCH_SCORE_WEIGHTS.COUNTRY_PRIORITY * 0.5;
    reasons.push("In a priority destination country");
  }

  // IELTS headroom: comfortably clearing the requirement scores higher than
  // just barely meeting it (less risk of falling short on the real test).
  if (course.ielts_required == null) {
    score += MATCH_SCORE_WEIGHTS.IELTS_HEADROOM * 0.5;
  } else {
    const headroom = Math.max(0, profile.ielts - course.ielts_required);
    const headroomFraction = Math.min(1, headroom / 1.0);
    score += MATCH_SCORE_WEIGHTS.IELTS_HEADROOM * (0.5 + 0.5 * headroomFraction);
    if (headroom > 0) reasons.push("Comfortably meets the IELTS requirement");
  }

  // Career relevance: simple keyword overlap between stated career goals and
  // the course name — no credit if the student didn't state a goal, or if
  // nothing in the course name plausibly connects to it (no forced link).
  const tokens = careerGoalTokens(profile.careerGoals);
  const courseNameLower = course.course_name.toLowerCase();
  const matchedToken = tokens.find((token) => courseNameLower.includes(token));
  if (matchedToken) {
    score += MATCH_SCORE_WEIGHTS.CAREER_RELEVANCE;
    reasons.push(`Relevant to your stated career goals ("${matchedToken}")`);
  }

  return { score: Math.round(Math.min(100, score)), reasons };
}

function scoreAndSort(courses: CourseRow[], profile: StudentProfile): ScoredCourseRow[] {
  return courses
    .map((course) => {
      const { score, reasons } = computeMatchScore(course, profile);
      return { ...course, matchScore: score, matchReasons: reasons };
    })
    .sort((a, b) => b.matchScore - a.matchScore);
}

const PRIMARY_LIMIT = 8;
const ALTERNATIVE_LIMIT = 6;

// Soft eligibility mapping for `course_level` (real values seen in the
// courses table: Undergraduate, Postgraduate, Diploma, PG Diploma,
// Certificate, Language, Foundation) — a bachelor's holder progresses to
// postgrad study, not back into an undergraduate seat, etc. Kept soft
// (applied, then dropped if it under-returns) because a hard gate on top of
// country/IELTS filtering over a 406-row table can easily zero out results.
const ELIGIBLE_LEVELS_BY_BACKGROUND: Record<AcademicBackground, string[]> = {
  high_school: ["Foundation", "Language", "Certificate", "Diploma", "Undergraduate"],
  bachelors: ["Postgraduate", "PG Diploma", "Certificate", "Diploma"],
  masters: ["Postgraduate", "PG Diploma"],
  phd: ["Postgraduate", "PG Diploma"],
};

// Below this many results, the academic-background filter is considered to
// be over-constraining (combined with country/IELTS) and is dropped in favor
// of showing the student something rather than a near-empty list.
const MIN_RESULTS_FOR_SOFT_FILTER = 3;

/**
 * Applies the academic-background level filter, but only keeps it if it
 * still returns enough rows — see MIN_RESULTS_FOR_SOFT_FILTER above.
 */
function queryWithSoftLevelFilter(
  db: ReturnType<typeof getDb>,
  filters: Parameters<typeof queryCourses>[1],
  academicBackground: AcademicBackground | undefined,
): CourseRow[] {
  if (!academicBackground) return queryCourses(db, filters);
  const levels = ELIGIBLE_LEVELS_BY_BACKGROUND[academicBackground];
  const filtered = queryCourses(db, { ...filters, courseLevels: levels });
  return filtered.length >= MIN_RESULTS_FOR_SOFT_FILTER ? filtered : queryCourses(db, filters);
}

/**
 * Structured (SQL-filtered, not vector search) course matching. IELTS is
 * treated as a hard eligibility gate; budget is NOT a hard cutoff — course
 * fee data quality varies (some rows are in local currency, not USD), so a
 * hard budget filter could silently return zero results. Instead, courses
 * are sorted cheapest-first and the AI report explains fee fit against the
 * student's stated budget explicitly, rather than pre-filtering it away.
 */
export function matchCourses(profile: StudentProfile): CourseMatchResult {
  const db = getDb();
  const hasSpecificCountry = Boolean(profile.preferredCountry) && profile.preferredCountry !== PREFERRED_COUNTRY_ANY;

  if (hasSpecificCountry) {
    const primary = queryWithSoftLevelFilter(
      db,
      { countries: [profile.preferredCountry], maxIelts: profile.ielts, limit: PRIMARY_LIMIT },
      profile.academicBackground,
    );

    const altCountries = PRIORITY_COUNTRIES.filter((c) => c !== profile.preferredCountry);
    let alternatives = queryWithSoftLevelFilter(
      db,
      { countries: altCountries, maxIelts: profile.ielts, limit: ALTERNATIVE_LIMIT },
      profile.academicBackground,
    );
    if (alternatives.length === 0) {
      alternatives = queryCourses(db, { maxIelts: profile.ielts, limit: ALTERNATIVE_LIMIT }).filter(
        (c) => c.country !== profile.preferredCountry,
      );
    }

    return {
      primary: scoreAndSort(primary, profile),
      alternatives: scoreAndSort(alternatives, profile),
      primaryCountries: [profile.preferredCountry],
    };
  }

  // No specific preference: lead with Australia, Canada, USA.
  const primary = queryWithSoftLevelFilter(
    db,
    { countries: [...PRIORITY_COUNTRIES], maxIelts: profile.ielts, limit: PRIMARY_LIMIT },
    profile.academicBackground,
  );
  const alternatives = queryCourses(db, { maxIelts: profile.ielts, limit: ALTERNATIVE_LIMIT + PRIMARY_LIMIT }).filter(
    (c) => !(PRIORITY_COUNTRIES as readonly string[]).includes(c.country),
  );

  return {
    primary: scoreAndSort(primary, profile),
    alternatives: scoreAndSort(alternatives, profile).slice(0, ALTERNATIVE_LIMIT),
    primaryCountries: [...PRIORITY_COUNTRIES],
  };
}

export function formatCoursesForPrompt(courses: (CourseRow | ScoredCourseRow)[]): string {
  if (courses.length === 0) return "(no matching courses found)";
  return courses
    .map((c) => {
      const university = c.university ?? "partner institution (specific university not listed)";
      const scoreLine =
        "matchScore" in c
          ? ` Fit score: ${c.matchScore}/100${c.matchReasons.length > 0 ? ` (${c.matchReasons.join("; ")})` : ""}.`
          : "";
      return `- ${c.course_name} (${c.course_level}) — ${c.country}, ${university}. IELTS required: ${c.ielts_required ?? "n/a"}. Fee: $${c.fee_per_year ?? "n/a"}/year (range ${c.fee_range ?? "n/a"}). Duration: ${c.duration_years ?? "n/a"} yrs. Intake: ${c.intake ?? "n/a"}.${scoreLine}`;
    })
    .join("\n");
}
