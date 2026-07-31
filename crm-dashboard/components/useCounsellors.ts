import { useEffect, useState } from "react";
import { API_URL, useAuth } from "./AuthContext";
import type { Counsellor } from "./types";

/** One-shot fetch — the counsellor roster changes rarely, unlike leads. */
export function useCounsellors() {
  const { token, logout } = useAuth();
  const [counsellors, setCounsellors] = useState<Counsellor[]>([]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    fetch(`${API_URL}/api/admin/counsellors`, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (res.status === 401) {
          logout();
          return null;
        }
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json() as Promise<{ counsellors: Counsellor[] }>;
      })
      .then((data) => {
        if (data && !cancelled) setCounsellors(data.counsellors);
      })
      .catch(() => {
        // Non-critical for the main table — assignment controls just won't have names to show.
      });
    return () => {
      cancelled = true;
    };
  }, [token, logout]);

  return counsellors;
}
