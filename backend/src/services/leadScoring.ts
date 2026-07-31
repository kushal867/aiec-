export type LeadStatus = "Hot" | "Warm" | "Cold";

export const PREFERRED_COUNTRY_ANY = "ANY";

export const PRIORITY_COUNTRIES = ["Australia", "Canada", "USA"] as const;

export type AcademicBackground = "high_school" | "bachelors" | "masters" | "phd";
export const ACADEMIC_BACKGROUNDS: AcademicBackground[] = ["high_school", "bachelors", "masters", "phd"];
export const ACADEMIC_BACKGROUND_LABELS: Record<AcademicBackground, string> = {
  high_school: "High school",
  bachelors: "Bachelor's degree",
  masters: "Master's degree",
  phd: "PhD",
};

export type MigrationIntent = "study_only" | "study_then_work" | "migrate_permanently" | "undecided";
export const MIGRATION_INTENTS: MigrationIntent[] = [
  "study_only",
  "study_then_work",
  "migrate_permanently",
  "undecided",
];
export const MIGRATION_INTENT_LABELS: Record<MigrationIntent, string> = {
  study_only: "Study only, then return home",
  study_then_work: "Study, then work abroad for a period",
  migrate_permanently: "Migrate/settle permanently",
  undecided: "Undecided",
};

import type { StudentRow } from "./db";

export interface StudentProfile {
  gpa: number; // 0.0 - 4.0
  ielts: number; // 0.0 - 9.0
  budget: number; // annual tuition + living, USD
  gap: number; // years since last education (integer, 0+)
  preferredCountry: string; // country name, or PREFERRED_COUNTRY_ANY
  // Brief 2.2 lists "academic background" as a lead-qualification input, and
  // 2.3 lists "career goals" + "migration intent" as recommendation-engine
  // inputs. Deliberately NOT folded into the numeric score below (that would
  // mean guessing an arbitrary weight for a soft signal) — instead used for
  // course-level eligibility matching (courseMatcher.ts) and report
  // personalization (claude.ts), which is what these inputs are actually for.
  academicBackground: AcademicBackground;
  careerGoals: string;
  migrationIntent: MigrationIntent;
}

// ---- Named, documented rubric constants — retune here, nowhere else. ----
// Scale is 0-10 total (matches the target `students.score` column, which is
// a NUMERIC(4,2) CHECK'd between 0 and 10).

export const GPA_POINTS = { EXCELLENT: 2.5, GOOD: 1.8, FAIR: 1.0, LOW: 0.3 } as const;
export const GPA_THRESHOLDS = { EXCELLENT: 3.5, GOOD: 3.0, FAIR: 2.5 } as const;

export const IELTS_POINTS = { EXCELLENT: 2.0, GOOD: 1.5, FAIR: 0.8, LOW: 0.2 } as const;
export const IELTS_THRESHOLDS = { EXCELLENT: 6.5, GOOD: 6.0, FAIR: 5.5 } as const;

export const BUDGET_POINTS = { HIGH: 3.0, MEDIUM: 2.0, LOW: 1.0, MINIMAL: 0.2 } as const;
export const BUDGET_THRESHOLDS_USD = { HIGH: 25000, MEDIUM: 15000, LOW: 8000 } as const;

export const GAP_POINTS = { NONE_TO_ONE: 1.5, TWO: 1.0, THREE_TO_FIVE: 0.5, OVER_FIVE: 0 } as const;

export const COUNTRY_SPECIFICITY_POINTS = { SPECIFIC: 1.0, ANY: 0.4 } as const;

export const CLASSIFICATION_THRESHOLDS = { HOT: 7.0, WARM: 4.0 } as const;

// Business-rule override, independent of the point rubric above: a student
// whose stated budget falls below realistic proof-of-funds/tuition minimums
// for most destination countries is not a realistically convertible "Hot"
// lead no matter how strong their academics are. Caps (never raises)
// classification — retune or delete independently of the point weights above.
export const MIN_VIABLE_BUDGET_USD = BUDGET_THRESHOLDS_USD.LOW;

