import { useRef, MouseEvent, ReactNode } from "react";

/**
 * SpotlightCard — card with a cursor-following radial spotlight (Framer
 * pricing-card effect). Wrap any card content.
 *
 *   <SpotlightCard className="p-6">
 *     <h3>Feature</h3>
 *     <p>…</p>
 *   </SpotlightCard>
 */
export function SpotlightCard({
  children,
  className = "",
  spotlightColor = "hsl(var(--primary) / 0.12)",
}: {
  children: ReactNode;
  className?: string;
  spotlightColor?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  const handleMove = (e: MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--spot-x", `${e.clientX - rect.left}px`);
    el.style.setProperty("--spot-y", `${e.clientY - rect.top}px`);
  };

  return (
    <div
      ref={ref}
      onMouseMove={handleMove}
      className={`group relative overflow-hidden rounded-xl border bg-card transition-colors hover:border-primary/40 ${className}`}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
        style={{
          background: `radial-gradient(320px circle at var(--spot-x, 50%) var(--spot-y, 50%), ${spotlightColor}, transparent 70%)`,
        }}
      />
      <div className="relative z-10 h-full">{children}</div>
    </div>
  );
}
