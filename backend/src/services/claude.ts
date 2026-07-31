import Anthropic from "@anthropic-ai/sdk";
import { config } from "../config";
import type { ChatMessage, RetrievedChunk, SourceRef } from "../types";
import {
  PREFERRED_COUNTRY_ANY,
  PRIORITY_COUNTRIES,
  ACADEMIC_BACKGROUND_LABELS,
  MIGRATION_INTENT_LABELS,
  type StudentProfile,
} from "./leadScoring";
import { getDb, queryCourses, type CourseRow } from "./db";
import { formatCoursesForPrompt, type CourseMatchResult } from "./courseMatcher";

const client = new Anthropic({ apiKey: config.anthropicApiKey });

const BASE_PERSONA = `You are the AIEC Global study-abroad counsellor assistant. You answer student questions about visas, fees, intake dates, country comparisons, eligibility, courses, universities, and next steps.

Do not use outside knowledge, prior training data, or assumptions to fill gaps — especially for fees, deadlines, GPA/IELTS thresholds, and visa rules, where being wrong could mislead a student. If you don't have enough grounded information to answer confidently, say so explicitly and suggest the student contact a human counsellor. Do not guess or invent a course, university, or fee that isn't in the data you were given.

If a STUDENT PROFILE block is present, personalize your answer to it (e.g. their preferred country, budget) — but you must still only state facts (fees, deadlines, eligibility) that appear in the grounding data provided to you.`;

const CHAT_PERSONA = `${BASE_PERSONA}

You have a CONTEXT block (institutional policy documents) and a "search_courses" tool (AIEC Global's real database of courses, universities, fees, and IELTS requirements across 16 countries). Use the search_courses tool whenever the student asks about specific courses, universities, fees, or country options — never answer those from general knowledge. Use CONTEXT for visa/policy questions instead.

When you answer using search_courses results, cite the country and course/university. When you answer from CONTEXT, cite the source document and page inline, e.g. "(Canada Study Permit Guide, p.4)".`;

function buildContextBlock(chunks: RetrievedChunk[]): string {
  if (chunks.length === 0) {
    return "CONTEXT:\n(No relevant information was found in the knowledge base for this question.)";
  }
  const rendered = chunks
    .map((chunk) => `[Source: ${chunk.document}, page ${chunk.page}]\n${chunk.text}`)
    .join("\n\n---\n\n");
  return `CONTEXT:\n${rendered}`;
}

function buildProfileBlock(profile?: StudentProfile): string | null {
  if (!profile) return null;
  const country =
    profile.preferredCountry === PREFERRED_COUNTRY_ANY || !profile.preferredCountry
      ? "Open to any country (let the counsellor recommend)"
      : profile.preferredCountry;
  return [
    "STUDENT PROFILE (self-reported by the student; treat as authoritative for personalization, not as a fee/policy source):",
    `- GPA: ${profile.gpa} / 4.0`,
    `- IELTS: ${profile.ielts} / 9.0`,
    `- Annual budget (tuition + living): $${profile.budget} USD`,
    `- Study gap: ${profile.gap} years`,
    `- Academic background: ${ACADEMIC_BACKGROUND_LABELS[profile.academicBackground] ?? profile.academicBackground}`,
    `- Career goals: ${profile.careerGoals || "(not specified)"}`,
    `- Migration intent: ${MIGRATION_INTENT_LABELS[profile.migrationIntent] ?? profile.migrationIntent}`,
    `- Preferred country: ${country}`,
  ].join("\n");
}

export interface GeneratedAnswer {
  reply: string;
  sources: SourceRef[];
  coursesReferenced: { courseName: string; university: string | null; country: string; feePerYear: number | null }[];
  usage: {
    inputTokens: number;
    outputTokens: number;
    cacheReadInputTokens: number;
  };
}

const SEARCH_COURSES_TOOL: Anthropic.Tool = {
  name: "search_courses",
  description:
    "Search AIEC Global's real course database (406 courses across 16 countries: Australia, USA, Canada, New Zealand, UK, Japan, South Korea, Malta, Germany, Netherlands, Finland, Cyprus, Romania, Ireland, Dubai (UAE), Denmark). Use this for ANY question about specific courses, universities, fees, IELTS requirements, or country options — never answer these from general knowledge.",
  input_schema: {
    type: "object",
    properties: {
      countries: {
        type: "array",
        items: { type: "string" },
        description: "Country names to filter by, e.g. [\"Australia\",\"Canada\"]. Omit to search all countries.",
      },
      maxIelts: { type: "number", description: "Only return courses requiring an IELTS score at or below this value." },
      maxFeePerYear: { type: "number", description: "Only return courses with an annual fee at or below this value (USD, approximate)." },
      courseLevel: {
        type: "string",
        description: "e.g. Undergraduate, Postgraduate, Diploma, Certificate, Foundation, Language, PG Diploma",
      },
      keyword: { type: "string", description: "Keyword to search within course names, e.g. \"Computer Science\"" },
    },
  },
};

