import Anthropic from "@anthropic-ai/sdk";
import { config } from "../config";
import { getDb, queryCourses, type CourseRow } from "./db";
import { PRIORITY_COUNTRIES, type AcademicBackground, type StudentProfile } from "./leadScoring";
import { formatCoursesForPrompt, type CourseMatchResult } from "./courseMatcher";

const client = new Anthropic({ apiKey: config.anthropicApiKey });

export interface StudyPathStage {
  title: string;
  description: string;
  estimatedTimeframe: string;
}

export interface StudyPath {
  stages: StudyPathStage[];
  usage: { inputTokens: number; outputTokens: number; cacheReadInputTokens: number };
}

// What a student could realistically move into AFTER their stage-1 eligible
// level, using only course levels that actually exist in the data (see
// courseMatcher.ts's ELIGIBLE_LEVELS_BY_BACKGROUND for stage 1). Bachelors/
// masters/phd already sit at the top of what this dataset offers
// (Postgraduate/PG Diploma) — there is no further formal level to point to,
// so their "stage 2" is deliberately narrative (career/migration pathway),
// not a fabricated course recommendation.
const STAGE_TWO_LEVELS_BY_BACKGROUND: Partial<Record<AcademicBackground, string[]>> = {
  high_school: ["Postgraduate", "PG Diploma"],
};

const STUDY_PATH_SCHEMA = {
  type: "object",
  properties: {
    stages: {
      type: "array",
      items: {
        type: "object",
        properties: {
          title: {
            type: "string",
            description: "Short stage name — a specific course/university/country from the data, or (for a non-course stage) the pathway name, e.g. 'Skilled migration pathway'.",
          },
          description: {
            type: "string",
            description: "1-2 sentences: what this stage involves and why it fits this student. No more than 2 sentences.",
          },
          estimatedTimeframe: {
            type: "string",
            description: "Rough duration or timing, e.g. '1-2 years' or 'After graduation'.",
          },
        },
        required: ["title", "description", "estimatedTimeframe"],
        additionalProperties: false,
      },
      description: "2 to 4 sequential stages forming this student's long-term study/career pathway, in chronological order.",
    },
  },
  required: ["stages"],
  additionalProperties: false,
} as const;

const STUDY_PATH_PERSONA = `You are a study-abroad counsellor writing a personalized, multi-stage long-term pathway for a student — not a single course recommendation, but a roadmap: what they study now, what plausibly comes next, and how it connects to their stated career goals and migration intent.

This is read by a student waiting for it to generate — be economical. Each stage description is 1-2 sentences, no more.

Rules:
- Stage 1 MUST be grounded in STAGE 1 COURSE MATCHES — name a real course/university/country from that data, never invent one.
- If STAGE 2 COURSE MATCHES is provided and non-empty, ground stage 2 in that data the same way.
- If there is no STAGE 2 COURSE MATCHES block (or it's empty), do not invent a stage-2 course — instead write a stage describing the transition to work or a migration pathway, framed by the student's migration intent and career goals. Only state specific visa/PR/work-rights facts if they're already visible in the course/country data given; otherwise say plainly that a counsellor can advise on the specific pathway.
- Produce 2 to 4 stages total, in chronological order.
- Do not repeat the same point across stages.`;

export async function generateStudyPath(profile: StudentProfile, matches: CourseMatchResult): Promise<StudyPath> {
  const stage2Levels = STAGE_TWO_LEVELS_BY_BACKGROUND[profile.academicBackground];
  let stage2Courses: CourseRow[] = [];
  if (stage2Levels) {
    const countries = matches.primaryCountries.length > 0 ? matches.primaryCountries : [...PRIORITY_COUNTRIES];
    stage2Courses = queryCourses(getDb(), { countries, courseLevels: stage2Levels, maxIelts: profile.ielts, limit: 5 });
  }

  const profileBlock = [
    "STUDENT PROFILE:",
    `- Academic background: ${profile.academicBackground}`,
    `- Career goals: ${profile.careerGoals || "(not specified)"}`,
    `- Migration intent: ${profile.migrationIntent}`,
    `- IELTS: ${profile.ielts} / 9.0`,
    `- Budget: $${profile.budget} USD/year`,
  ].join("\n");

  const coursesBlock = [
    "STAGE 1 COURSE MATCHES:",
    formatCoursesForPrompt(matches.primary),
    "",
    stage2Courses.length > 0 ? "STAGE 2 COURSE MATCHES:" : "STAGE 2 COURSE MATCHES: (none — no further formal course level available; write stage 2 as a career/migration pathway instead)",
    stage2Courses.length > 0 ? formatCoursesForPrompt(stage2Courses) : "",
  ].join("\n");

  const response = await client.messages.create({
    model: config.claudeModel,
    max_tokens: 700,
    thinking: { type: "disabled" },
    output_config: {
      effort: "low",
      format: { type: "json_schema", schema: STUDY_PATH_SCHEMA },
    },
    system: [
      { type: "text", text: STUDY_PATH_PERSONA, cache_control: { type: "ephemeral" } },
      { type: "text", text: profileBlock },
      { type: "text", text: coursesBlock },
    ],
    messages: [{ role: "user", content: "Build my long-term study and career pathway." }],
  });

  const textBlock = response.content.find((block) => block.type === "text");
  const raw = textBlock && textBlock.type === "text" ? textBlock.text : "{}";
  const parsed = JSON.parse(raw) as { stages: StudyPathStage[] };

  return {
    stages: parsed.stages,
    usage: {
      inputTokens: response.usage.input_tokens,
      outputTokens: response.usage.output_tokens,
      cacheReadInputTokens: response.usage.cache_read_input_tokens ?? 0,
    },
  };
}
