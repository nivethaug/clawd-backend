/**
 * Orbs — floating gradient orbs background for heroes and feature sections.
 *
 *   <section className="relative overflow-hidden">
 *     <Orbs />
 *     <div className="relative z-10">…content…</div>
 *   </section>
 *
 * Keep the parent `relative overflow-hidden` and content above with z-10.
 * `count` (1-4) and `intensity` ("subtle" | "strong") tune the effect.
 */
export function Orbs({
  count = 3,
  intensity = "subtle",
}: {
  count?: number;
  intensity?: "subtle" | "strong";
}) {
  const orbs = [
    { top: "-10%", left: "-5%", size: "34rem", color: "bg-primary/25", delay: "0s" },
    { top: "30%", right: "-10%", size: "28rem", color: "bg-accent/20", delay: "-4s" },
    { bottom: "-15%", left: "25%", size: "38rem", color: "bg-primary/15", delay: "-8s" },
    { top: "10%", left: "45%", size: "22rem", color: "bg-accent/10", delay: "-12s" },
  ].slice(0, Math.max(1, Math.min(4, count)));

  const blur = intensity === "strong" ? "blur-3xl" : "blur-3xl opacity-70";

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0">
      {orbs.map((o, i) => (
        <div
          key={i}
          className={`absolute rounded-full mix-blend-screen ${blur} ${o.color} animate-float`}
          style={{
            top: o.top,
            left: o.left,
            right: o.right,
            bottom: o.bottom,
            width: o.size,
            height: o.size,
            animationDelay: o.delay,
          }}
        />
      ))}
    </div>
  );
}