function executeSearchCourses(input: Record<string, unknown>): CourseRow[] {
  return queryCourses(getDb(), {
    countries: Array.isArray(input.countries) ? (input.countries as string[]) : undefined,
    maxIelts: typeof input.maxIelts === "number" ? input.maxIelts : undefined,
    maxFeePerYear: typeof input.maxFeePerYear === "number" ? input.maxFeePerYear : undefined,
    courseLevel: typeof input.courseLevel === "string" ? input.courseLevel : undefined,
    keyword: typeof input.keyword === "string" ? input.keyword : undefined,
    limit: 15,
  });
}

const MAX_TOOL_ITERATIONS = 3;

/** General chat — supports the search_courses tool for course/fee/university questions. */
export async function generateAnswer(
  history: ChatMessage[],
  retrievedChunks: RetrievedChunk[],
  profile?: StudentProfile,
): Promise<GeneratedAnswer> {
  const profileBlock = buildProfileBlock(profile);
  const system: Anthropic.TextBlockParam[] = [
    { type: "text", text: CHAT_PERSONA, cache_control: { type: "ephemeral" } },
    ...(profileBlock ? [{ type: "text" as const, text: profileBlock }] : []),
    { type: "text", text: buildContextBlock(retrievedChunks) },
  ];

  let messages: Anthropic.MessageParam[] = history.map((m) => ({ role: m.role, content: m.content }));
  let totalInputTokens = 0;
  let totalOutputTokens = 0;
  let totalCacheReadTokens = 0;
  const coursesReferenced: GeneratedAnswer["coursesReferenced"] = [];

  for (let i = 0; i < MAX_TOOL_ITERATIONS; i++) {
    const response = await client.messages.create({
      model: config.claudeModel,
      max_tokens: 1024,
      thinking: { type: "adaptive" },
      output_config: { effort: "low" },
      system,
      messages,
      tools: [SEARCH_COURSES_TOOL],
    });

    totalInputTokens += response.usage.input_tokens;
    totalOutputTokens += response.usage.output_tokens;
    totalCacheReadTokens += response.usage.cache_read_input_tokens ?? 0;

    if (response.stop_reason !== "tool_use") {
      const textBlock = response.content.find((block) => block.type === "text");
      const reply = textBlock && textBlock.type === "text" ? textBlock.text : "";
      const sources: SourceRef[] = Array.from(
        new Map(retrievedChunks.map((c) => [`${c.document}:${c.page}`, { document: c.document, page: c.page }])).values(),
      );
      return {
        reply,
        sources,
        coursesReferenced,
        usage: { inputTokens: totalInputTokens, outputTokens: totalOutputTokens, cacheReadInputTokens: totalCacheReadTokens },
      };
    }

    messages = [...messages, { role: "assistant", content: response.content }];

    const toolResults: Anthropic.ToolResultBlockParam[] = [];
    for (const block of response.content) {
      if (block.type !== "tool_use" || block.name !== "search_courses") continue;
      const results = executeSearchCourses(block.input as Record<string, unknown>);
      results.forEach((c) =>
        coursesReferenced.push({
          courseName: c.course_name,
          university: c.university,
          country: c.country,
          feePerYear: c.fee_per_year,
        }),
      );
      toolResults.push({
        type: "tool_result",
        tool_use_id: block.id,
        content: results.length > 0 ? formatCoursesForPrompt(results) : "No matching courses found.",
      });
    }
    messages = [...messages, { role: "user", content: toolResults }];
  }

  // Safety net: ran out of tool iterations without a final text answer.
  return {
    reply: "I found some relevant course options but need a moment longer than usual — please rephrase your question or ask a human counsellor for help.",
    sources: [],
    coursesReferenced,
    usage: { inputTokens: totalInputTokens, outputTokens: totalOutputTokens, cacheReadInputTokens: totalCacheReadTokens },
  };
}

export interface ProfileReport {
  summary: string;
  recommendedCountries: string[];
  nextSteps: string[];
  usage: {
    inputTokens: number;
    outputTokens: number;
    cacheReadInputTokens: number;
  };
}

const PROFILE_REPORT_SCHEMA = {
  type: "object",
  properties: {
    summary: {
      type: "string",
      description:
        "The narrative report for the student, target 150-220 words: acknowledge their profile in one sentence, present fee margins (min-max) for matched programs, name the matching countries/courses/universities, explain in 1-2 sentences why the primary recommended country/countries fit their budget and profile, and (unless they specified a single preferred country) present other viable countries as additional options in 1-2 sentences. Be economical — one clear sentence per point, not multiple angles on the same point.",
    },
    recommendedCountries: {
      type: "array",
      items: { type: "string" },
      description: "The countries actually recommended in the summary, in priority order.",
    },
    nextSteps: {
      type: "array",
      items: { type: "string" },
      description: "A concise, ordered, step-by-step action plan for the student.",
    },
  },
  required: ["summary", "recommendedCountries", "nextSteps"],
  additionalProperties: false,
} as const;

