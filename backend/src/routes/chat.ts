import { Router } from "express";
import rateLimit from "express-rate-limit";
import { z } from "zod";
import { retrieveRelevantChunks } from "../services/retrieval";
import { generateAnswer } from "../services/claude";
import { getDb, getStudentBySessionId } from "../services/db";
import { studentRowToProfile, type StudentProfile } from "../services/leadScoring";
import { config } from "../config";

export const chatRouter = Router();

// Scoped to this route only (not the whole /api prefix) — see server.ts note
// on why app.use("/api", limiter, router) would otherwise leak the limiter
// onto every /api/* request, including unrelated routes.
const chatLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: config.rateLimitMax,
  standardHeaders: true,
  legacyHeaders: false,
});

const chatRequestSchema = z.object({
  messages: z
    .array(
      z.object({
        role: z.enum(["user", "assistant"]),
        content: z.string().min(1).max(4000),
      }),
    )
    .min(1)
    .max(50),
  sessionId: z.string().max(200).optional(),
});

chatRouter.post("/chat", chatLimiter, async (req, res) => {
  const parsed = chatRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request body", details: parsed.error.flatten() });
    return;
  }

  const { messages, sessionId } = parsed.data;

  // The Anthropic Messages API requires the first message to have role
  // "user" — the widget seeds a greeting as an assistant turn (and the
  // profile-analyze recommendation is seeded the same way), so the array we
  // receive can start with "assistant". Trim any leading assistant turns
  // rather than forwarding them verbatim.
  const firstUserIdx = messages.findIndex((m) => m.role === "user");
  const trimmedMessages = firstUserIdx === -1 ? [] : messages.slice(firstUserIdx);

  const latestUserMessage = [...trimmedMessages].reverse().find((m) => m.role === "user");
  if (!latestUserMessage) {
    res.status(400).json({ error: "No user message found in request" });
    return;
  }

  try {
    const student = sessionId ? getStudentBySessionId(getDb(), sessionId) : undefined;
    const profile: StudentProfile | undefined = student ? studentRowToProfile(student) : undefined;

    const retrievedChunks = await retrieveRelevantChunks(latestUserMessage.content);
    const { reply, sources, coursesReferenced, usage } = await generateAnswer(trimmedMessages, retrievedChunks, profile);

    console.log(
      `[chat] session=${sessionId ?? "-"} student_found=${Boolean(student)} input_tokens=${usage.inputTokens} output_tokens=${usage.outputTokens} cache_read=${usage.cacheReadInputTokens}`,
    );

    res.json({ reply, sources, coursesReferenced, sessionId });
  } catch (err) {
    console.error("[chat] request failed:", err);
    res.status(500).json({ error: "Failed to generate a response. Please try again." });
  }
});
