import type { StudentRow, ApplicationStatus } from "./db";
import type { LeadStatus } from "./leadScoring";
import { checkInactivity } from "./crmAssistant";
import { buildDocumentChecklist, type DocumentRecord } from "./documentChecklist";

export type ConversionLikelihood = "Very Likely" | "Likely" | "Possible" | "Unlikely";

export interface ConversionPrediction {
  probability: number; // 0-100, integer
  likelihood: ConversionLikelihood;
  factors: string[];
}

// Rule-based heuristic — deliberately NOT a trained ML model. A genuine
// predictive classifier needs historical outcomes (leads that actually
// enrolled vs. didn't, over enough volume) to learn from, and this is a
// brand-new system with no such history yet. The numbers below are
// documented starting assumptions, not measured conversion rates — same
// "named constants, retune here" philosophy as leadScoring.ts.
//
// Once real outcome data accumulates (roughly 100+ leads that reached a
// terminal state — enrolled or rejected/withdrawn), replace this function
// with an actual trained model (e.g. logistic regression) fit on that
// history. The inputs used here — lead classification, application stage,
// contact recency, document completeness — are exactly the feature set
// such a model would use, so the data pipeline doesn't need to change,
// only the scoring function.
export const BASE_RATE_BY_LEAD_STATUS: Record<LeadStatus, number> = {
  Hot: 55,
  Warm: 28,
  Cold: 8,
};

// Multiplies the base rate — further pipeline progress signals a real,
// increasingly committed applicant, independent of the original Hot/Warm/Cold
// score (which only reflects academic/financial fit, not follow-through).
export const STATUS_STAGE_MULTIPLIER: Record<ApplicationStatus, number> = {
  not_started: 1.0,
  documents_pending: 1.05,
  submitted: 1.3,
  under_review: 1.5,
  offer_received: 2.0,
  visa_processing: 2.3,
  enrolled: 1.0, // unreachable — handled as a terminal case below
  rejected: 1.0, // unreachable — handled as a terminal case below
  deferred: 1.4,
};

export const INACTIVITY_PENALTY_POINTS = 15;
export const DOCUMENT_COMPLETE_BONUS_POINTS = 10;

const MIN_PROBABILITY = 1;
const MAX_PROBABILITY = 99; // never claim certainty short of the terminal states below

function likelihoodBand(probability: number): ConversionLikelihood {
  if (probability >= 70) return "Very Likely";
  if (probability >= 40) return "Likely";
  if (probability >= 15) return "Possible";
  return "Unlikely";
}

/** Pure function — no I/O, no LLM call. Deterministic and unit-testable, same as scoreLead(). */
export function predictConversion(student: StudentRow): ConversionPrediction {
  if (student.application_status === "enrolled") {
    return { probability: 100, likelihood: "Very Likely", factors: ["Already enrolled — outcome realized"] };
  }
  if (student.application_status === "rejected") {
    return { probability: 0, likelihood: "Unlikely", factors: ["Application was not successful"] };
  }

  const factors: string[] = [];
  const base = BASE_RATE_BY_LEAD_STATUS[student.status];
  factors.push(`${student.status} lead classification (base ${base}%)`);

  const stageMultiplier = STATUS_STAGE_MULTIPLIER[student.application_status];
  let probability = base * stageMultiplier;
  if (stageMultiplier > 1) {
    factors.push(`"${student.application_status}" pipeline stage increases likelihood`);
  }

  const inactivity = checkInactivity(student);
  if (inactivity.isInactive) {
    probability -= INACTIVITY_PENALTY_POINTS;
    factors.push(`Overdue for contact (-${INACTIVITY_PENALTY_POINTS} pts)`);
  }

  const documents = student.documents ? (JSON.parse(student.documents) as DocumentRecord[]) : [];
  const checklist = buildDocumentChecklist(documents);
  if (checklist.complete) {
    probability += DOCUMENT_COMPLETE_BONUS_POINTS;
    factors.push(`All required documents complete (+${DOCUMENT_COMPLETE_BONUS_POINTS} pts)`);
  } else if (checklist.missing.length > 0) {
    factors.push(`${checklist.missing.length} document(s) still missing`);
  }

  const clamped = Math.round(Math.min(MAX_PROBABILITY, Math.max(MIN_PROBABILITY, probability)));
  return { probability: clamped, likelihood: likelihoodBand(clamped), factors };
}
