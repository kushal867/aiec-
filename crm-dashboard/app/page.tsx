"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthContext";
import { LeadsTable } from "@/components/LeadsTable";
import { TopNav } from "@/components/TopNav";
import styles from "./page.module.css";

export default function HomePage() {
  const router = useRouter();
  const { user, isReady, logout } = useAuth();

  useEffect(() => {
    if (isReady && !user) router.replace("/login");
  }, [isReady, user, router]);

  if (!isReady || !user) return null;

  return (
    <main className={styles.main}>
      <TopNav active="crm" />
      <div className={styles.headerRow}>
        <div>
          <h1 className={styles.title}>AIEC Global — Leads CRM</h1>
          <p className={styles.subtitle}>
            Hot / Warm / Cold lead classification, application status, and follow-up assistant.
          </p>
        </div>
        <div className={styles.userBox}>
          <div>
            <strong>{user.name}</strong> · {user.role === "admin" ? "Admin" : "Counsellor"}
          </div>
          <button onClick={logout} className={styles.signOut}>
            Sign out
          </button>
        </div>
      </div>

      <LeadsTable />
    </main>
  );
}
