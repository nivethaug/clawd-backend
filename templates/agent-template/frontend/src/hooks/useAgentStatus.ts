import { useCallback, useEffect, useRef, useState } from "react";
import { AGENT_STATUS_URL, AgentStatus, POLL_INTERVAL_MS } from "../lib/config";

export interface UseAgentStatus {
  data: AgentStatus | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * Live agent status — polls the token-scoped status endpoint every 15s.
 * `data` stays stale (last good) while a refresh fails; `error` reports it.
 */
export function useAgentStatus(): UseAgentStatus {
  const [data, setData] = useState<AgentStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(AGENT_STATUS_URL);
      if (!res.ok) throw new Error(`Status endpoint returned ${res.status}`);
      const body = (await res.json()) as AgentStatus;
      setData(body);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    timer.current = setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  return { data, error, loading, refresh };
}