export interface LeadScoreResult {
  score: number;
  status: LeadStatus;
  breakdown: {
    gpa: number;
    ielts: number;
    budget: number;
    gap: number;
    countrySpecificity: number;
  };
}

function scoreGpa(gpa: number): number {
  if (gpa >= GPA_THRESHOLDS.EXCELLENT) return GPA_POINTS.EXCELLENT;
  if (gpa >= GPA_THRESHOLDS.GOOD) return GPA_POINTS.GOOD;
  if (gpa >= GPA_THRESHOLDS.FAIR) return GPA_POINTS.FAIR;
  return GPA_POINTS.LOW;
}

function scoreIelts(ielts: number): number {
  if (ielts >= IELTS_THRESHOLDS.EXCELLENT) return IELTS_POINTS.EXCELLENT;
  if (ielts >= IELTS_THRESHOLDS.GOOD) return IELTS_POINTS.GOOD;
  if (ielts >= IELTS_THRESHOLDS.FAIR) return IELTS_POINTS.FAIR;
  return IELTS_POINTS.LOW;
}

function scoreBudget(budget: number): number {
  if (budget >= BUDGET_THRESHOLDS_USD.HIGH) return BUDGET_POINTS.HIGH;
  if (budget >= BUDGET_THRESHOLDS_USD.MEDIUM) return BUDGET_POINTS.MEDIUM;
  if (budget >= BUDGET_THRESHOLDS_USD.LOW) return BUDGET_POINTS.LOW;
  return BUDGET_POINTS.MINIMAL;
}

function scoreGap(gap: number): number {
  if (gap <= 1) return GAP_POINTS.NONE_TO_ONE;
  if (gap === 2) return GAP_POINTS.TWO;
  if (gap <= 5) return GAP_POINTS.THREE_TO_FIVE;
  return GAP_POINTS.OVER_FIVE;
}

function scoreCountry(preferredCountry: string): number {
  return preferredCountry === PREFERRED_COUNTRY_ANY || !preferredCountry
    ? COUNTRY_SPECIFICITY_POINTS.ANY
    : COUNTRY_SPECIFICITY_POINTS.SPECIFIC;
}

/** Pure function — no I/O, no LLM call. Deterministic and unit-testable. */
export function scoreLead(profile: StudentProfile): LeadScoreResult {
  const breakdown = {
    gpa: scoreGpa(profile.gpa),
    ielts: scoreIelts(profile.ielts),
    budget: scoreBudget(profile.budget),
    gap: scoreGap(profile.gap),
    countrySpecificity: scoreCountry(profile.preferredCountry),
  };
  const rawScore =
    breakdown.gpa + breakdown.ielts + breakdown.budget + breakdown.gap + breakdown.countrySpecificity;
  const score = Math.round(rawScore * 100) / 100;

  let status: LeadStatus =
    score >= CLASSIFICATION_THRESHOLDS.HOT ? "Hot" : score >= CLASSIFICATION_THRESHOLDS.WARM ? "Warm" : "Cold";

  // Budget-viability override — see MIN_VIABLE_BUDGET_USD doc comment above.
  if (status === "Hot" && profile.budget < MIN_VIABLE_BUDGET_USD) {
    status = "Warm";
  }

  return { score, status, breakdown };
}

/**
 * Reconstructs a StudentProfile from a persisted row, e.g. to personalize a
 * later chat turn or document check against the profile submitted earlier in
 * the same session. Only rows from before academic_background/etc. existed
 * could have nulls here — defaults are a neutral mid-point, not a real guess.
 */
export function studentRowToProfile(row: StudentRow): StudentProfile {
  return {
    gpa: row.gpa,
    ielts: row.ielts,
    budget: row.budget,
    gap: row.gap,
    preferredCountry: row.preferred_country ?? PREFERRED_COUNTRY_ANY,
    academicBackground: (row.academic_background as AcademicBackground | null) ?? "bachelors",
    careerGoals: row.career_goals ?? "",
    migrationIntent: (row.migration_intent as MigrationIntent | null) ?? "undecided",
  };
}
