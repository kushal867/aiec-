import styles from "./TopNav.module.css";

const AI_COUNSELLOR_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
const CRM_DASHBOARD_URL = process.env.NEXT_PUBLIC_SELF_URL ?? "http://localhost:3002";

/**
 * AI Counsellor (the client's public site) and this CRM Dashboard are
 * separate deployments (the CRM is internal/login-gated), so this is a
 * cross-app nav, not client-side routing.
 */
export function TopNav({ active }: { active: "counsellor" | "crm" }) {
  return (
    <nav className={styles.nav}>
      <a href={AI_COUNSELLOR_URL} className={`${styles.tab} ${active === "counsellor" ? styles.tabActive : ""}`}>
        AI Counsellor
      </a>
      <a href={CRM_DASHBOARD_URL} className={`${styles.tab} ${active === "crm" ? styles.tabActive : ""}`}>
        CRM Dashboard
      </a>
    </nav>
  );
}
