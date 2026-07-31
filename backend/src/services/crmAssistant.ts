import Anthropic from "@anthropic-ai/sdk";
import { config } from "../config";
import type { LeadStatus } from "./leadScoring";
import type { StudentRow } from "./db";
import { explainApplicationStatus } from "./applicationStatus";
import { buildDocumentChecklist, type DocumentRecord } from "./documentChecklist";

const client = new Anthropic({ apiKey: config.anthropicApiKey });

// Named, documented thresholds — same rubric philosophy as leadScoring.ts:
// a Hot lead going quiet is far more time-sensitive than a Cold one.
export const INACTIVITY_THRESHOLD_DAYS: Record<LeadStatus, number> = {
  Hot: 2,
  Warm: 5,
  Cold: 14,
};

const MS_PER_DAY = 1000 * 60 * 60 * 24;

export interface InactivityCheckResult {
  isInactive: boolean;
  daysSinceContact: number | null; // null = never contacted at all
  thresholdDays: number;
}

/**
 * Pure, deterministic — no I/O, no LLM call. A student who has reached the
 * terminal "enrolled" status is never flagged: there's no further pipeline
 * movement to chase.
 */
export function checkInactivity(student: StudentRow, now: Date = new Date()): InactivityCheckResult {
  const thresholdDays = INACTIVITY_THRESHOLD_DAYS[student.status];
  if (student.application_status === "enrolled") {
    return { isInactive: false, daysSinceContact: null, thresholdDays };
  }

  const referenceIso = student.last_contacted_at ?? student.created_at;
  const daysSince = Math.floor((now.getTime() - new Date(referenceIso).getTime()) / MS_PER_DAY);

  return {
    isInactive: daysSince >= thresholdDays,
    daysSinceContact: student.last_contacted_at ? daysSince : null,
    thresholdDays,
  };
}

export interface FollowupSuggestion {
  timing: string;
  suggestedAction: string;
  messageTemplate: string;
}

const FOLLOWUP_SCHEMA = {
  type: "object",
  properties: {
    suggestedAction: {
      type: "string",
      description: "One or two sentences telling the counsellor exactly what to do right now (call, email, chase a document, etc).",
    },
    messageTemplate: {
      type: "string",
      description: "A short, ready-to-send message addressed directly to the student, personalized to their specific situation. Plain text, no subject line.",
    },
  },
  required: ["suggestedAction", "messageTemplate"],
  additionalProperties: false,
} as const;

const FOLLOWUP_PERSONA = `You are an assistant to a study-abroad counsellor at AIEC Global. You are given one student's CRM record and must suggest what the counsellor should do next to re-engage them.

Do not invent facts not present in the STUDENT RECORD below (no fee/policy/visa claims). Be specific to this student — reference their actual situation (status, missing documents, how long it's been) rather than writing something generic that could apply to anyone.`;

/**
 * On-demand only (never auto-run per row on every dashboard load) — an
 * explicit "regenerate suggestion" action, same cost-control reasoning as
 * the rest of this codebase (rule-based where deterministic suffices,
 * Claude only where personalization genuinely adds value).
 */
export async function generateFollowupSuggestion(
  student: StudentRow,
  inactivity: InactivityCheckResult,
): Promise<FollowupSuggestion> {
  const statusInfo = explainApplicationStatus(student.application_status);
  const documents = student.documents ? (JSON.parse(student.documents) as DocumentRecord[]) : [];
  const checklist = buildDocumentChecklist(documents);

  const timing = inactivity.isInactive
    ? `Overdue now — contact within 24 hours (${student.status} leads are expected to be contacted every ${inactivity.thresholdDays} day(s))`
    : `On track — next contact due in ${inactivity.thresholdDays - (inactivity.daysSinceContact ?? 0)} day(s)`;

  const recordBlock = [
    `STUDENT RECORD:`,
    `- Name: ${student.name}`,
    `- Lead classification: ${student.status}`,
    `- Application status: ${statusInfo.label} — ${statusInfo.description}`,
    `- Days since last contact: ${inactivity.daysSinceContact ?? "never contacted"}`,
    `- Preferred country: ${student.preferred_country ?? "not specified"}`,
    `- Career goals: ${student.career_goals || "not specified"}`,
    `- Missing documents: ${checklist.missing.length > 0 ? checklist.missing.join(", ") : "none"}`,
    `- Documents needing attention: ${checklist.needsAttention.length > 0 ? checklist.needsAttention.join(", ") : "none"}`,
    `- Counsellor notes: ${student.counsellor_notes || "(none)"}`,
  ].join("\n");

  const response = await client.messages.create({
    model: config.claudeModel,
    max_tokens: 512,
    thinking: { type: "adaptive" },
    output_config: {
      effort: "low",
      format: { type: "json_schema", schema: FOLLOWUP_SCHEMA },
    },
    system: [
      { type: "text", text: FOLLOWUP_PERSONA, cache_control: { type: "ephemeral" } },
      { type: "text", text: recordBlock },
    ],
    messages: [{ role: "user", content: "Suggest my next action and a message I can send this student." }],
  });

  const textBlock = response.content.find((block) => block.type === "text");
  const raw = textBlock && textBlock.type === "text" ? textBlock.text : "{}";
  const parsed = JSON.parse(raw) as { suggestedAction: string; messageTemplate: string };

  return { timing, suggestedAction: parsed.suggestedAction, messageTemplate: parsed.messageTemplate };
}
