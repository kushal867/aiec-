import Anthropic from "@anthropic-ai/sdk";
import { config } from "../config";
import type { StudentProfile } from "./leadScoring";

const client = new Anthropic({ apiKey: config.anthropicApiKey });

export type DocumentType = "citizenship" | "marksheet" | "ielts_certificate" | "pte_certificate";

export const DOCUMENT_TYPES: DocumentType[] = ["citizenship", "marksheet", "ielts_certificate", "pte_certificate"];

export interface DocumentVerificationResult {
  documentType: DocumentType;
  status: "valid" | "issues_found" | "unclear";
  issues: string[];
  extractedSummary: string;
  message: string;
  uploadedAt: string;
}

const BASE_INSTRUCTIONS = `You are AIEC Global's document verification assistant. A student has uploaded a document as part of their study-abroad application. Your job is to check it BEFORE a human counsellor reviews it, so obvious problems (blurry, wrong document, missing info, mismatched data) get caught immediately.

Be specific and factual about what you can actually see in the image — do not invent details you cannot read. If the image is unreadable, cropped, clearly not the requested document type, or looks like a photo of a screen/unrelated image, say so plainly rather than guessing at content.`;

function buildDocumentSpecificInstructions(documentType: DocumentType, profile?: StudentProfile): string {
  switch (documentType) {
    case "citizenship":
      return `This should be a government-issued citizenship certificate, national ID, or passport. Check:
- Is it legible (not blurry, not cut off)?
- Does it show a full name, date of birth, and an issuing authority/government?
- Any signs it's not a genuine ID document (e.g. a screenshot, an unrelated photo, an obviously edited image)?`;
    case "marksheet": {
      const gpaLine = profile
        ? `\nThe student self-reported a GPA of ${profile.gpa}/4.0 — if a GPA or percentage is visible on the marksheet, check whether it's broadly consistent with that. Flag a clear mismatch, but don't fail the document just because an exact GPA isn't printed in the same scale.`
        : "";
      return `This should be an academic transcript/marksheet. Check:
- Is it legible?
- Does it show the institution name, student name, subjects/grades, and completion status?${gpaLine}`;
    }
    case "ielts_certificate": {
      const ieltsLine = profile
        ? `\nThe student self-reported an IELTS score of ${profile.ielts}/9.0 — check whether the Overall band score on the certificate matches or closely aligns. Flag clearly if there's a mismatch.`
        : "";
      return `This should be an IELTS Test Report Form (TRF). Check:
- Is it legible?
- Does it show the test taker's name, test date, and band scores (Listening/Reading/Writing/Speaking/Overall)?
- Is the test date within the last 2 years? (IELTS scores are typically considered valid for 2 years — flag if it looks older.)${ieltsLine}`;
    }
    case "pte_certificate": {
      const pteLine = profile
        ? `\nThe student self-reported a PTE score — check whether the Overall score on the certificate is broadly consistent with what they reported. Flag clearly if there's a mismatch.`
        : "";
      return `This should be a PTE Academic score report. Check:
- Is it legible?
- Does it show the test taker's name, test date, and scores (Listening/Reading/Speaking/Writing/Overall, scored out of 90 — not IELTS's 0-9 band scale)?
- Is the test date within the last 2 years? (PTE scores are typically considered valid for 2 years — flag if it looks older.)${pteLine}`;
    }
  }
}

const VERIFICATION_SCHEMA = {
  type: "object",
  properties: {
    status: { type: "string", enum: ["valid", "issues_found", "unclear"] },
    issues: {
      type: "array",
      items: { type: "string" },
      description: "Specific, concrete problems found. Empty array if status is valid.",
    },
    extractedSummary: {
      type: "string",
      description: "Brief factual summary of what's visible in the document (name, dates, scores, etc. — only what you can actually read).",
    },
    message: {
      type: "string",
      description: "A short, plain-language, student-facing message explaining the result and what to do next if there's a problem.",
    },
  },
  required: ["status", "issues", "extractedSummary", "message"],
  additionalProperties: false,
} as const;

export async function verifyDocument(
  documentType: DocumentType,
  fileBuffer: Buffer,
  mimeType: string,
  profile?: StudentProfile,
): Promise<Omit<DocumentVerificationResult, "documentType" | "uploadedAt">> {
  const base64 = fileBuffer.toString("base64");
  const isPdf = mimeType === "application/pdf";

  const documentContentBlock: Anthropic.Base64PDFSource | Anthropic.Base64ImageSource = isPdf
    ? { type: "base64", media_type: "application/pdf", data: base64 }
    : { type: "base64", media_type: mimeType as "image/jpeg" | "image/png" | "image/webp" | "image/gif", data: base64 };

  const response = await client.messages.create({
    model: config.claudeModel,
    max_tokens: 1024,
    thinking: { type: "adaptive" },
    output_config: {
      effort: "low",
      format: { type: "json_schema", schema: VERIFICATION_SCHEMA },
    },
    system: [{ type: "text", text: `${BASE_INSTRUCTIONS}\n\n${buildDocumentSpecificInstructions(documentType, profile)}` }],
    messages: [
      {
        role: "user",
        content: [
          isPdf
            ? { type: "document", source: documentContentBlock as Anthropic.Base64PDFSource }
            : { type: "image", source: documentContentBlock as Anthropic.Base64ImageSource },
          { type: "text", text: "Please review this document." },
        ],
      },
    ],
  });

  const textBlock = response.content.find((block) => block.type === "text");
  const raw = textBlock && textBlock.type === "text" ? textBlock.text : "{}";
  const parsed = JSON.parse(raw) as { status: string; issues: string[]; extractedSummary: string; message: string };

  return {
    status: parsed.status as "valid" | "issues_found" | "unclear",
    issues: parsed.issues,
    extractedSummary: parsed.extractedSummary,
    message: parsed.message,
  };
}
