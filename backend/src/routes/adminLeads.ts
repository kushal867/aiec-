import { Router } from "express";
import cors from "cors";
import { z } from "zod";
import {
  getDb,
  listStudents,
  updateCounsellorNotes,
  listCounsellors,
  updateApplicationStatus,
  markContacted,
  saveFollowupSuggestion,
  getStudentById,
  getUserById,
  assignCounsellor,
  APPLICATION_STATUSES,
  type ApplicationStatus,
} from "../services/db";
import { buildDocumentChecklist, type DocumentRecord } from "../services/documentChecklist";
import { explainApplicationStatus } from "../services/applicationStatus";
import { checkInactivity, generateFollowupSuggestion } from "../services/crmAssistant";
import { predictConversion } from "../services/conversionPrediction";
import { config } from "../config";
import { requireAuth } from "../middleware/auth";

export const adminLeadsRouter = Router();

// CORS and auth are attached directly to these specific routes (not via the
// shared app.use("/api", ...) chain in server.ts) so they can never leak
// onto or be bypassed by unrelated /api/* requests, and so requireAuth here
// can't accidentally start blocking public chat/profile traffic — see
// middleware/auth.ts.
const adminCors = cors({ origin: config.adminAllowedOrigin });

// Every route below sends a non-simple request (custom `Authorization`
// header, or a JSON body on POST/PATCH), so the browser preflights ALL of
// them with OPTIONS first. `router.get/post/patch(path, adminCors, ...)`
// only matches its own method — without an explicit OPTIONS handler on the
// same path, every preflight 404s with no CORS headers and the real request
// never fires client-side ("Failed to fetch", nothing in the server log).
// One wildcard covers every path under this router without broadening the
// CORS policy itself — adminCors is still the same restrictive origin.
adminLeadsRouter.options("*", adminCors);

function serializeStudent(row: ReturnType<typeof listStudents>[number]) {
  const documents = row.documents ? (JSON.parse(row.documents) as DocumentRecord[]) : [];
  return {
    id: row.id,
    sessionId: row.session_id,
    referenceCode: row.reference_code,
    name: row.name,
    email: row.email,
    phone: row.phone,
    gpa: row.gpa,
    ielts: row.ielts,
    budget: row.budget,
    gap: row.gap,
    academicBackground: row.academic_background,
    careerGoals: row.career_goals,
    migrationIntent: row.migration_intent,
    preferredCountry: row.preferred_country,
    score: row.score,
    status: row.status,
    countries: row.countries,
    aiResponse: row.ai_response,
    nextSteps: row.next_steps ? (JSON.parse(row.next_steps) as string[]) : [],
    documents,
    documentChecklist: buildDocumentChecklist(documents),
    counsellorNotes: row.counsellor_notes,
    applicationStatus: explainApplicationStatus(row.application_status),
    applicationStatusUpdatedAt: row.application_status_updated_at,
    assignedCounsellorId: row.assigned_counsellor_id,
    suggestedCounsellorId: row.suggested_counsellor_id,
    lastContactedAt: row.last_contacted_at,
    followupSuggestion: row.followup_suggestion,
    followupAction: row.followup_action,
    followupTiming: row.followup_timing,
    followupGeneratedAt: row.followup_generated_at,
    inactivity: checkInactivity(row),
    conversionPrediction: predictConversion(row),
    studyPath: row.study_path ? (JSON.parse(row.study_path) as { title: string; description: string; estimatedTimeframe: string }[]) : null,
    studyPathGeneratedAt: row.study_path_generated_at,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

// Admins see every lead; counsellors only see leads assigned to them — the
// 4.3 "role-based behavior" requirement from the brief.
adminLeadsRouter.get("/admin/leads", adminCors, requireAuth, (req, res) => {
  const status = typeof req.query.status === "string" ? req.query.status : undefined;
  const sort = req.query.sort === "asc" ? "asc" : "desc";
  const counsellorId = req.user!.role === "counsellor" ? req.user!.userId : undefined;

  const rows = listStudents(getDb(), { status, sort, counsellorId });
  let serialized = rows.map(serializeStudent);
  // Inactivity is time-relative ("now"), so it can't be a SQL WHERE clause —
  // filtered in JS after the (small, single-tenant) result set is fetched.
  if (req.query.inactiveOnly === "true") {
    serialized = serialized.filter((s) => s.inactivity.isInactive);
  }
  res.json({ leads: serialized });
});

adminLeadsRouter.get("/admin/counsellors", adminCors, requireAuth, (_req, res) => {
  const rows = listCounsellors(getDb());
  res.json({ counsellors: rows.map((c) => ({ id: c.id, name: c.name, email: c.email })) });
});

const notesSchema = z.object({ notes: z.string().max(5000) });

adminLeadsRouter.patch("/admin/leads/:id/notes", adminCors, requireAuth, (req, res) => {
  const parsed = notesSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request body", details: parsed.error.flatten() });
    return;
  }
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: "Invalid id" });
    return;
  }
  const updated = updateCounsellorNotes(getDb(), id, parsed.data.notes);
  if (!updated) {
    res.status(404).json({ error: "Lead not found" });
    return;
  }
  res.json({ lead: serializeStudent(updated) });
});

