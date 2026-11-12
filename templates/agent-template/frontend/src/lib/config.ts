/**
 * Agent dashboard configuration.
 *
 * {agent_status_url} is replaced by the platform at creation time with the
 * token-scoped status endpoint for THIS agent:
 *   https://api.dreamagent.cloud/api/agent-status/{trigger_token}
 *
 * DATA RULE: this URL is the ONLY data source for the dashboard. Never call
 * other APIs, backends, or hardcode data (see frontend/agent/README.md).
 */
export const AGENT_STATUS_URL = "{agent_status_url}";

export const POLL_INTERVAL_MS = 15_000;

export interface AgentJob {
  id: number;
  task_type: string;
  schedule_value: string;
  status: string;
  last_run: string | null;
  next_run: string | null;
}

export interface AgentLogEntry {
  created_at: string;
  task_type: string;
  status: string;
  message: string;
}

export interface CollectionSummary {
  count: number;
  docs: Record<string, unknown>[];
}

export interface AgentStatus {
  name: string;
  description: string | null;
  jobs: AgentJob[];
  recent_logs: AgentLogEntry[];
  state: Record<string, unknown> | null;
  collections: Record<string, CollectionSummary>;
  channels?: string[];
  trigger_url: string;
}
