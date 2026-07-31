"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthContext";

export default function LoginPage() {
  const router = useRouter();
  const { user, isReady, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (isReady && user) router.replace("/");
  }, [isReady, user, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <main style={{ maxWidth: 380, margin: "80px auto", padding: "0 16px" }}>
      <h1 style={{ fontSize: 20, marginBottom: 4 }}>AIEC Global — CRM</h1>
      <p style={{ color: "#666", marginTop: 0, marginBottom: 24, fontSize: 14 }}>Sign in with your admin or counsellor account.</p>

      <form
        onSubmit={handleSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 12, background: "#fff", border: "1px solid #e0e0e0", borderRadius: 12, padding: 20 }}
      >
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid #ccc", fontSize: 14 }}
          />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13 }}>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            style={{ padding: "8px 10px", borderRadius: 8, border: "1px solid #ccc", fontSize: 14 }}
          />
        </label>
        {error && <p style={{ color: "#c0392b", fontSize: 13, margin: 0 }}>{error}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          style={{
            padding: "10px 16px",
            borderRadius: 8,
            border: "none",
            background: "#1a5f7a",
            color: "#fff",
            fontSize: 14,
            fontWeight: 600,
            cursor: isSubmitting ? "not-allowed" : "pointer",
            opacity: isSubmitting ? 0.6 : 1,
          }}
        >
          {isSubmitting ? "Signing in..." : "Sign in"}
        </button>
      </form>
    </main>
  );
}
