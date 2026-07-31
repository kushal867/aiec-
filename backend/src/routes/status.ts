import { Router } from "express";
import rateLimit from "express-rate-limit";
import { getDb, getStudentByReferenceCode } from "../services/db";
import { explainApplicationStatus } from "../services/applicationStatus";
import { buildDocumentChecklist, type DocumentRecord } from "../services/documentChecklist";
import { generateReportPdf, generateReportDocx } from "../services/reportExport";

export const statusRouter = Router();

// Public endpoint gated only by knowing the reference code (like a parcel
// tracking number) — keep it tight since a code is guessable-by-brute-force
// in theory (32^8 space makes that impractical, but rate limiting is cheap
// insurance regardless).
const statusLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 20,
  standardHeaders: true,
  legacyHeaders: false,
});

const exportLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 20,
  standardHeaders: true,
  legacyHeaders: false,
});

function sanitizeFilenamePart(value: string): string {
  return value.replace(/[^a-zA-Z0-9-]+/g, "_").slice(0, 60) || "report";
}

statusRouter.get("/status/:referenceCode", statusLimiter, (req, res) => {
  const student = getStudentByReferenceCode(getDb(), req.params.referenceCode.trim().toUpperCase());
  if (!student) {
    res.status(404).json({ error: "No application found for that reference code" });
    return;
  }

  const documents = student.documents ? (JSON.parse(student.documents) as DocumentRecord[]) : [];

  // Deliberately minimal, student-safe projection — never expose internal
  // CRM fields (Hot/Warm/Cold score, counsellor notes, assigned counsellor,
  // contact info) through a code-only-gated public endpoint.
  res.json({
    referenceCode: student.reference_code,
    name: student.name,
    applicationStatus: explainApplicationStatus(student.application_status),
    documentChecklist: buildDocumentChecklist(documents),
    updatedAt: student.application_status_updated_at ?? student.updated_at,
  });
});

// Unlike the endpoint above, this returns the student's own full profile +
// AI recommendation (name/contact/GPA/etc.) — a deliberate "give me my
// information" action the student takes, not the passive minimal status
// check. Still never includes internal CRM-only fields (Hot/Warm/Cold
// score, counsellor notes, assignment) — see reportExport.ts.
statusRouter.get("/status/:referenceCode/export", exportLimiter, async (req, res) => {
  const format = req.query.format === "docx" ? "docx" : req.query.format === "pdf" ? "pdf" : null;
  if (!format) {
    res.status(400).json({ error: "Query param 'format' must be 'pdf' or 'docx'" });
    return;
  }

  const student = getStudentByReferenceCode(getDb(), req.params.referenceCode.trim().toUpperCase());
  if (!student) {
    res.status(404).json({ error: "No application found for that reference code" });
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
    console.error("[status/export] request failed:", err);
    res.status(500).json({ error: "Failed to generate report. Please try again." });
  }
});