const statusSchema = z.object({
  applicationStatus: z.enum(APPLICATION_STATUSES as [ApplicationStatus, ...ApplicationStatus[]]),
});

adminLeadsRouter.patch("/admin/leads/:id/status", adminCors, requireAuth, (req, res) => {
  const parsed = statusSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request body", details: parsed.error.flatten() });
    return;
  }
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: "Invalid id" });
    return;
  }
  const updated = updateApplicationStatus(getDb(), id, parsed.data.applicationStatus);
  if (!updated) {
    res.status(404).json({ error: "Lead not found" });
    return;
  }
  res.json({ lead: serializeStudent(updated) });
});

const assignSchema = z.object({ counsellorId: z.number().int().positive() });

// Admins may assign any lead to any counsellor. Counsellors may only claim a
// lead for themselves (self-assign) — they can't reassign to a colleague or
// take a lead someone else already owns. This is the 2.2 "counsellor
// assignment" requirement, gated by the 4.3 role-based behavior rule.
adminLeadsRouter.post("/admin/leads/:id/assign", adminCors, requireAuth, (req, res) => {
  const parsed = assignSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request body", details: parsed.error.flatten() });
    return;
  }
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: "Invalid id" });
    return;
  }
  const { counsellorId } = parsed.data;
  const db = getDb();

  if (req.user!.role === "counsellor") {
    if (counsellorId !== req.user!.userId) {
      res.status(403).json({ error: "Counsellors may only claim a lead for themselves" });
      return;
    }
    const existing = getStudentById(db, id);
    if (existing?.assigned_counsellor_id && existing.assigned_counsellor_id !== req.user!.userId) {
      res.status(403).json({ error: "This lead is already assigned to another counsellor" });
      return;
    }
  } else {
    const target = getUserById(db, counsellorId);
    if (!target || target.role !== "counsellor") {
      res.status(400).json({ error: "counsellorId does not refer to a counsellor account" });
      return;
    }
  }

  const updated = assignCounsellor(db, id, counsellorId);
  if (!updated) {
    res.status(404).json({ error: "Lead not found" });
    return;
  }
  res.json({ lead: serializeStudent(updated) });
});

adminLeadsRouter.post("/admin/leads/:id/contacted", adminCors, requireAuth, (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: "Invalid id" });
    return;
  }
  const updated = markContacted(getDb(), id);
  if (!updated) {
    res.status(404).json({ error: "Lead not found" });
    return;
  }
  res.json({ lead: serializeStudent(updated) });
});

// On-demand — never auto-generated in bulk (Claude call, see crmAssistant.ts).
adminLeadsRouter.post("/admin/leads/:id/followup", adminCors, requireAuth, async (req, res) => {
  const id = Number(req.params.id);
  if (!Number.isInteger(id)) {
    res.status(400).json({ error: "Invalid id" });
    return;
  }
  const db = getDb();
  const student = getStudentById(db, id);
  if (!student) {
    res.status(404).json({ error: "Lead not found" });
    return;
  }
  try {
    const inactivity = checkInactivity(student);
    const suggestion = await generateFollowupSuggestion(student, inactivity);
    const updated = saveFollowupSuggestion(db, id, {
      suggestion: suggestion.messageTemplate,
      action: suggestion.suggestedAction,
      timing: suggestion.timing,
    });
    res.json({ lead: updated ? serializeStudent(updated) : undefined });
  } catch (err) {
    console.error("[admin/leads/followup] request failed:", err);
    res.status(500).json({ error: "Failed to generate follow-up suggestion. Please try again." });
  }
});
