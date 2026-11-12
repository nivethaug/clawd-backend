import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Activity, Clock, Database, Mail, MonitorPlay, Send, Webhook, Zap } from "lucide-react";
import { useAgentStatus } from "../hooks/useAgentStatus";
import { Empty, StatusPill, TimeAgo } from "../components/ui";

/**
 * Flow — animated workflow chart: how this agent runs.
 *
 * Five zig-zag stages: Triggers (center) → Jobs (left) → Data (right) →
 * Deliver (left) → Present (center). Nodes come from LIVE data (15s
 * polling); each target card carries a teal diamond arrowhead ON its top
 * border (DOM element — it can never drift), and the wires end exactly at
 * the diamond tips.
 *
 * Edge endpoints are measured from CURRENT rects relative to the wrap and
 * looked up via data-flow attributes + querySelector — no refs, no stale
 * measurements. If a card is momentarily missing from the DOM, the previous
 * edges are kept (never rebuilt degraded).
 */

interface Edge {
  id: string;
  d: string;
  delay: number;
}

interface Pt {
  x: number;
  y: number;
}

export default function FlowChart() {
  const { data, error, loading, refresh } = useAgentStatus();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [box, setBox] = useState({ w: 0, h: 0 });

  const jobs = data?.jobs ?? [];
  const scheduleJobs = jobs.filter((j) => j.job_type !== "event");
  const eventJobs = jobs.filter((j) => j.job_type === "event");
  const collectionNames = Object.keys(data?.collections ?? {});
  const channels = data?.channels ?? [];

  const recompute = useCallback(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const q = (sel: string): HTMLElement | null => wrap.querySelector(`[data-flow="${sel}"]`);

    const w = wrap.scrollWidth;
    const h = wrap.scrollHeight;
    const list: Edge[] = [];
    let n = 0;
    const link = (fromSel: string, toSel: string) => {
      const from = q(fromSel);
      const to = q(toSel);
      if (!from || !to) return;
      const rF = from.getBoundingClientRect();
      const rT = to.getBoundingClientRect();
      const wR = wrap.getBoundingClientRect();
      const a = { x: rF.left - wR.left + rF.width / 2, y: rF.bottom - wR.top };
      const b = { x: rT.left - wR.left + rT.width / 2, y: rT.top - wR.top };
      if (b.y <= a.y + 4) return;
      const mid = (a.y + b.y) / 2;
      const ey = b.y - 11; // diamond tip (16px rotated diamond ≈ 11px above border)
      const d = `M ${a.x} ${a.y} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${ey}`;
      list.push({ id: `fp${n}`, d, delay: (n % 6) * 0.45 });
      n += 1;
    };

    for (const j of scheduleJobs) link("schedule", `job-${j.task_type}`);
    for (const j of eventJobs) link("webhook", `job-${j.task_type}`);
    for (const name of collectionNames) for (const j of jobs) link(`job-${j.task_type}`, `col-${name}`);
    for (const name of collectionNames) for (const ch of channels) link(`col-${name}`, `del-${ch}`);
    if (channels.length > 0) for (const ch of channels) link(`del-${ch}`, "present");
    else for (const name of collectionNames) link(`col-${name}`, "present");

    // Bail out when nothing changed — prevents the ResizeObserver feedback
    // loop from escalating into React error #185.
    setBox((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    setEdges((prev) =>
      prev.length === list.length && prev.every((e, i) => e.d === list[i].d && e.delay === list[i].delay)
        ? prev
        : list,
    );
  }, [jobs, scheduleJobs, eventJobs, collectionNames, channels]);

  const rafRef = useRef(0);
  const scheduleRecompute = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(recompute);
  }, [recompute]);

  useLayoutEffect(() => {
    recompute();
  }, [recompute, data]);

  // Settle pass + observers: any card or wrap size change re-measures
  useEffect(() => {
    const t = setTimeout(scheduleRecompute, 250);
    const ro = new ResizeObserver(scheduleRecompute);
    if (wrapRef.current) ro.observe(wrapRef.current);
    wrapRef.current?.querySelectorAll("[data-flow]").forEach((el) => ro.observe(el));
    window.addEventListener("resize", scheduleRecompute);
    return () => {
      clearTimeout(t);
      ro.disconnect();
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener("resize", scheduleRecompute);
    };
  }, [scheduleRecompute, data]);

  if (loading && !data) {
    return (
      <div className="flex h-full items-center gap-3 rounded-xl border border-[#E8E2D8] bg-card p-5 text-muted-foreground shadow-soft">
        <span className="animate-pulse-soft h-2.5 w-2.5 rounded-full bg-[#168F86]" />
        Mapping the agent flow…
      </div>
    );
  }
  if (!data) {
    return (
      <div className="h-full rounded-xl border border-[#E88A8A]/45 bg-card p-5 shadow-soft">
        <p className="font-semibold text-[#B03A3A]">Flow unavailable</p>
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

  const schedules = Array.from(new Set(scheduleJobs.map((j) => j.schedule_value))).join(" · ");
  const lastLogFor = (task: string) => data.recent_logs.find((l) => l.task_type === task);

  const stagePill = (icon: React.ReactNode, label: string) => (
    <div className="flex w-20 shrink-0 justify-end sm:w-28">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-[#E8E2D8] bg-card px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground shadow-soft sm:px-3.5 sm:text-xs">
        {icon}
        {label}
      </span>
    </div>
  );

  const iconChip = (icon: React.ReactNode) => (
    <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-lg bg-[#A8DCC0]/35 text-[#168F86] shadow-soft">
      {icon}
    </div>
  );

  const dimmedNode = (icon: React.ReactNode, title: string, sub: string) => (
    <div className="rounded-2xl border-2 border-dashed border-[#E8E2D8] bg-card/50 px-4 py-2 text-center opacity-60">
      <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-lg bg-[#E8E2D8]/60 text-muted-foreground">
        {icon}
      </div>
      <p className="mt-1.5 text-sm font-semibold text-muted-foreground">{title}</p>
      <p className="text-xs text-muted-foreground/80">{sub}</p>
    </div>
  );

  const deliverMeta: Record<string, { label: string; icon: React.ReactNode }> = {
    telegram: { label: "Telegram", icon: <Send className="h-4 w-4" /> },
    "telegram-pending": { label: "Telegram", icon: <Send className="h-4 w-4" /> },
    discord: { label: "Discord", icon: <Webhook className="h-4 w-4" /> },
    email: { label: "Email", icon: <Mail className="h-4 w-4" /> },
    "webhook-api": { label: "Webhook API", icon: <Webhook className="h-4 w-4" /> },
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex shrink-0 items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight">Agent Flow</h2>
          <p className="text-xs text-muted-foreground">
            How this agent runs — triggers, jobs, data, delivery, presentation
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[#A8DCC0]/60 bg-[#A8DCC0]/25 px-3 py-1 text-xs font-semibold text-[#0F6B63]">
          <Activity className="h-3.5 w-3.5" />
          live · 15s
        </span>
      </div>

      <div ref={wrapRef} className="relative min-h-0 flex-1 overflow-hidden">
        <svg className="pointer-events-none absolute inset-0 z-0" width={box.w} height={box.h} aria-hidden>
          <defs>
            {edges.map((e) => (
              <linearGradient
                key={e.id}
                id={`lg-${e.id}`}
                gradientUnits="userSpaceOnUse"
                x1="0"
                y1="0"
                x2="0"
                y2={box.h}
              >
                <stop offset="0%" stopColor="#7CC9B4" />
                <stop offset="100%" stopColor="#0E7A72" />
              </linearGradient>
            ))}
          </defs>
          {edges.map((e) => (
            <g key={e.id}>
              <path
                d={e.d}
                fill="none"
                stroke="#3BBFAE"
                strokeWidth="4"
                strokeLinecap="round"
                strokeDasharray="0.5 16"
                opacity="0.8"
                className="flow-dash"
              />
              <path
                id={e.id}
                d={e.d}
                fill="none"
                stroke={`url(#lg-${e.id})`}
                strokeWidth="3"
                strokeLinecap="round"
              />
              <circle r="4" fill="#168F86" stroke="#A8DCC0" strokeWidth="1.5" className="flow-dot">
                <animateMotion dur="2.6s" repeatCount="indefinite" begin={`${e.delay}s`}>
                  <mpath href={`#${e.id}`} />
                </animateMotion>
              </circle>
              {(() => {
                const m = e.d.match(/C [\d.]+ [\d.]+, ([\d.]+) ([\d.]+), ([\d.]+) ([\d.]+)$/);
                if (!m) return null;
                return (
                  <g>
                    <circle cx={parseFloat(m[1])} cy={parseFloat(m[2])} r="2.5" fill="#7CC9B4" opacity="0.7" />
                    <circle cx={parseFloat(m[5])} cy={parseFloat(m[6])} r="2.5" fill="#0E7A72" opacity="0.8" />
                  </g>
                );
              })()}
            </g>
          ))}
        </svg>

        <div className="relative z-10 flex h-full flex-col gap-5 py-1">
          {/* TRIGGERS */}
          <div className="flex min-h-0 flex-1 items-center">
            {stagePill(<Zap className="h-3 w-3" />, "Triggers")}
            <div className="flex flex-1 flex-wrap items-stretch justify-center gap-6">
              <div data-flow="schedule" className="min-w-40 rounded-2xl border border-[#A8DCC0]/70 bg-card px-4 py-2 text-center shadow-soft transition-all duration-200 hover:shadow-lift">
                {iconChip(<Clock className="h-5 w-5" />)}
                <p className="mt-1.5 text-sm font-bold">Schedule</p>
                <p className="text-xs font-medium text-[#0F6B63]">{schedules || "—"}</p>
              </div>
              {eventJobs.length > 0 ? (
                <div data-flow="webhook" className="min-w-40 rounded-2xl border border-[#A8DCC0]/70 bg-card px-4 py-2 text-center shadow-soft transition-all duration-200 hover:shadow-lift">
                  {iconChip(<Webhook className="h-5 w-5" />)}
                  <p className="mt-1.5 text-sm font-bold">Webhook</p>
                  <p className="text-xs font-medium text-[#0F6B63]">external events</p>
                </div>
              ) : (
                dimmedNode(<Webhook className="h-5 w-5" />, "Webhook", "not configured")
              )}
              {jobs.length === 0 && (
                <div className="w-full max-w-md">
                  <Empty text="The flow appears when the agent creates its first job." />
                </div>
              )}
            </div>
          </div>

          {/* JOBS */}
          <div className="flex min-h-0 flex-1 items-center">
            {stagePill(<Zap className="h-3 w-3" />, "Jobs")}
            <div className="flex flex-1 flex-wrap items-stretch justify-center gap-6 sm:justify-end sm:pr-[14%]">
              {jobs.length > 0 ? (
                jobs.map((job) => {
                  const last = lastLogFor(job.task_type);
                  const failed = last?.status === "failed";
                  return (
                    <div
                      key={job.id}
                      data-flow={`job-${job.task_type}`}
                      className={`relative min-w-44 rounded-2xl border-2 bg-card px-4 py-2 text-center shadow-soft transition-all duration-200 hover:shadow-lift ${
                        failed ? "border-[#E88A8A]/70" : "border-[#A8DCC0]/80"
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`absolute -top-2.5 left-1/2 h-4 w-4 -translate-x-1/2 rotate-45 border-2 border-[#FFFEFA] ${
                          failed ? "bg-[#E88A8A]" : "bg-[#168F86]"
                        }`}
                      />
                      <div className="flex items-center justify-center gap-2.5">
                        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#168F86]/10 text-[#168F86]">
                          <Zap className="h-4 w-4" />
                        </div>
                        <span className="font-mono text-sm font-bold">{job.task_type}</span>
                        {job.status === "active" && (
                          <span className="relative flex h-2.5 w-2.5">
                            <span className="animate-pulse-soft absolute h-full w-full rounded-full bg-[#168F86]" />
                            <span className="relative h-2.5 w-2.5 rounded-full bg-[#168F86]" />
                          </span>
                        )}
                      </div>
                      <div className="mt-2 flex items-center justify-center gap-2">
                        <span className="rounded-full bg-[#A8DCC0]/40 px-2.5 py-0.5 text-xs font-bold text-[#0F6B63]">
                          {job.schedule_value || job.job_type}
                        </span>
                        <StatusPill status={failed ? "failed" : job.status} />
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        last run <TimeAgo iso={job.last_run} />
                      </p>
                    </div>
                  );
                })
              ) : (
                <div className="w-full max-w-md">
                  <Empty text="The flow appears when the agent creates its first job." />
                </div>
              )}
            </div>
          </div>

          {/* DATA */}
          <div className="flex min-h-0 flex-1 items-center">
            {stagePill(<Database className="h-3 w-3" />, "Data")}
            <div className="flex flex-1 flex-wrap items-stretch justify-center gap-6">
              {collectionNames.length > 0 ? (
                collectionNames.map((name) => (
                  <div
                    key={name}
                    data-flow={`col-${name}`}
                    className="relative min-w-36 rounded-2xl border border-[#A8DCC0]/70 bg-card px-4 py-2 text-center shadow-soft transition-all duration-200 hover:shadow-lift"
                  >
                    <span
                      aria-hidden
                      className="absolute -top-2.5 left-1/2 h-4 w-4 -translate-x-1/2 rotate-45 border-2 border-[#FFFEFA] bg-[#A8DCC0]"
                    />
                    {iconChip(<Database className="h-4 w-4" />)}
                    <p className="mt-1.5 font-mono text-sm font-bold">{name}</p>
                    <p className="text-xs font-medium text-muted-foreground">
                      {data.collections[name].count} docs
                    </p>
                  </div>
                ))
              ) : (
                <div className="w-full max-w-sm">
                  <Empty text="No collections yet — handlers store data here as they run." />
                </div>
              )}
            </div>
          </div>

          {/* DELIVER */}
          <div className="flex min-h-0 flex-1 items-center">
            {stagePill(<Send className="h-3 w-3" />, "Deliver")}
            <div className="flex flex-1 flex-wrap items-stretch justify-center gap-6 sm:justify-start sm:pl-[14%]">
              {channels.length > 0 ? (
                channels.map((ch) => {
                  const m = deliverMeta[ch] ?? { label: ch, icon: <Send className="h-4 w-4" /> };
                  const pending = ch === "telegram-pending";
                  return (
                    <div
                      key={ch}
                      data-flow={`del-${ch}`}
                      className={`relative min-w-40 rounded-2xl border bg-card px-4 py-2 text-center shadow-soft transition-all duration-200 hover:shadow-lift ${
                        pending ? "border-dashed border-[#E8E2D8] opacity-70" : "border-[#A8DCC0]/70"
                      }`}
                    >
                      <span
                        aria-hidden
                        className={`absolute -top-2.5 left-1/2 h-4 w-4 -translate-x-1/2 rotate-45 border-2 border-[#FFFEFA] ${
                          pending ? "bg-[#A8DCC0]" : "bg-[#168F86]"
                        }`}
                      />
                      {iconChip(m.icon)}
                      <p className="mt-1.5 text-sm font-bold">{m.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {pending ? "waiting for /start" : "delivering"}
                      </p>
                    </div>
                  );
                })
              ) : (
                dimmedNode(<Send className="h-5 w-5" />, "Delivery", "no channels")
              )}
            </div>
          </div>

          {/* PRESENT */}
          <div className="flex min-h-0 flex-1 items-center">
            {stagePill(<MonitorPlay className="h-3 w-3" />, "Present")}
            <div className="flex flex-1 justify-center">
              <div
                data-flow="present"
                className="relative min-w-52 rounded-2xl border-2 border-[#A8DCC0]/80 bg-card px-5 py-2.5 text-center shadow-soft transition-all duration-200 hover:shadow-lift"
              >
                <span
                  aria-hidden
                  className="absolute -top-2.5 left-1/2 h-4 w-4 -translate-x-1/2 rotate-45 border-2 border-[#FFFEFA] bg-[#168F86]"
                />
                <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-lg bg-[#168F86] text-white shadow-glow">
                  <MonitorPlay className="h-5 w-5" />
                </div>
                <p className="mt-1.5 text-sm font-extrabold">Live Dashboard</p>
                <p className="text-xs text-muted-foreground">this site · updates every 15s</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
