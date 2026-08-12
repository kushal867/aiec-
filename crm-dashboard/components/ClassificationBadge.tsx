import type { LeadStatus } from "./types";

const COLORS: Record<LeadStatus, { bg: string; fg: string }> = {
  Hot: { bg: "#fde2e1", fg: "#c0392b" },
  Warm: { bg: "#fdf1d6", fg: "#b7791f" },
  Cold: { bg: "#dbeafe", fg: "#1d4ed8" },
};

export function ClassificationBadge({ status }: { status: LeadStatus }) {
  const { bg, fg } = COLORS[status];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 11px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: "0.02em",
        textTransform: "uppercase",
        background: bg,
        color: fg,
      }}
    >
      {status}
    </span>
  );
}
