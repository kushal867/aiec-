import { useCallback, useState } from "react";
import { ChatWidget } from "./ChatWidget";
import { ProfileForm } from "./ProfileForm";
import { DocumentUpload } from "./DocumentUpload";
import { useChat } from "./useChat";
import type { LeadStatus, ProfileAnalyzeResponse, ProfileFormValues, StudyPathResponse, StudyPathStage } from "./types";

export interface CounsellorPanelProps {
  apiUrl: string;
  countries?: string[];
  onError?: (error: Error) => void;
}

const PROMPT_MESSAGE = "Please fill in your profile on the left and click Analyse My Profile to begin.";

const STATUS_COLORS: Record<LeadStatus, string> = {
  Hot: "#c0392b",
  Warm: "#b7791f",
  Cold: "#1d4ed8",
};

const downloadButtonStyle: React.CSSProperties = {
  flex: 1,
  textAlign: "center",
  padding: "8px 12px",
  borderRadius: 8,
  border: "1px solid #ccc",
  background: "#fff",
  color: "#1a5f7a",
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
};

export function CounsellorPanel({ apiUrl, countries, onError }: CounsellorPanelProps) {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [analyzed, setAnalyzed] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [result, setResult] = useState<{
    status: LeadStatus;
    score: number;
    nextSteps: string[];
    referenceCode: string;
  } | null>(null);
  const [studyPath, setStudyPath] = useState<StudyPathStage[] | null>(null);
  const [isGeneratingPath, setIsGeneratingPath] = useState(false);
  const [studyPathError, setStudyPathError] = useState<string | null>(null);

  const chat = useChat({ apiUrl, initialMessage: PROMPT_MESSAGE, sessionId, onError });

  const handleGenerateStudyPath = useCallback(async () => {
    setIsGeneratingPath(true);
    setStudyPathError(null);
    try {
      const response = await fetch(`${apiUrl}/api/profile/${sessionId}/study-path`, { method: "POST" });
      if (!response.ok) {
        if (response.status === 429) {
          throw new Error("You've requested this a few times in quick succession — please wait a minute and try again.");
        }
        const body = await response.json().catch(() => ({}) as { error?: string });
        throw new Error(body.error ?? `Something went wrong (status ${response.status}). Please try again.`);
      }
      const data: StudyPathResponse = await response.json();
      setStudyPath(data.stages);
    } catch (err) {
      const error = err instanceof Error ? err : new Error("Unknown study path error");
      setStudyPathError(
        error.message === "Failed to fetch"
          ? "Couldn't reach the server. Please check your connection and try again."
          : error.message,
      );
      onError?.(error);
    } finally {
      setIsGeneratingPath(false);
    }
  }, [apiUrl, sessionId, onError]);

  const handleAnalyze = useCallback(
    async (values: ProfileFormValues) => {
      setIsAnalyzing(true);
      setAnalyzeError(null);
      try {
        const response = await fetch(`${apiUrl}/api/profile/analyze`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...values, sessionId }),
        });
        if (!response.ok) {
          if (response.status === 429) {
            throw new Error("You've submitted a few times in quick succession — please wait a minute and try again.");
          }
          const body = await response.json().catch(() => ({}) as { error?: string });
          throw new Error(body.error ?? `Something went wrong (status ${response.status}). Please try again.`);
        }
        const data: ProfileAnalyzeResponse = await response.json();
        chat.seedAssistantMessage(data.reply);
        setResult({
          status: data.status,
          score: data.score,
          nextSteps: data.nextSteps,
          referenceCode: data.referenceCode,
        });
        setAnalyzed(true);
      } catch (err) {
        const error = err instanceof Error ? err : new Error("Unknown analyze error");
        // Network-level failures (server down, CORS rejection, offline) throw
        // a generic "Failed to fetch" with no other detail — give the
        // student something more actionable than that raw message.
        setAnalyzeError(
          error.message === "Failed to fetch"
            ? "Couldn't reach the server. Please check your connection and try again."
            : error.message,
        );
        onError?.(error);
      } finally {
        setIsAnalyzing(false);
      }
    },
    [apiUrl, sessionId, chat, onError],
  );

  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-start" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <ProfileForm onSubmit={handleAnalyze} isSubmitting={isAnalyzing} disabled={analyzed} countries={countries} />
        {analyzeError && (
          <div
            style={{
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid #f3c2bc",
              background: "#fdecea",
              color: "#c0392b",
              fontSize: 13,
              maxWidth: 420,
            }}
          >
            {analyzeError}
          </div>
        )}
        {result && (
          <div
            style={{
              border: "1px solid #e0e0e0",
              borderRadius: 12,
              padding: 16,
              maxWidth: 420,
              fontFamily: "system-ui, sans-serif",
              fontSize: 14,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span
                style={{
                  display: "inline-block",
                  padding: "2px 10px",
                  borderRadius: 999,
                  fontSize: 12,
                  fontWeight: 600,
                  color: "#fff",
                  background: STATUS_COLORS[result.status],
                }}
              >
                {result.status.toUpperCase()}
              </span>
              <span style={{ color: "#666" }}>Score: {result.score.toFixed(1)} / 10</span>
            </div>
            <strong>Next steps</strong>
            <ol style={{ paddingLeft: 20, margin: "6px 0 0" }}>
              {result.nextSteps.map((step, i) => (
                <li key={i} style={{ marginBottom: 4 }}>
                  {step}
                </li>
              ))}
            </ol>
            <div
              style={{
                marginTop: 12,
                padding: "8px 10px",
                background: "#f7f7f7",
                borderRadius: 8,
                fontSize: 13,
              }}
            >
              Your reference number: <strong>{result.referenceCode}</strong>
              <div style={{ color: "#777", fontSize: 12, marginTop: 2 }}>
                Save this — you can use it to check your application status anytime.
              </div>
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
              <a
                href={`${apiUrl}/api/profile/${sessionId}/export?format=pdf`}
                style={downloadButtonStyle}
              >
                Download PDF
              </a>
              <a
                href={`${apiUrl}/api/profile/${sessionId}/export?format=docx`}
                style={downloadButtonStyle}
              >
                Download Word
              </a>
            </div>
          </div>
        )}
        {analyzed && (
          <div
            style={{
              border: "1px solid #e0e0e0",
              borderRadius: 12,
              padding: 16,
              maxWidth: 420,
              fontFamily: "system-ui, sans-serif",
              fontSize: 14,
            }}
          >
            <strong>Your long-term study path</strong>
            <p style={{ color: "#777", fontSize: 12, margin: "4px 0 10px" }}>
              A multi-stage roadmap beyond just your next course — where this could lead.
            </p>
            {studyPathError && (
              <div style={{ color: "#c0392b", fontSize: 13, marginBottom: 8 }}>{studyPathError}</div>
            )}
            {studyPath && (
              <ol style={{ paddingLeft: 20, margin: "0 0 10px" }}>
                {studyPath.map((stage, i) => (
                  <li key={i} style={{ marginBottom: 8 }}>
                    <strong>{stage.title}</strong>{" "}
                    <span style={{ color: "#999", fontSize: 12 }}>({stage.estimatedTimeframe})</span>
                    <div style={{ fontSize: 13 }}>{stage.description}</div>
                  </li>
                ))}
              </ol>
            )}
            <button
              onClick={handleGenerateStudyPath}
              disabled={isGeneratingPath}
              style={{
                padding: "8px 14px",
                borderRadius: 8,
                border: "1px solid #ccc",
                background: "#fff",
                color: "#1a5f7a",
                fontSize: 13,
                fontWeight: 600,
                cursor: isGeneratingPath ? "not-allowed" : "pointer",
                opacity: isGeneratingPath ? 0.6 : 1,
              }}
            >
              {isGeneratingPath ? "Generating..." : studyPath ? "Regenerate" : "Generate my study path"}
            </button>
          </div>
        )}
        {analyzed && <DocumentUpload apiUrl={apiUrl} sessionId={sessionId} onError={onError} />}
      </div>
      <ChatWidget apiUrl={apiUrl} chat={chat} />
    </div>
  );
}
