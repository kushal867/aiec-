"use client";

import { Fragment, useState } from "react";
import { useAuth, API_URL } from "./AuthContext";
import { useLeads } from "./useLeads";
import { useCounsellors } from "./useCounsellors";
import { ClassificationBadge } from "./ClassificationBadge";
import { APPLICATION_STATUSES, type ApplicationStatus, type Lead, type LeadStatus } from "./types";
import styles from "./LeadsTable.module.css";

const FILTERS: { label: string; value: LeadStatus | undefined }[] = [
  { label: "All", value: undefined },
  { label: "Hot", value: "Hot" },
  { label: "Warm", value: "Warm" },
  { label: "Cold", value: "Cold" },
];

const DOC_STATUS_LABEL: Record<string, string> = {
  valid: "Valid",
  issues_found: "Issues found",
  unclear: "Unclear",
};

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function humanizeStatus(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Every field used here is already loaded in the Lead object the dashboard
// fetches for the table — no backend round-trip needed, this just assembles
// what's already on screen into a ready-to-edit starting note instead of
// making a counsellor type the same profile summary out by hand every time.
function suggestCounsellorNote(lead: Lead): string {
  const missingLabels = lead.documentChecklist.items
    .filter((item) => lead.documentChecklist.missing.includes(item.documentType))
    .map((item) => item.label);
  const docsLine = lead.documentChecklist.complete
    ? "Documents: all complete."
    : `Documents: missing ${missingLabels.length > 0 ? missingLabels.join(", ") : "none tracked"}.`;

  return [
    `Profile: ${lead.academicBackground ? humanizeStatus(lead.academicBackground) : "background not specified"}, ` +
      `GPA ${lead.gpa}/4.0, IELTS ${lead.ielts}/9.0, budget $${lead.budget.toLocaleString()}/year, ${lead.gap}y gap.`,
    `Preferred country: ${lead.preferredCountry ?? "Any"}. Career goal: ${lead.careerGoals || "not specified"}.`,
    `Migration intent: ${lead.migrationIntent ? humanizeStatus(lead.migrationIntent) : "not specified"}.`,
    `Lead classification: ${lead.status} (${lead.score}/10). Conversion likelihood: ${lead.conversionPrediction.probability}% (${lead.conversionPrediction.likelihood}).`,
    docsLine,
    `Application status: ${lead.applicationStatus.label}.`,
  ].join("\n");
}

function conversionColor(likelihood: Lead["conversionPrediction"]["likelihood"]): string {
  switch (likelihood) {
    case "Very Likely":
      return "var(--color-success)";
    case "Likely":
      return "#1d7a8c";
    case "Possible":
      return "var(--color-warning)";
    case "Unlikely":
      return "var(--color-danger)";
  }
}

export function LeadsTable() {
  const { token, user } = useAuth();
  const [filter, setFilter] = useState<LeadStatus | undefined>(undefined);
  const [sort, setSort] = useState<"asc" | "desc">("desc");
  const [inactiveOnly, setInactiveOnly] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [notesDraft, setNotesDraft] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { leads, isLoading, error, refetch } = useLeads({ status: filter, sort, inactiveOnly });
  const counsellors = useCounsellors();

  const counsellorName = (id: number | null) => {
    if (!id) return null;
    return counsellors.find((c) => c.id === id)?.name ?? `#${id}`;
  };

  const authedFetch = async (path: string, options: RequestInit = {}) => {
    const res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers ?? {}) },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error ?? `Request failed: ${res.status}`);
    }
    return res.json();
  };

  // Plain <a href> can't carry an Authorization header, and the old links
  // pointed at the public, session_id-gated /profile/:sessionId/export route
  // — session_id is generated client-side, sent on every widget request, and
  // shown right here in this table, so it's a far weaker secret than it
  // needs to be for full profile data. This fetches the auth-gated,
  // role-scoped /admin/leads/:id/export route instead and downloads the blob
  // directly, matching how every other admin action in this file authenticates.
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const downloadReport = async (id: number, name: string, format: "pdf" | "docx") => {
    const key = `${id}-${format}`;
    setDownloadingId(key);
    setActionError(null);
    try {
      const res = await fetch(`${API_URL}/api/admin/leads/${id}/export?format=${format}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `Request failed: ${res.status}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `AIEC-Report-${name.replace(/[^a-zA-Z0-9-]+/g, "_")}.${format}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Failed to download report. Please try again.");
    } finally {
      setDownloadingId(null);
    }
  };

  // Every admin action (notes, status, assign, contacted, follow-up
  // generation) funnels through here so none of them can silently swallow a
  // failure — previously each one only had a `finally` resetting the busy
  // state, with no `catch` at all, so a failed request (e.g. a 404 from
  // trying to act on a lead you're not assigned to) just made the button
  // stop "Working..." with zero feedback, as if nothing had happened.
  const runAction = async (id: number, action: () => Promise<unknown>) => {
    setBusyId(id);
    setActionError(null);
    try {
      await action();
      await refetch();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusyId(null);
    }
  };

  const saveNotes = (id: number) =>
    runAction(id, () =>
      authedFetch(`/api/admin/leads/${id}/notes`, {
        method: "PATCH",
        body: JSON.stringify({ notes: notesDraft[id] ?? "" }),
      }),
    );

  const updateStatus = (id: number, applicationStatus: ApplicationStatus) =>
    runAction(id, () =>
      authedFetch(`/api/admin/leads/${id}/status`, {
        method: "PATCH",
        body: JSON.stringify({ applicationStatus }),
      }),
    );

  const assign = (id: number, counsellorId: number) =>
    runAction(id, () =>
      authedFetch(`/api/admin/leads/${id}/assign`, {
        method: "POST",
        body: JSON.stringify({ counsellorId }),
      }),
    );

  const markContacted = (id: number) =>
    runAction(id, () => authedFetch(`/api/admin/leads/${id}/contacted`, { method: "POST" }));

  const generateFollowup = (id: number) => {
    runAction(id, () => authedFetch(`/api/admin/leads/${id}/followup`, { method: "POST" }));
  };

  const renderAssignment = (lead: Lead) => {
    if (lead.assignedCounsellorId) {
      const name = counsellorName(lead.assignedCounsellorId);
      if (user?.role !== "admin") return <span>{name}</span>;
      return (
        <select
          value={lead.assignedCounsellorId}
          disabled={busyId === lead.id}
          onChange={(e) => assign(lead.id, Number(e.target.value))}
          className={styles.select}
        >
          {counsellors.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      );
    }

    if (user?.role === "admin") {
      return (
        <select
          value=""
          disabled={busyId === lead.id}
          onChange={(e) => e.target.value && assign(lead.id, Number(e.target.value))}
          className={styles.select}
        >
          <option value="">
            {lead.suggestedCounsellorId ? `Suggested: ${counsellorName(lead.suggestedCounsellorId)}` : "Assign..."}
          </option>
          {counsellors.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      );
    }

    // Counsellor view — self-claim only.
    return (
      <button onClick={() => user && assign(lead.id, user.id)} disabled={busyId === lead.id} className={styles.smallButton}>
        Claim{lead.suggestedCounsellorId === user?.id ? " (suggested)" : ""}
      </button>
    );
  };

  return (
    <div>
      <div className={styles.toolbar}>
        {FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setFilter(f.value)}
            className={`${styles.pillButton} ${filter === f.value ? styles.pillButtonActive : ""}`}
          >
            {f.label}
          </button>
        ))}
        <button
          onClick={() => setInactiveOnly((v) => !v)}
          className={`${styles.pillButton} ${inactiveOnly ? styles.pillButtonDanger : ""}`}
        >
          {inactiveOnly ? "Inactive only ✓" : "Inactive only"}
        </button>
        <span className={styles.spacer} />
        <button onClick={() => setSort(sort === "desc" ? "asc" : "desc")} className={styles.pillButton}>
          Sort: {sort === "desc" ? "Newest first" : "Oldest first"}
        </button>
        <button onClick={() => refetch()} className={styles.pillButton}>
          Refresh
        </button>
      </div>

      {error && <p className={styles.errorText}>Error loading leads: {error}</p>}
      {isLoading && leads.length === 0 && <p>Loading...</p>}
      {!isLoading && !error && leads.length === 0 && <p>No leads match this view.</p>}
      {actionError && (
        <p className={styles.actionError}>
          {actionError}
          <button onClick={() => setActionError(null)} className={styles.dismissButton}>
            Dismiss
          </button>
        </p>
      )}

      {leads.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr className={styles.theadRow}>
                <th className={styles.th}>Name</th>
                <th className={styles.th}>Email</th>
                <th className={styles.th}>Score</th>
                <th className={styles.th}>Lead Status</th>
                <th className={styles.th}>Conversion</th>
                <th className={styles.th}>Application Status</th>
                <th className={styles.th}>Assigned To</th>
                <th className={styles.th}>Contact</th>
                <th className={styles.th}>Submitted</th>
                <th className={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <Fragment key={lead.id}>
                  <tr className={styles.row}>
                    <td className={styles.td}>{lead.name}</td>
                    <td className={styles.td}>{lead.email ?? "—"}</td>
                    <td className={styles.td}>{lead.score.toFixed(1)}</td>
                    <td className={styles.td}>
                      <ClassificationBadge status={lead.status} />
                    </td>
                    <td className={styles.td}>
                      <span className={styles.conversionValue} style={{ color: conversionColor(lead.conversionPrediction.likelihood) }}>
                        {lead.conversionPrediction.probability}%
                      </span>{" "}
                      <span className={styles.conversionLikelihood}>{lead.conversionPrediction.likelihood}</span>
                    </td>
                    <td className={styles.td}>
                      <select
                        value={lead.applicationStatus.status}
                        disabled={busyId === lead.id}
                        onChange={(e) => updateStatus(lead.id, e.target.value as ApplicationStatus)}
                        className={styles.select}
                      >
                        {APPLICATION_STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {humanizeStatus(s)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className={styles.td}>{renderAssignment(lead)}</td>
                    <td className={styles.td}>
                      {lead.inactivity.isInactive ? (
                        <span className={styles.inactiveFlag}>
                          ⚠ {lead.inactivity.daysSinceContact === null ? "never contacted" : `${lead.inactivity.daysSinceContact}d`}
                        </span>
                      ) : (
                        <span className={styles.mutedText}>
                          {lead.lastContactedAt ? relativeTime(lead.lastContactedAt) : "on track"}
                        </span>
                      )}
                    </td>
                    <td className={styles.td}>{relativeTime(lead.createdAt)}</td>
                    <td className={styles.td}>
                      <button
                        onClick={() => setExpandedId(expandedId === lead.id ? null : lead.id)}
                        className={styles.smallButton}
                      >
                        {expandedId === lead.id ? "Hide" : "View"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === lead.id && (
                    <tr className={styles.expandedRow}>
                      <td colSpan={10} className={styles.expandedCell}>
                        <div className={styles.detailGrid}>
                          <div className={styles.detailSection}>
                            <p className={styles.detailSectionTitle}>Profile</p>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Reference:</span> {lead.referenceCode ?? "—"}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Phone:</span> {lead.phone ?? "—"}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>GPA:</span> {lead.gpa} / 4.0 &nbsp;
                              <span className={styles.detailLabel}>IELTS:</span> {lead.ielts} / 9.0
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Budget:</span> ${lead.budget.toLocaleString()} &nbsp;
                              <span className={styles.detailLabel}>Gap:</span> {lead.gap}y
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Preferred country:</span> {lead.preferredCountry ?? "Any"}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Recommended:</span> {lead.countries ?? "—"}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Academic background:</span> {lead.academicBackground ?? "—"}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Migration intent:</span> {lead.migrationIntent ?? "—"}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Career goals:</span> {lead.careerGoals || "—"}
                            </div>
                          </div>

                          <div className={styles.detailSection}>
                            <p className={styles.detailSectionTitle}>Application &amp; conversion</p>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Status:</span> {lead.applicationStatus.label} —{" "}
                              {lead.applicationStatus.description}
                            </div>
                            <div className={styles.detailRow}>
                              <span className={styles.detailLabel}>Conversion likelihood:</span>{" "}
                              <span
                                className={styles.conversionValue}
                                style={{ color: conversionColor(lead.conversionPrediction.likelihood) }}
                              >
                                {lead.conversionPrediction.probability}% — {lead.conversionPrediction.likelihood}
                              </span>
                            </div>
                            {lead.conversionPrediction.factors.length > 0 && (
                              <ul className={styles.detailList}>
                                {lead.conversionPrediction.factors.map((factor, i) => (
                                  <li key={i}>{factor}</li>
                                ))}
                              </ul>
                            )}
                          </div>

                          <div className={styles.detailSection}>
                            <p className={styles.detailSectionTitle}>
                              Documents ({lead.documentChecklist.complete ? "complete" : "incomplete"})
                            </p>
                            {lead.documentChecklist.items.map((item) => (
                              <div key={item.documentType} className={styles.docItem}>
                                <span
                                  className={`${styles.docTag} ${
                                    !item.uploaded ? styles.tagMissing : item.status === "valid" ? styles.tagValid : styles.tagIssue
                                  }`}
                                >
                                  [{!item.uploaded ? "MISSING" : DOC_STATUS_LABEL[item.status ?? ""] ?? item.status}]
                                </span>
                                <span>
                                  {item.label}
                                  {item.issues.length > 0 && (
                                    <ul className={`${styles.detailList} ${styles.detailListDanger}`}>
                                      {item.issues.map((issue, j) => (
                                        <li key={j}>{issue}</li>
                                      ))}
                                    </ul>
                                  )}
                                </span>
                              </div>
                            ))}
                          </div>

                          <div className={styles.detailSection}>
                            <p className={styles.detailSectionTitle}>Follow-up assistant</p>
                            {lead.followupTiming && (
                              <div className={styles.detailRow}>
                                <span className={styles.detailLabel}>Timing:</span> {lead.followupTiming}
                              </div>
                            )}
                            {lead.followupAction && (
                              <div className={styles.detailRow}>
                                <span className={styles.detailLabel}>Suggested action:</span> {lead.followupAction}
                              </div>
                            )}
                            {lead.followupSuggestion && (
                              <div className={styles.detailRow}>
                                <span className={styles.detailLabel}>Message draft:</span> {lead.followupSuggestion}
                              </div>
                            )}
                            <div className={styles.notesActions}>
                              <button onClick={() => generateFollowup(lead.id)} disabled={busyId === lead.id} className={styles.smallButton}>
                                {busyId === lead.id ? "Working..." : lead.followupSuggestion ? "Regenerate suggestion" : "Generate suggestion"}
                              </button>
                              <button onClick={() => markContacted(lead.id)} disabled={busyId === lead.id} className={styles.smallButton}>
                                Mark contacted
                              </button>
                            </div>
                          </div>

                          <div className={styles.detailSection}>
                            <p className={styles.detailSectionTitle}>Study path</p>
                            {lead.studyPath ? (
                              <ol className={styles.detailList}>
                                {lead.studyPath.map((stage, i) => (
                                  <li key={i} style={{ marginBottom: 6 }}>
                                    <strong>{stage.title}</strong> <span className={styles.mutedText}>({stage.estimatedTimeframe})</span>
                                    <div>{stage.description}</div>
                                  </li>
                                ))}
                              </ol>
                            ) : (
                              <div className={styles.emptyText}>Not generated yet — the student can generate this from the chat widget.</div>
                            )}
                          </div>

                          {lead.aiResponse && (
                            <div className={`${styles.detailSection} ${styles.detailFull}`}>
                              <p className={styles.detailSectionTitle}>AI report sent</p>
                              <div className={styles.detailRow} style={{ whiteSpace: "pre-wrap" }}>
                                {lead.aiResponse}
                              </div>
                              {lead.nextSteps.length > 0 && (
                                <>
                                  <p className={styles.detailSectionTitle} style={{ marginTop: 10 }}>
                                    Next steps
                                  </p>
                                  <ol className={styles.detailList}>
                                    {lead.nextSteps.map((step, i) => (
                                      <li key={i}>{step}</li>
                                    ))}
                                  </ol>
                                </>
                              )}
                              <div className={styles.notesActions}>
                                <button
                                  onClick={() => downloadReport(lead.id, lead.name, "pdf")}
                                  disabled={downloadingId === `${lead.id}-pdf`}
                                  className={styles.downloadButton}
                                >
                                  {downloadingId === `${lead.id}-pdf` ? "Downloading…" : "Download PDF"}
                                </button>
                                <button
                                  onClick={() => downloadReport(lead.id, lead.name, "docx")}
                                  disabled={downloadingId === `${lead.id}-docx`}
                                  className={styles.downloadButton}
                                >
                                  {downloadingId === `${lead.id}-docx` ? "Downloading…" : "Download Word"}
                                </button>
                              </div>
                            </div>
                          )}

                          <div className={`${styles.detailSection} ${styles.detailFull}`}>
                            <p className={styles.detailSectionTitle}>Counsellor notes</p>
                            <textarea
                              value={notesDraft[lead.id] ?? lead.counsellorNotes ?? ""}
                              onChange={(e) => setNotesDraft((prev) => ({ ...prev, [lead.id]: e.target.value }))}
                              rows={3}
                              className={styles.notesTextarea}
                            />
                            <div className={styles.notesActions}>
                              <button onClick={() => saveNotes(lead.id)} disabled={busyId === lead.id} className={styles.smallButton}>
                                {busyId === lead.id ? "Saving..." : "Save notes"}
                              </button>
                              <button
                                onClick={() => {
                                  const existing = (notesDraft[lead.id] ?? lead.counsellorNotes ?? "").trim();
                                  if (existing && !window.confirm("Replace your current notes draft with an auto-generated summary?")) {
                                    return;
                                  }
                                  setNotesDraft((prev) => ({ ...prev, [lead.id]: suggestCounsellorNote(lead) }));
                                }}
                                disabled={busyId === lead.id}
                                className={styles.smallButton}
                              >
                                Suggest note
                              </button>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
