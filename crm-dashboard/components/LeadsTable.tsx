"use client";

import { Fragment, useState } from "react";
import { useAuth, API_URL } from "./AuthContext";
import { useLeads } from "./useLeads";
import { useCounsellors } from "./useCounsellors";
import { ClassificationBadge } from "./ClassificationBadge";
import { APPLICATION_STATUSES, type ApplicationStatus, type Lead, type LeadStatus } from "./types";

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
      return "#1a7d3a";
    case "Likely":
      return "#1d7a8c";
    case "Possible":
      return "#b7791f";
    case "Unlikely":
      return "#c0392b";
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
          style={selectStyle}
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
          style={selectStyle}
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
      <button onClick={() => user && assign(lead.id, user.id)} disabled={busyId === lead.id} style={smallButtonStyle}>
        Claim{lead.suggestedCounsellorId === user?.id ? " (suggested)" : ""}
      </button>
    );
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        {FILTERS.map((f) => (
          <button
            key={f.label}
            onClick={() => setFilter(f.value)}
            style={{
              padding: "6px 14px",
              borderRadius: 8,
              border: "1px solid #ccc",
              background: filter === f.value ? "#1a5f7a" : "#fff",
              color: filter === f.value ? "#fff" : "#333",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            {f.label}
          </button>
        ))}
        <button
          onClick={() => setInactiveOnly((v) => !v)}
          style={{
            padding: "6px 14px",
            borderRadius: 8,
            border: "1px solid #ccc",
            background: inactiveOnly ? "#c0392b" : "#fff",
            color: inactiveOnly ? "#fff" : "#333",
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          {inactiveOnly ? "Inactive only ✓" : "Inactive only"}
        </button>
        <span style={{ flex: 1 }} />
        <button
          onClick={() => setSort(sort === "desc" ? "asc" : "desc")}
          style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid #ccc", background: "#fff", cursor: "pointer", fontSize: 13 }}
        >
          Sort: {sort === "desc" ? "Newest first" : "Oldest first"}
        </button>
        <button
          onClick={() => refetch()}
          style={{ padding: "6px 14px", borderRadius: 8, border: "1px solid #ccc", background: "#fff", cursor: "pointer", fontSize: 13 }}
        >
          Refresh
        </button>
      </div>

      {error && <p style={{ color: "#c0392b" }}>Error loading leads: {error}</p>}
      {isLoading && leads.length === 0 && <p>Loading...</p>}
      {!isLoading && !error && leads.length === 0 && <p>No leads match this view.</p>}
      {actionError && (
        <p style={{ color: "#c0392b", background: "#fdecea", padding: "8px 12px", borderRadius: 6 }}>
          {actionError}{" "}
          <button
            onClick={() => setActionError(null)}
            style={{ background: "none", border: "none", color: "#c0392b", cursor: "pointer", textDecoration: "underline", fontSize: 13 }}
          >
            Dismiss
          </button>
        </p>
      )}

      {leads.length > 0 && (
        <div style={{ background: "#fff", borderRadius: 8, overflow: "hidden", border: "1px solid #e0e0e0" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "#f0f0f0", textAlign: "left" }}>
                <th style={cellStyle}>Name</th>
                <th style={cellStyle}>Email</th>
                <th style={cellStyle}>Score</th>
                <th style={cellStyle}>Lead Status</th>
                <th style={cellStyle}>Conversion</th>
                <th style={cellStyle}>Application Status</th>
                <th style={cellStyle}>Assigned To</th>
                <th style={cellStyle}>Contact</th>
                <th style={cellStyle}>Submitted</th>
                <th style={cellStyle}></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((lead) => (
                <Fragment key={lead.id}>
                  <tr style={{ borderTop: "1px solid #eee" }}>
                    <td style={cellStyle}>{lead.name}</td>
                    <td style={cellStyle}>{lead.email ?? "—"}</td>
                    <td style={cellStyle}>{lead.score.toFixed(1)}</td>
                    <td style={cellStyle}>
                      <ClassificationBadge status={lead.status} />
                    </td>
                    <td style={cellStyle}>
                      <span style={{ fontWeight: 600, color: conversionColor(lead.conversionPrediction.likelihood) }}>
                        {lead.conversionPrediction.probability}%
                      </span>{" "}
                      <span style={{ color: "#999", fontSize: 11 }}>{lead.conversionPrediction.likelihood}</span>
                    </td>
                    <td style={cellStyle}>
                      <select
                        value={lead.applicationStatus.status}
                        disabled={busyId === lead.id}
                        onChange={(e) => updateStatus(lead.id, e.target.value as ApplicationStatus)}
                        style={selectStyle}
                      >
                        {APPLICATION_STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {humanizeStatus(s)}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td style={cellStyle}>{renderAssignment(lead)}</td>
                    <td style={cellStyle}>
                      {lead.inactivity.isInactive ? (
                        <span style={{ color: "#c0392b", fontWeight: 600 }}>
                          ⚠ {lead.inactivity.daysSinceContact === null ? "never contacted" : `${lead.inactivity.daysSinceContact}d`}
                        </span>
                      ) : (
                        <span style={{ color: "#999" }}>
                          {lead.lastContactedAt ? relativeTime(lead.lastContactedAt) : "on track"}
                        </span>
                      )}
                    </td>
                    <td style={cellStyle}>{relativeTime(lead.createdAt)}</td>
                    <td style={cellStyle}>
                      <button
                        onClick={() => setExpandedId(expandedId === lead.id ? null : lead.id)}
                        style={smallButtonStyle}
                      >
                        {expandedId === lead.id ? "Hide" : "View"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === lead.id && (
                    <tr style={{ background: "#fafafa" }}>
                      <td colSpan={10} style={{ ...cellStyle, whiteSpace: "pre-wrap" }}>
                        <strong>Reference code:</strong> {lead.referenceCode ?? "—"} &nbsp;
                        <strong>Phone:</strong> {lead.phone ?? "—"}
                        {lead.aiResponse && (
                          <span style={{ marginLeft: 12 }} onClick={(e) => e.stopPropagation()}>
                            <a
                              href={`${API_URL}/api/profile/${lead.sessionId}/export?format=pdf`}
                              style={downloadLinkStyle}
                            >
                              Download PDF
                            </a>
                            <a
                              href={`${API_URL}/api/profile/${lead.sessionId}/export?format=docx`}
                              style={{ ...downloadLinkStyle, marginLeft: 8 }}
                            >
                              Download Word
                            </a>
                          </span>
                        )}
                        <br />
                        <strong>GPA:</strong> {lead.gpa} / 4.0 &nbsp; <strong>IELTS:</strong> {lead.ielts} / 9.0 &nbsp;
                        <strong>Budget:</strong> ${lead.budget.toLocaleString()} &nbsp; <strong>Gap:</strong> {lead.gap}y
                        <br />
                        <strong>Preferred country:</strong> {lead.preferredCountry ?? "Any"} &nbsp;
                        <strong>Recommended:</strong> {lead.countries ?? "—"}
                        <br />
                        <strong>Academic background:</strong> {lead.academicBackground ?? "—"} &nbsp;
                        <strong>Migration intent:</strong> {lead.migrationIntent ?? "—"}
                        <br />
                        <strong>Career goals:</strong> {lead.careerGoals || "—"}

                        <br />
                        <br />
                        <strong>Application status:</strong> {lead.applicationStatus.label} — {lead.applicationStatus.description}
                        <br />
                        <strong>AI report sent:</strong>
                        <br />
                        {lead.aiResponse}
                        {lead.nextSteps.length > 0 && (
                          <>
                            <br />
                            <br />
                            <strong>Next steps:</strong>
                            <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                              {lead.nextSteps.map((step, i) => (
                                <li key={i}>{step}</li>
                              ))}
                            </ol>
                          </>
                        )}

                        <br />
                        <strong>Documents ({lead.documentChecklist.complete ? "complete" : "incomplete"}):</strong>
                        <ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                          {lead.documentChecklist.items.map((item) => (
                            <li key={item.documentType}>
                              <span
                                style={{
                                  fontWeight: 600,
                                  color: !item.uploaded ? "#999" : item.status === "valid" ? "#1a7d3a" : "#c0392b",
                                }}
                              >
                                [{!item.uploaded ? "MISSING" : DOC_STATUS_LABEL[item.status ?? ""] ?? item.status}]
                              </span>{" "}
                              {item.label}
                              {item.issues.length > 0 && (
                                <ul style={{ margin: "2px 0 0", paddingLeft: 18, color: "#c0392b" }}>
                                  {item.issues.map((issue, j) => (
                                    <li key={j}>{issue}</li>
                                  ))}
                                </ul>
                              )}
                            </li>
                          ))}
                        </ul>

                        <br />
                        <strong>Follow-up assistant:</strong>
                        <div style={{ marginTop: 4 }}>
                          {lead.followupTiming && (
                            <div>
                              <strong>Timing:</strong> {lead.followupTiming}
                            </div>
                          )}
                          {lead.followupAction && (
                            <div>
                              <strong>Suggested action:</strong> {lead.followupAction}
                            </div>
                          )}
                          {lead.followupSuggestion && (
                            <div>
                              <strong>Message draft:</strong> {lead.followupSuggestion}
                            </div>
                          )}
                          <div style={{ marginTop: 6, display: "flex", gap: 8 }}>
                            <button
                              onClick={() => generateFollowup(lead.id)}
                              disabled={busyId === lead.id}
                              style={smallButtonStyle}
                            >
                              {busyId === lead.id ? "Working..." : lead.followupSuggestion ? "Regenerate suggestion" : "Generate suggestion"}
                            </button>
                            <button onClick={() => markContacted(lead.id)} disabled={busyId === lead.id} style={smallButtonStyle}>
                              Mark contacted
                            </button>
                          </div>
                        </div>

                        <br />
                        <strong>Conversion likelihood:</strong>{" "}
                        <span style={{ fontWeight: 600, color: conversionColor(lead.conversionPrediction.likelihood) }}>
                          {lead.conversionPrediction.probability}% — {lead.conversionPrediction.likelihood}
                        </span>
                        <ul style={{ margin: "4px 0 0", paddingLeft: 20, color: "#666" }}>
                          {lead.conversionPrediction.factors.map((factor, i) => (
                            <li key={i}>{factor}</li>
                          ))}
                        </ul>

                        <br />
                        <strong>Study path:</strong>
                        {lead.studyPath ? (
                          <ol style={{ margin: "4px 0 0", paddingLeft: 20 }}>
                            {lead.studyPath.map((stage, i) => (
                              <li key={i} style={{ marginBottom: 4 }}>
                                <strong>{stage.title}</strong> <span style={{ color: "#999" }}>({stage.estimatedTimeframe})</span>
                                <br />
                                {stage.description}
                              </li>
                            ))}
                          </ol>
                        ) : (
                          <div style={{ color: "#999", fontSize: 12, marginTop: 4 }}>Not generated yet — the student can generate this from the chat widget.</div>
                        )}

                        <br />
                        <strong>Counsellor notes:</strong>
                        <br />
                        <textarea
                          value={notesDraft[lead.id] ?? lead.counsellorNotes ?? ""}
                          onChange={(e) => setNotesDraft((prev) => ({ ...prev, [lead.id]: e.target.value }))}
                          rows={3}
                          style={{ width: "100%", marginTop: 4, fontFamily: "inherit", fontSize: 13, boxSizing: "border-box" }}
                        />
                        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                          <button onClick={() => saveNotes(lead.id)} disabled={busyId === lead.id} style={smallButtonStyle}>
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
                            style={smallButtonStyle}
                          >
                            Suggest note
                          </button>
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

const cellStyle: React.CSSProperties = { padding: "10px 12px" };
const selectStyle: React.CSSProperties = { padding: "4px 6px", borderRadius: 6, border: "1px solid #ccc", fontSize: 12 };
const smallButtonStyle: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: 6,
  border: "1px solid #ccc",
  background: "#fff",
  cursor: "pointer",
  fontSize: 12,
};
const downloadLinkStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: "#1a5f7a",
  textDecoration: "none",
  border: "1px solid #ccc",
  borderRadius: 6,
  padding: "2px 8px",
};
