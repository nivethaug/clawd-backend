/**
 * Helpers over the agent's own document DB (data/agent.db on the worker),
 * served through the token-scoped status endpoint.
 */
import { AGENT_STATUS_URL } from "./config";

export interface AgentDoc {
  _id: number;
  ts: string;
  [key: string]: unknown;
}

/** Fetch up to `limit` latest documents from one collection. */
export async function getCollection(
  name: string,
  opts: { limit?: number } = {},
): Promise<AgentDoc[]> {
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
  const res = await fetch(
    `${AGENT_STATUS_URL}/collections/${encodeURIComponent(name)}?limit=${limit}`,
  );
  if (!res.ok) throw new Error(`Collection "${name}" unavailable (${res.status})`);
  const body = await res.json();
  return (body.docs ?? []) as AgentDoc[];
}
