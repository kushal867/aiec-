"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthContext";
import { LeadsTable } from "@/components/LeadsTable";
import { TopNav } from "@/components/TopNav";

export default function HomePage() {
  const router = useRouter();
  const { user, isReady, logout } = useAuth();

  useEffect(() => {
    if (isReady && !user) router.replace("/login");
  }, [isReady, user, router]);

  if (!isReady || !user) return null;

  return (
    <main style={{ maxWidth: 1200, margin: "0 auto", padding: 32 }}>
      <TopNav active="crm" />
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4 }}>
        <div>
          <h1 style={{ marginBottom: 4 }}>AIEC Global — Leads CRM</h1>
          <p style={{ color: "#666", marginTop: 0 }}>
            Hot / Warm / Cold lead classification, application status, and follow-up assistant.
          </p>
        </div>
        <div style={{ textAlign: "right", fontSize: 13, color: "#444" }}>
          <div>
            <strong>{user.name}</strong> · {user.role === "admin" ? "Admin" : "Counsellor"}
          </div>
          <button
            onClick={logout}
            style={{ marginTop: 6, padding: "4px 12px", borderRadius: 6, border: "1px solid #ccc", background: "#fff", cursor: "pointer", fontSize: 12 }}
          >
            Sign out
          </button>
        </div>
      </div>

      <LeadsTable />
    </main>
  );
}
