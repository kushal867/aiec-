"use client";

import { useState, type FormEvent } from "react";
import styles from "./statusChecker.module.css";
import type { StatusLookupResponse } from "./types";

export interface StatusCheckerProps {
  apiUrl: string;
  onError?: (error: Error) => void;
}

/**
 * Standalone, embeddable "portal" component (brief 4.4) — deliberately not
 * coupled to CounsellorPanel/useChat's sessionId, since its whole purpose is
 * letting a student check their status from any device using the reference
 * code they were given after profile analysis, not just the browser they
 * originally submitted from.
 */
export function StatusChecker({ apiUrl, onError }: StatusCheckerProps) {
  const [referenceCode, setReferenceCode] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<StatusLookupResponse | null>(null);
  const [lookedUpCode, setLookedUpCode] = useState("");
  const [notFound, setNotFound] = useState(false);

  const handleCheck = async (e: FormEvent) => {
    e.preventDefault();
    const code = referenceCode.trim();
    if (!code) return;

    setIsLoading(true);
    setNotFound(false);
    setResult(null);

    try {
      const response = await fetch(`${apiUrl}/api/status/${encodeURIComponent(code)}`);
      if (response.status === 404) {
        setNotFound(true);
        return;
      }
      if (!response.ok) {
        throw new Error(`Status lookup failed with status ${response.status}`);
      }
      const data: StatusLookupResponse = await response.json();
      setResult(data);
      setLookedUpCode(code);
    } catch (err) {
      onError?.(err instanceof Error ? err : new Error("Unknown status lookup error"));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={styles.container}>
      <h3 className={styles.title}>Check Application Status</h3>
      <p className={styles.subtitle}>Enter the reference number you received after your profile analysis.</p>

      <form className={styles.form} onSubmit={handleCheck}>
        <input
          className={styles.input}
          value={referenceCode}
          onChange={(e) => setReferenceCode(e.target.value)}
          placeholder="e.g. AIEC-4F82A1XK"
        />
        <button className={styles.button} type="submit" disabled={isLoading || !referenceCode.trim()}>
          {isLoading ? "Checking..." : "Check Status"}
        </button>
      </form>

      {notFound && (
        <div className={styles.notFound}>No application found for that reference code. Double-check it and try again.</div>
      )}

      {result && (
        <div className={styles.result}>
          <div className={styles.resultHeader}>
            <span className={styles.name}>{result.name}</span>
            <span className={styles.statusBadge}>{result.applicationStatus.label}</span>
          </div>

          <p className={styles.description}>{result.applicationStatus.description}</p>

          <div className={styles.nextLabel}>What happens next</div>
          <p className={styles.next}>{result.applicationStatus.whatHappensNext}</p>

          <div className={styles.nextLabel}>Documents</div>
          <div className={styles.docList}>
            {result.documentChecklist.items.map((item) => {
              const state = !item.uploaded ? "missing" : item.status === "valid" ? "valid" : "attention";
              return (
                <div key={item.documentType} className={styles.docLine}>
                  <span>{item.label}</span>
                  <span className={styles.docStatus} data-state={state}>
                    {state === "missing" ? "Missing" : state === "valid" ? "Received" : "Needs another look"}
                  </span>
                </div>
              );
            })}
          </div>

          <div className={styles.updatedAt}>Last updated: {new Date(result.updatedAt).toLocaleDateString()}</div>

          <div className={styles.downloadRow}>
            <a
              href={`${apiUrl}/api/status/${encodeURIComponent(lookedUpCode)}/export?format=pdf`}
              className={styles.downloadButton}
            >
              Download PDF
            </a>
            <a
              href={`${apiUrl}/api/status/${encodeURIComponent(lookedUpCode)}/export?format=docx`}
              className={styles.downloadButton}
            >
              Download Word
            </a>
          </div>
        </div>
      )}
    </div>
  );
}
