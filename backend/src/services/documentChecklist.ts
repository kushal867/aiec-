import { DOCUMENT_TYPES, type DocumentType } from "./documentVerification";

export interface DocumentRecord {
  documentType: DocumentType;
  filename: string;
  status: "valid" | "issues_found" | "unclear";
  issues: string[];
  extractedSummary: string;
  uploadedAt: string;
}

export interface DocumentChecklistItem {
  documentType: DocumentType;
  label: string;
  uploaded: boolean;
  status: "valid" | "issues_found" | "unclear" | null;
  issues: string[];
  uploadedAt: string | null;
}

export interface DocumentChecklist {
  items: DocumentChecklistItem[];
  /** Document types never uploaded at all. */
  missing: DocumentType[];
  /** Document types uploaded but not yet in "valid" status. */
  needsAttention: DocumentType[];
  /** True only when every required type is uploaded AND valid. */
  complete: boolean;
}

const DOCUMENT_LABELS: Record<DocumentType, string> = {
  citizenship: "Citizenship / ID document",
  marksheet: "Academic transcript / marksheet",
  ielts_certificate: "IELTS certificate",
};

/**
 * Pure aggregation over a student's uploaded-document records (brief 2.4:
 * "identify missing documents", not just per-document validation). If a type
 * was uploaded more than once (e.g. a re-upload after a rejected scan), the
 * most recent upload determines its current status.
 */
export function buildDocumentChecklist(documents: DocumentRecord[]): DocumentChecklist {
  const latestByType = new Map<DocumentType, DocumentRecord>();
  for (const doc of documents) {
    const existing = latestByType.get(doc.documentType);
    if (!existing || doc.uploadedAt > existing.uploadedAt) {
      latestByType.set(doc.documentType, doc);
    }
  }

  const items: DocumentChecklistItem[] = DOCUMENT_TYPES.map((type) => {
    const latest = latestByType.get(type);
    return {
      documentType: type,
      label: DOCUMENT_LABELS[type],
      uploaded: Boolean(latest),
      status: latest?.status ?? null,
      issues: latest?.issues ?? [],
      uploadedAt: latest?.uploadedAt ?? null,
    };
  });

  const missing = items.filter((item) => !item.uploaded).map((item) => item.documentType);
  const needsAttention = items
    .filter((item) => item.uploaded && item.status !== "valid")
    .map((item) => item.documentType);

  return {
    items,
    missing,
    needsAttention,
    complete: missing.length === 0 && needsAttention.length === 0,
  };
}
