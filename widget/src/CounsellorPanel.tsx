import { useCallback, useState } from "react";
import { ChatWidget } from "./ChatWidget";
import { ProfileForm } from "./ProfileForm";
import { DocumentUpload } from "./DocumentUpload";
import { useChat } from "./useChat";
import { generateSessionId } from "./sessionId";
import { WidgetErrorBoundary } from "./WidgetErrorBoundary";
import styles from "./counsellorPanel.module.css";
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

export function CounsellorPanel(props: CounsellorPanelProps) {
  return (
    <WidgetErrorBoundary label="CounsellorPanel" onError={props.onError}>
      <CounsellorPanelInner {...props} />
    </WidgetErrorBoundary>
  );
}

function CounsellorPanelInner({ apiUrl, countries, onError }: CounsellorPanelProps) {
  const [sessionId] = useState(() => generateSessionId());
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
    <div className={styles.layout}>
      <div className={styles.column}>
        <ProfileForm onSubmit={handleAnalyze} isSubmitting={isAnalyzing} disabled={analyzed} countries={countries} />
        {analyzeError && <div className={styles.errorBanner}>{analyzeError}</div>}
        {result && (
          <div className={styles.card}>
            <div className={styles.resultHeader}>
              <span className={styles.statusPill} style={{ background: STATUS_COLORS[result.status] }}>
                {result.status.toUpperCase()}
              </span>
              <span className={styles.scoreText}>Score: {result.score.toFixed(1)} / 10</span>
            </div>
            <strong>Next steps</strong>
            <ol className={styles.stepsList}>
              {result.nextSteps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
            <div className={styles.referenceBox}>
              Your reference number: <strong>{result.referenceCode}</strong>
              <div className={styles.referenceHint}>
                Save this — you can use it to check your application status anytime.
              </div>
            </div>
            <div className={styles.downloadRow}>
              <a href={`${apiUrl}/api/profile/${sessionId}/export?format=pdf`} className={styles.downloadButton}>
                Download PDF
              </a>
              <a href={`${apiUrl}/api/profile/${sessionId}/export?format=docx`} className={styles.downloadButton}>
                Download Word
              </a>
            </div>
          </div>
        )}
        {analyzed && (
          <div className={styles.card}>
            <strong>Your long-term study path</strong>
            <p className={styles.pathSubtitle}>
              A multi-stage roadmap beyond just your next course — where this could lead.
            </p>
            {studyPathError && <div className={styles.pathError}>{studyPathError}</div>}
            {studyPath && (
              <ol className={styles.pathList}>
                {studyPath.map((stage, i) => (
                  <li key={i}>
                    <strong>{stage.title}</strong> <span className={styles.pathTimeframe}>({stage.estimatedTimeframe})</span>
                    <div className={styles.pathDescription}>{stage.description}</div>
                  </li>
                ))}
              </ol>
            )}
            <button onClick={handleGenerateStudyPath} disabled={isGeneratingPath} className={styles.secondaryButton}>
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
