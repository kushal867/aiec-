import { Router } from "express";
import multer from "multer";
import rateLimit from "express-rate-limit";
import fs from "node:fs";
import path from "node:path";
import { z } from "zod";
import { verifyDocument, DOCUMENT_TYPES, type DocumentType } from "../services/documentVerification";
import { buildDocumentChecklist, type DocumentRecord } from "../services/documentChecklist";
import { getDb, getStudentBySessionId, appendDocumentRecord } from "../services/db";
import { studentRowToProfile, type StudentProfile } from "../services/leadScoring";
import { config } from "../config";

export const documentsRouter = Router();

// Vision calls are more expensive than a text chat turn — keep this tight.
const documentsLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: config.documentRateLimitMax,
  standardHeaders: true,
  legacyHeaders: false,
});

// Read-only, no Claude call — lighter than documentsLimiter, but still
// scoped to its own route (never the shared /api prefix) per convention.
const checklistLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 30,
  standardHeaders: true,
  legacyHeaders: false,
});

function parseDocumentRecords(documentsJson: string | null): DocumentRecord[] {
  if (!documentsJson) return [];
  return JSON.parse(documentsJson) as DocumentRecord[];
}

const ALLOWED_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/webp", "application/pdf"]);
const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10MB

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_FILE_BYTES },
  fileFilter: (_req, file, cb) => {
    if (!ALLOWED_MIME_TYPES.has(file.mimetype)) {
      cb(new Error(`Unsupported file type: ${file.mimetype}. Allowed: JPEG, PNG, WEBP, PDF.`));
      return;
    }
    cb(null, true);
  },
});

const uploadFieldsSchema = z.object({
  documentType: z.enum(DOCUMENT_TYPES as [DocumentType, ...DocumentType[]]),
  sessionId: z.string().min(1).max(200),
});

// SessionId is client-generated (crypto.randomUUID()) — never trust it
// directly in a filesystem path. Strip to a safe charset before using it as
// a directory name.
function sanitizeForPath(value: string): string {
  return value.replace(/[^a-zA-Z0-9-]/g, "").slice(0, 100) || "unknown-session";
}

function extensionFor(mimeType: string): string {
  switch (mimeType) {
    case "image/jpeg":
      return "jpg";
    case "image/png":
      return "png";
    case "image/webp":
      return "webp";
    case "application/pdf":
      return "pdf";
    default:
      return "bin";
  }
}

documentsRouter.post("/documents/upload", documentsLimiter, upload.single("file"), async (req, res) => {
  if (!req.file) {
    res.status(400).json({ error: "No file uploaded (expected multipart field 'file')" });
    return;
  }

  const parsed = uploadFieldsSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Invalid request fields", details: parsed.error.flatten() });
    return;
  }
  const { documentType, sessionId } = parsed.data;

  try {
    const student = getStudentBySessionId(getDb(), sessionId);
    const profile: StudentProfile | undefined = student ? studentRowToProfile(student) : undefined;

    const result = await verifyDocument(documentType, req.file.buffer, req.file.mimetype, profile);

    const safeSessionDir = sanitizeForPath(sessionId);
    const uploadDir = path.join(config.uploadsDir, safeSessionDir);
    fs.mkdirSync(uploadDir, { recursive: true });
    const filename = `${documentType}-${Date.now()}.${extensionFor(req.file.mimetype)}`;
    fs.writeFileSync(path.join(uploadDir, filename), req.file.buffer);

    const record = {
      documentType,
      filename,
      status: result.status,
      issues: result.issues,
      extractedSummary: result.extractedSummary,
      uploadedAt: new Date().toISOString(),
    };
    const updated = appendDocumentRecord(getDb(), sessionId, record);
    const checklist = buildDocumentChecklist(parseDocumentRecords(updated?.documents ?? null));

    console.log(`[documents] session=${sessionId} type=${documentType} status=${result.status}`);

    res.json({ documentType, ...result, sessionId, checklist });
  } catch (err) {
    console.error("[documents/upload] request failed:", err);
    res.status(500).json({ error: "Failed to verify document. Please try again." });
  }
});

documentsRouter.get("/documents/checklist/:sessionId", checklistLimiter, (req, res) => {
  const sessionId = req.params.sessionId;
  const student = getStudentBySessionId(getDb(), sessionId);
  if (!student) {
    // Not an error — a student who hasn't submitted their profile yet simply
    // has all documents outstanding.
    res.json({ sessionId, checklist: buildDocumentChecklist([]) });
    return;
  }
  const checklist = buildDocumentChecklist(parseDocumentRecords(student.documents));
  res.json({ sessionId, checklist });
});
