import { useEffect, useState } from "react";
import styles from "./documentUpload.module.css";
import type {
  DocumentChecklist,
  DocumentChecklistResponse,
  DocumentType,
  DocumentVerificationResponse,
} from "./types";

export interface DocumentUploadProps {
  apiUrl: string;
  sessionId: string;
  onError?: (error: Error) => void;
}

const DOCUMENT_SLOTS: { type: DocumentType; label: string; hint: string }[] = [
  { type: "citizenship", label: "Citizenship / ID / Passport", hint: "Government-issued ID document" },
  { type: "marksheet", label: "Academic Marksheet", hint: "Transcript showing your grades" },
  { type: "ielts_certificate", label: "IELTS Certificate", hint: "Test Report Form (TRF)" },
];

const STATUS_LABELS: Record<DocumentVerificationResponse["status"], { label: string; color: string }> = {
  valid: { label: "Looks good", color: "#1a7d3a" },
  issues_found: { label: "Issues found", color: "#c0392b" },
  unclear: { label: "Couldn't verify", color: "#b7791f" },
};

function DocumentSlot({ apiUrl, sessionId, type, label, hint, onError, onChecklistUpdate }: {
  apiUrl: string;
  sessionId: string;
  type: DocumentType;
  label: string;
  hint: string;
  onError?: (error: Error) => void;
  onChecklistUpdate: (checklist: DocumentChecklist) => void;
}) {
  const [isUploading, setIsUploading] = useState(false);
  const [result, setResult] = useState<DocumentVerificationResponse | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setIsUploading(true);
    setResult(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("documentType", type);
      formData.append("sessionId", sessionId);

      const response = await fetch(`${apiUrl}/api/documents/upload`, { method: "POST", body: formData });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error ?? `Upload failed with status ${response.status}`);
      }
      const data: DocumentVerificationResponse = await response.json();
      setResult(data);
      onChecklistUpdate(data.checklist);
    } catch (err) {
      onError?.(err instanceof Error ? err : new Error("Unknown document upload error"));
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  return (
    <div className={styles.slot}>
      <div className={styles.slotHeader}>
        <span className={styles.slotLabel}>{label}</span>
        <span className={styles.slotHint}>{hint}</span>
      </div>
      <label className={styles.fileButton}>
        {isUploading ? "Checking..." : fileName ? "Replace file" : "Choose file"}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp,application/pdf"
          onChange={handleFileChange}
          disabled={isUploading}
          className={styles.fileInput}
        />
      </label>
      {fileName && <span className={styles.fileName}>{fileName}</span>}

      {result && (
        <div className={styles.result}>
          <span className={styles.statusBadge} style={{ color: STATUS_LABELS[result.status].color }}>
            ● {STATUS_LABELS[result.status].label}
          </span>
          <p className={styles.message}>{result.message}</p>
          {result.issues.length > 0 && (
            <ul className={styles.issues}>
              {result.issues.map((issue, i) => (
                <li key={i}>{issue}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export function DocumentUpload({ apiUrl, sessionId, onError }: DocumentUploadProps) {
  const [checklist, setChecklist] = useState<DocumentChecklist | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiUrl}/api/documents/checklist/${sessionId}`)
      .then((res) => (res.ok ? (res.json() as Promise<DocumentChecklistResponse>) : Promise.reject(new Error(`Checklist request failed with status ${res.status}`))))
      .then((data) => {
        if (!cancelled) setChecklist(data.checklist);
      })
      .catch((err) => {
        if (!cancelled) onError?.(err instanceof Error ? err : new Error("Unknown checklist error"));
      });
    return () => {
      cancelled = true;
    };
  }, [apiUrl, sessionId, onError]);

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>Document Check</h3>
      <p className={styles.subtitle}>
        Upload your documents and Claude will check them for obvious issues before a counsellor reviews them.
      </p>
      {checklist && !checklist.complete && (
        <div className={styles.checklistSummary}>
          {checklist.missing.length > 0 && (
            <div>Still needed: {checklist.missing.map((t) => DOCUMENT_SLOTS.find((s) => s.type === t)?.label ?? t).join(", ")}</div>
          )}
          {checklist.needsAttention.length > 0 && (
            <div>
              Needs another look: {checklist.needsAttention.map((t) => DOCUMENT_SLOTS.find((s) => s.type === t)?.label ?? t).join(", ")}
            </div>
          )}
        </div>
      )}
      {checklist?.complete && <div className={styles.checklistComplete}>✓ All required documents received and look valid.</div>}
      {DOCUMENT_SLOTS.map((slot) => (
        <DocumentSlot key={slot.type} apiUrl={apiUrl} sessionId={sessionId} onError={onError} onChecklistUpdate={setChecklist} {...slot} />
      ))}
    </div>
  );
}
