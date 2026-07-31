import { Router } from "express";
import rateLimit from "express-rate-limit";
import { z } from "zod";
import { generateStructuredProfileReport } from "../services/claude";
import { generateStudyPath } from "../services/studyPathEngine";
import { getDb, upsertStudent, suggestCounsellor, getStudentBySessionId, saveStudyPath } from "../services/db";
import { matchCourses } from "../services/courseMatcher";
import { generateReportPdf, generateReportDocx } from "../services/reportExport";
import {
  scoreLead,
  PREFERRED_COUNTRY_ANY,
  ACADEMIC_BACKGROUNDS,
  MIGRATION_INTENTS,
  studentRowToProfile,
  type AcademicBackground,
  type MigrationIntent,
  type StudentProfile,
} from "../services/leadScoring";
import { config } from "../config";

export const profileRouter = Router();

// Scoped to this route only — see chat.ts's chatLimiter comment for why.
const profileLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: config.profileRateLimitMax,
  standardHeaders: true,
  legacyHeaders: false,
});

// Read-only, no Claude call — document generation is local CPU work, so this
// can be looser than profileLimiter (which gates a paid Claude call).
const exportLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 20,
  standardHeaders: true,
  legacyHeaders: false,
});

// Gates a paid Claude call, same reasoning as profileLimiter — generated
// on-demand (student clicks a button), never automatically, and cached in
// the DB so re-viewing it doesn't re-trigger generation.
const studyPathLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: config.profileRateLimitMax,
  standardHeaders: true,
  legacyHeaders: false,
});

function sanitizeFilenamePart(value: string): string {
  return value.replace(/[^a-zA-Z0-9-]+/g, "_").slice(0, 60) || "report";
}

const profileRequestSchema = z.object({
  fullName: z.string().min(1).max(200),
  email: z.string().email().max(200).optional().or(z.literal("")),
  phone: z.string().max(30).optional().or(z.literal("")),
  gpa: z.number().min(0).max(4.0),
  ielts: z.number().min(0).max(9.0),
  budget: z.number().positive().max(1_000_000),
  gap: z.number().int().min(0).max(50),
  academicBackground: z.enum(ACADEMIC_BACKGROUNDS as [AcademicBackground, ...AcademicBackground[]]),
  careerGoals: z.string().max(1000).default(""),
  migrationIntent: z.enum(MIGRATION_INTENTS as [MigrationIntent, ...MigrationIntent[]]),
  preferredCountry: z.string().min(1).max(100).default(PREFERRED_COUNTRY_ANY),
  sessionId: z.string().min(1).max(200),
});

profileRouter.post("/profile/analyze", profileLimiter, async (req, res) => {
  const parsed = profileRequestSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid profile", details: parsed.error.flatten() });
    return;
  }

  const { fullName, email, phone, sessionId, ...profileInput } = parsed.data;
  const profile: StudentProfile = profileInput;

  try {
    const { score, status } = scoreLead(profile);
    const matches = matchCourses(profile);
    const alternativesAllowed = profile.preferredCountry === PREFERRED_COUNTRY_ANY || matches.primary.length === 0;

    const report = await generateStructuredProfileReport(profile, matches, alternativesAllowed);
    const db = getDb();
    // Suggestion only — a human (admin/counsellor) still has to confirm the
    // assignment via POST /api/admin/students/:id/assign. See 2.2 "AI Lead
    // Qualification" (counsellor assignment) in the brief.
    const suggested = suggestCounsellor(db);

    const savedStudent = upsertStudent(db, {
      sessionId,
      name: fullName,
      email: email || null,
      phone: phone || null,
      gpa: profile.gpa,
      ielts: profile.ielts,
      budget: profile.budget,
      gap: profile.gap,
      academicBackground: profile.academicBackground,
      careerGoals: profile.careerGoals || null,
      migrationIntent: profile.migrationIntent,
      preferredCountry: profile.preferredCountry,
      score,
      status,
      countries: report.recommendedCountries.join(", "),
      aiResponse: report.summary,
      nextSteps: JSON.stringify(report.nextSteps),
      suggestedCounsellorId: suggested?.id ?? null,
    });

    console.log(
      `[profile] session=${sessionId} status=${status} score=${score} input_tokens=${report.usage.inputTokens} output_tokens=${report.usage.outputTokens}`,
    );

    res.json({
      reply: report.summary,
      status,
      score,
      recommendedCountries: report.recommendedCountries,
      nextSteps: report.nextSteps,
      suggestedCounsellor: suggested ? { id: suggested.id, name: suggested.name } : null,
      referenceCode: savedStudent.reference_code,
      sessionId,
    });
  } catch (err) {
    console.error("[profile/analyze] request failed:", err);
    res.status(500).json({ error: "Failed to analyze profile. Please try again." });
  }
});

profileRouter.get("/profile/:sessionId/export", exportLimiter, async (req, res) => {
  const format = req.query.format === "docx" ? "docx" : req.query.format === "pdf" ? "pdf" : null;
  if (!format) {
    res.status(400).json({ error: "Query param 'format' must be 'pdf' or 'docx'" });
    return;
  }

  const student = getStudentBySessionId(getDb(), req.params.sessionId);
  if (!student) {
    res.status(404).json({ error: "No profile found for that session" });
    return;
  }

  const filename = `AIEC-Report-${sanitizeFilenamePart(student.name)}.${format}`;

  try {
    if (format === "pdf") {
      const buffer = await generateReportPdf(student);
      res.setHeader("Content-Type", "application/pdf");
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
      res.send(buffer);
    } else {
      const buffer = await generateReportDocx(student);
      res.setHeader("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
      res.setHeader("Content-Disposition", `attachment; filename="${filename}"`);
      res.send(buffer);
    }
  } catch (err) {
    console.error("[profile/export] request failed:", err);
    res.status(500).json({ error: "Failed to generate report. Please try again." });
  }
});

// Phase 3 "Personalized study path engine" — a multi-stage roadmap beyond
// the single-recommendation profile report. On-demand only (see
// studyPathLimiter comment) and cached on the student row.
profileRouter.post("/profile/:sessionId/study-path", studyPathLimiter, async (req, res) => {
  const db = getDb();
  const student = getStudentBySessionId(db, req.params.sessionId);
  if (!student) {
    res.status(404).json({ error: "No profile found for that session" });
    return;
  }

  try {
    const profile = studentRowToProfile(student);
    const matches = matchCourses(profile);
    const studyPath = await generateStudyPath(profile, matches);
    saveStudyPath(db, student.id, JSON.stringify(studyPath.stages));

    console.log(
      `[profile] session=${req.params.sessionId} study-path input_tokens=${studyPath.usage.inputTokens} output_tokens=${studyPath.usage.outputTokens}`,
    );

    res.json({ stages: studyPath.stages, sessionId: req.params.sessionId });
  } catch (err) {
    console.error("[profile/study-path] request failed:", err);
    res.status(500).json({ error: "Failed to generate study path. Please try again." });
  }
});