const PROFILE_REPORT_PERSONA = `${BASE_PERSONA}

You are writing a personalized study-abroad report from a COURSE MATCHES block (real data: course name, level, university if known, country, IELTS requirement, fee per year, fee range, duration, intake). This is your ONLY source for course/fee/university facts — never invent a course, university, or fee not listed there.

This report is read by a student waiting on a page for it to finish generating — length costs them real time. Be economical: one clear sentence per point, never multiple sentences restating the same point from different angles. Every sentence must add new information.

Formatting rules:
- State the fee margin (minimum to maximum) for the matched programs in one sentence, related to the student's stated budget (within budget, or exceeds it by how much).
- Name the specific matching courses/universities/countries from COURSE MATCHES — say "a partner institution" only when the university field is genuinely not listed, never invent a name.
- Courses are listed best-fit-first with a "Fit score" and the reasons behind it — lead with the top-scoring course in each section and you may briefly echo one of its listed reasons, but don't recite every course's score.
- PRIMARY RECOMMENDATION: the countries in "primaryCountries" below are the priority recommendation — explain in 1-2 sentences why they fit this student's profile and budget.
- ALTERNATIVES: if "alternativesAllowed" is true below, briefly (1-2 sentences) present the courses in ALTERNATIVE COURSE MATCHES as other options. If "alternativesAllowed" is false, the student specified a single preferred country — do not suggest other countries unless the primary country genuinely has no viable matches, in which case briefly explain that and offer the alternatives as a fallback.
- In one sentence, use the student's academic background to justify why the matched course LEVELS (e.g. Postgraduate vs Undergraduate) fit — don't just repeat the label back at them.
- In one sentence, connect their career goals to the matched course/field, only when the connection is genuinely plausible — don't force a link that isn't there, and skip this entirely rather than stretch for one.
- In one sentence, note migration intent only where it changes the framing (e.g. "study then work" → post-study work rights if visible in the data; "migrate permanently" → PR-friendly pathway if visible). Skip this sentence entirely if the data doesn't support a specific claim — don't pad with a generic "a counsellor can advise" filler.
- End with a step-by-step next-steps action plan — concise items, not paragraphs.`;

export async function generateStructuredProfileReport(
  profile: StudentProfile,
  matches: CourseMatchResult,
  alternativesAllowed: boolean,
): Promise<ProfileReport> {
  const profileBlock = buildProfileBlock(profile)!;
  const matchesBlock = [
    `primaryCountries: ${JSON.stringify(matches.primaryCountries)}`,
    `alternativesAllowed: ${alternativesAllowed}`,
    "",
    "PRIMARY COURSE MATCHES:",
    formatCoursesForPrompt(matches.primary),
    "",
    "ALTERNATIVE COURSE MATCHES:",
    formatCoursesForPrompt(matches.alternatives),
  ].join("\n");

  const response = await client.messages.create({
    model: config.claudeModel,
    // Generation latency here scales with OUTPUT tokens, not thinking
    // config — measured 1400-1900 output tokens (~20s) regardless of
    // effort/thinking settings, because the persona asked for a long,
    // multi-angle narrative. The actual fix is the shortened persona above
    // (target 150-220 word summary); this cap is a backstop against
    // runaway length, not the primary lever.
    max_tokens: 1024,
    thinking: { type: "disabled" },
    output_config: {
      effort: "low",
      format: { type: "json_schema", schema: PROFILE_REPORT_SCHEMA },
    },
    system: [
      { type: "text", text: PROFILE_REPORT_PERSONA, cache_control: { type: "ephemeral" } },
      { type: "text", text: profileBlock },
      { type: "text", text: matchesBlock },
    ],
    messages: [
      {
        role: "user",
        content: "Please review my profile and recommend suitable study-abroad options, including next steps.",
      },
    ],
  });

  const textBlock = response.content.find((block) => block.type === "text");
  const raw = textBlock && textBlock.type === "text" ? textBlock.text : "{}";
  const parsed = JSON.parse(raw) as { summary: string; recommendedCountries: string[]; nextSteps: string[] };

  return {
    summary: parsed.summary,
    recommendedCountries: parsed.recommendedCountries,
    nextSteps: parsed.nextSteps,
    usage: {
      inputTokens: response.usage.input_tokens,
      outputTokens: response.usage.output_tokens,
      cacheReadInputTokens: response.usage.cache_read_input_tokens ?? 0,
    },
  };
}
