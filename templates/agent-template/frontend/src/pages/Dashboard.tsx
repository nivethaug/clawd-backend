import { useState } from "react";
import { Activity as ActivityIcon, Clock, CalendarClock, Database, Check, Copy } from "lucide-react";
import { useAgentStatus } from "../hooks/useAgentStatus";
import { Empty, Section, StatCard, StatusPill, TimeAgo } from "../components/ui";

/**
 * Default dashboard page: title + active badge, KPI row, and a balanced
 * two-column main area — left: Jobs, agent data collections, Recent
 * Activity; right: Agent State + Webhook Trigger. All data is LIVE from
 * the token-scoped status endpoint (15s polling in useAgentStatus).
 */
export default function Dashboard() {
  const { data, error, loading, refresh } = useAgentStatus();
  const [copied, setCopied] = useState(false);

  if (loading && !data) {
    return (
      <div className="flex h-full items-center gap-3 rounded-xl border border-[#E8E2D8] bg-card p-6 text-muted-foreground shadow-soft">
        <span className="animate-pulse-soft h-2.5 w-2.5 rounded-full bg-[#168F86]" />
        Loading agent status…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="h-full rounded-xl border border-[#E88A8A]/45 bg-card p-5 shadow-soft">
        <p className="font-semibold text-[#B03A3A]">Agent status unavailable</p>
        <p className="mt-1 text-sm text-muted-foreground">{error}</p>
        <button
          onClick={refresh}
          className="mt-4 rounded-full bg-[#168F86] px-4 py-2 text-sm font-semibold text-white shadow-soft transition-all duration-200 hover:shadow-lift active:scale-95"
        >
          Retry
        </button>
      </div>
    );
  }

  const activeJobs = data.jobs.filter((j) => j.status === "active").length;
  const lastLog = data.recent_logs[0];
  const collectionNames = Object.keys(data.collections ?? {});

  const copyTrigger = async () => {
    try {
      await navigator.clipboard.writeText(data.trigger_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable — the URL stays selectable below */
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* KPI row */}
      <div className="grid shrink-0 grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Active Jobs"
          value={activeJobs}
          hint={`${data.jobs.length} total`}
          icon={<ActivityIcon className="h-5 w-5" />}
          iconTone="sage"
          delay={0}
        />
        <StatCard
          label="Last Run"
          value={lastLog ? <TimeAgo iso={lastLog.created_at} /> : "—"}
          hint={lastLog?.task_type}
          icon={<Clock className="h-5 w-5" />}
          iconTone="teal"
          delay={0.08}
        />
        <StatCard
          label="Next Run"
          value={data.jobs.some((j) => j.next_run) ? <TimeAgo iso={soonestNextRun(data.jobs)} /> : "—"}
          icon={<CalendarClock className="h-5 w-5" />}
          iconTone="amber"
          delay={0.16}
        />
        <StatCard
          label="Collections"
          value={collectionNames.length}
          hint="in agent db"
          icon={<Database className="h-5 w-5" />}
          iconTone="violet"
          delay={0.24}
        />
      </div>

      {/* Balanced two-column main area */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-3">

        {/* ── LEFT (2/3): Jobs · Agent data · Activity ── */}
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1 lg:col-span-2">
          <Section title="Jobs" delay={0.3}>
            {data.jobs.length === 0 ? (
              <Empty text="No jobs yet — the agent creates them as it's set up." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#E8E2D8] text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="pb-2.5 pr-4 font-medium">Task</th>
                      <th className="pb-2.5 pr-4 font-medium">Schedule</th>
                      <th className="pb-2.5 pr-4 font-medium">Status</th>
                      <th className="pb-2.5 pr-4 font-medium">Last Run</th>
                      <th className="pb-2.5 font-medium">Next Run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.jobs.map((job) => (
                      <tr key={job.id} className="border-b border-[#E8E2D8]/60 transition-colors last:border-0 hover:bg-[#F5F1E8]/50">
                        <td className="py-2.5 pr-4 font-medium">{job.task_type}</td>
                        <td className="py-2.5 pr-4 text-muted-foreground">{job.schedule_value}</td>
                        <td className="py-2.5 pr-4"><StatusPill status={job.status} /></td>
                        <td className="py-2.5 pr-4"><TimeAgo iso={job.last_run} /></td>
                        <td className="py-2.5"><TimeAgo iso={job.next_run} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>

          {collectionNames.length > 0 && (
            <Section title="Agent Data" delay={0.38}>
              <div className="space-y-5">
                {collectionNames.map((name) => (
                  <CollectionTable key={name} name={name} count={data.collections[name].count} docs={data.collections[name].docs} />
                ))}
              </div>
            </Section>
          )}

          <Section title="Recent Activity" delay={0.46}>
            {data.recent_logs.length === 0 ? (
              <Empty text="No runs recorded yet." />
            ) : (
              <ul className="space-y-2.5">
                {data.recent_logs.slice(0, 20).map((log, i) => (
                  <li
                    key={i}
                    className="anim-activity-in flex items-start gap-3 rounded-xl border border-[#E8E2D8]/70 bg-card px-3.5 py-2.5 text-sm transition-colors duration-200 hover:bg-[#F5F1E8]/70"
                    style={{ animationDelay: `${Math.min(i, 8) * 0.04}s` }}
                  >
                    <span className="mt-0.5 shrink-0"><StatusPill status={log.status} /></span>
                    <div className="min-w-0">
                      <p className="truncate font-medium">{log.task_type}</p>
                      <p className="text-muted-foreground">{log.message}</p>
                    </div>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                      <TimeAgo iso={log.created_at} />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        {/* ── RIGHT (1/3): State · Webhook ── */}
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1">
          <Section title="Agent State" delay={0.34}>
            {data.state && Object.keys(data.state).length > 0 ? (
              <pre className="max-h-72 overflow-auto rounded-xl bg-[#202522] p-4 text-xs leading-relaxed text-[#A8DCC0]">
                {JSON.stringify(data.state, null, 2)}
              </pre>
            ) : (
              <Empty text="No state stored yet." />
            )}
          </Section>

          <Section title="Webhook Trigger" delay={0.42}>
            <p className="text-sm leading-relaxed text-muted-foreground">
              POST to this URL to fire the agent's event job within ~10s.
              Keep it private — <span className="font-medium text-foreground">the URL is the credential</span>.
            </p>
            <div className="mt-4 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-xl border border-[#E8E2D8] bg-[#F5F1E8]/80 px-3.5 py-2.5 text-xs text-foreground">
                {data.trigger_url}
              </code>
              <button
                onClick={copyTrigger}
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white shadow-soft transition-all duration-200 hover:shadow-lift active:scale-90 ${
                  copied ? "bg-[#A8DCC0] text-[#0F6B63]" : "bg-[#168F86]"
                }`}
                aria-label={copied ? "Copied" : "Copy webhook URL"}
              >
                {copied ? <Check className="anim-check-pop h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </button>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}

function soonestNextRun(jobs: { next_run: string | null }[]): string | null {
  const times = jobs.map((j) => j.next_run).filter(Boolean) as string[];
  if (times.length === 0) return null;
  return times.reduce((a, b) => (a < b ? a : b));
}

/** Renders any collection dynamically: union of doc keys → columns (max 5). */
function CollectionTable({ name, count, docs }: { name: string; count: number; docs: Record<string, unknown>[] }) {
  const keys = Array.from(
    docs.reduce((set, doc) => {
      Object.keys(doc).forEach((k) => set.add(k));
      return set;
    }, new Set<string>()),
  )
    .filter((k) => k !== "_id")
    .slice(0, 5);

  return (
    <div>
      <div className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">{name}</h3>
        <span className="text-xs text-muted-foreground">{count} documents</span>
      </div>
      {docs.length === 0 ? (
        <Empty text="No documents yet." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-[#E8E2D8] text-left uppercase tracking-wide text-muted-foreground">
                <th className="pb-1.5 pr-3 font-medium">ts</th>
                {keys.map((k) => (
                  <th key={k} className="pb-1.5 pr-3 font-medium">{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {docs.map((doc, i) => (
                <tr key={doc._id as number ?? i} className="border-b border-[#E8E2D8]/60 last:border-0">
                  <td className="py-1.5 pr-3 text-muted-foreground">
                    <TimeAgo iso={doc.ts as string} />
                  </td>
                  {keys.map((k) => (
                    <td key={k} className="py-1.5 pr-3">{formatCell(doc[k])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
