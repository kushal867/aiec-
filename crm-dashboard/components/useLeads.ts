import { useCallback, useEffect, useState } from "react";
import { API_URL, useAuth } from "./AuthContext";
import type { Lead, LeadStatus } from "./types";

const POLL_INTERVAL_MS = 30_000;

export interface LeadsFilter {
  status?: LeadStatus;
  sort?: "asc" | "desc";
  inactiveOnly?: boolean;
}

export function useLeads(filter: LeadsFilter) {
  const { token, logout } = useAuth();
  const [leads, setLeads] = useState<Lead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    if (!token) return;
    setIsLoading(true);
    try {
      const params = new URLSearchParams({
        sort: filter.sort ?? "desc",
        ...(filter.status ? { status: filter.status } : {}),
        ...(filter.inactiveOnly ? { inactiveOnly: "true" } : {}),
      });
      const res = await fetch(`${API_URL}/api/admin/leads?${params}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.status === 401) {
        logout();
        return;
      }
      if (!res.ok) throw new Error(`Request failed: ${res.status}`);
      const data: { leads: Lead[] } = await res.json();
      setLeads(data.leads);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load leads");
    } finally {
      setIsLoading(false);
    }
  }, [token, logout, filter.status, filter.sort, filter.inactiveOnly]);

  useEffect(() => {
    refetch();
    const id = setInterval(refetch, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refetch]);

  return { leads, isLoading, error, refetch };
}
