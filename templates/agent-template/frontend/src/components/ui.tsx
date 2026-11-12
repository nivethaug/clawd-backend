import { ReactNode } from "react";
import { formatDistanceToNow, parseISO } from "date-fns";

/**
 * Dashboard UI kit — warm ivory / sage / teal light theme.
 * Entrance animations use .anim-card-in with inline animation-delay
 * (staggered); everything respects prefers-reduced-motion via index.css.
 */

/** KPI stat card with pastel icon chip + entrance animation. */
export function StatCard({
  label,
  value,
  hint,
  icon,
  iconTone = "sage",
  delay = 0,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  icon?: ReactNode;
  iconTone?: "sage" | "teal" | "amber" | "violet";
  delay?: number;
}) {
  const tones: Record<string, string> = {
    sage: "bg-[#A8DCC0]/40 text-[#168F86]",
    teal: "bg-[#168F86]/12 text-[#168F86]",
    amber: "bg-[#F5C66B]/30 text-[#A8741B]",
    violet: "bg-[#C9B8F0]/30 text-[#6D55B0]",
  };
  return (
    <div
      className="anim-card-in rounded-xl border border-[#E8E2D8] bg-card p-3.5 shadow-soft transition-all duration-200 hover:shadow-lift"
      style={{ animationDelay: `${delay}s` }}
    >
      <div className="flex items-center gap-3">
        {icon && (
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tones[iconTone]}`}>
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
          <div className="mt-0.5 truncate text-lg font-semibold text-card-foreground">{value}</div>
          {hint && <div className="mt-0.5 truncate text-xs text-muted-foreground">{hint}</div>}
        </div>
      </div>
    </div>
  );
}

const STATUS_TONES: Record<string, string> = {
  active: "bg-[#A8DCC0]/35 text-[#0F6B63] border-[#A8DCC0]/60",
  running: "bg-[#168F86]/12 text-[#168F86] border-[#168F86]/30",
  completed: "bg-[#A8DCC0]/35 text-[#0F6B63] border-[#A8DCC0]/60",
  success: "bg-[#A8DCC0]/35 text-[#0F6B63] border-[#A8DCC0]/60",
  skipped: "bg-[#F5C66B]/25 text-[#A8741B] border-[#F5C66B]/50",
  paused: "bg-[#E8E2D8]/50 text-muted-foreground border-[#E8E2D8]",
  failed: "bg-[#E88A8A]/20 text-[#B03A3A] border-[#E88A8A]/45",
  error: "bg-[#E88A8A]/20 text-[#B03A3A] border-[#E88A8A]/45",
  cancelled: "bg-[#E8E2D8]/50 text-muted-foreground border-[#E8E2D8]",
  interrupted: "bg-[#E88A8A]/20 text-[#B03A3A] border-[#E88A8A]/45",
};

/** Colored status chip (job status, run outcome). */
export function StatusPill({ status }: { status: string }) {
  const tone = STATUS_TONES[(status || "").toLowerCase()] ?? "bg-[#E8E2D8]/50 text-muted-foreground border-[#E8E2D8]";
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium ${tone}`}>
      {status || "unknown"}
    </span>
  );
}

/** Green "Agent Active" badge with gentle pulse. */
export function ActiveBadge({ label = "Agent Active" }: { label?: string }) {
  return (
    <span className="anim-fade-in inline-flex items-center gap-2 rounded-full border border-[#A8DCC0]/70 bg-[#A8DCC0]/25 px-3.5 py-1.5 text-sm font-semibold text-[#0F6B63] shadow-soft">
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-pulse-soft absolute inline-flex h-full w-full rounded-full bg-[#168F86]" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[#168F86]" />
      </span>
      {label}
    </span>
  );
}

/** ISO timestamp → "3 min ago". */
export function TimeAgo({ iso }: { iso: string | null }) {
  if (!iso) return <span className="text-muted-foreground">—</span>;
  try {
    return <span title={iso}>{formatDistanceToNow(parseISO(iso), { addSuffix: true })}</span>;
  } catch {
    return <span className="text-muted-foreground">{iso}</span>;
  }
}

/** Card section wrapper — soft shadow, beige border, rounded 16px. */
export function Section({
  title,
  children,
  delay = 0,
  action,
}: {
  title: string;
  children: ReactNode;
  delay?: number;
  action?: ReactNode;
}) {
  return (
    <section
      className="anim-card-in flex shrink-0 flex-col rounded-xl border border-[#E8E2D8] bg-card shadow-soft transition-shadow duration-200"
      style={{ animationDelay: `${delay}s` }}
    >
      <div className="flex shrink-0 items-center justify-between border-b border-[#E8E2D8] px-4 py-2.5">
        <h2 className="text-sm font-semibold text-card-foreground">{title}</h2>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Empty-state text. */
export function Empty({ text }: { text: string }) {
  return (
    <div className="flex items-center justify-center rounded-xl border border-dashed border-[#E8E2D8] bg-[#F5F1E8]/60 px-4 py-6 text-sm text-muted-foreground">
      {text}
    </div>
  );
}
