const AI_COUNSELLOR_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
const CRM_DASHBOARD_URL = process.env.NEXT_PUBLIC_SELF_URL ?? "http://localhost:3002";

function tabStyle(isActive: boolean): React.CSSProperties {
  return {
    padding: "8px 16px",
    borderRadius: 8,
    fontSize: 14,
    fontWeight: 600,
    textDecoration: "none",
    color: isActive ? "#1a5f7a" : "#666",
    background: isActive ? "#e3f1f7" : "transparent",
  };
}

/**
 * AI Counsellor (the client's public site) and this CRM Dashboard are
 * separate deployments (the CRM is internal/login-gated), so this is a
 * cross-app nav, not client-side routing.
 */
export function TopNav({ active }: { active: "counsellor" | "crm" }) {
  return (
    <nav style={{ display: "inline-flex", gap: 4, padding: 4, background: "#f1f3f5", borderRadius: 10, marginBottom: 24 }}>
      <a href={AI_COUNSELLOR_URL} style={tabStyle(active === "counsellor")}>
        AI Counsellor
      </a>
      <a href={CRM_DASHBOARD_URL} style={tabStyle(active === "crm")}>
        CRM Dashboard
      </a>
    </nav>
  );
}
