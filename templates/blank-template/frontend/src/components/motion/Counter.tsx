import { useEffect, useRef, useState } from "react";

/**
 * Counter — number that counts up when scrolled into view (stats rows).
 *
 *   <Counter to={98} suffix="%" />
 *   <Counter to={2500} prefix="$" duration={1.6} />
 *
 * Respects reduced-motion (renders the final value immediately).
 */
export function Counter({
  to,
  from = 0,
  duration = 1.4,
  prefix = "",
  suffix = "",
  decimals = 0,
}: {
  to: number;
  from?: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [value, setValue] = useState(from);
  const started = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(to);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (!e.isIntersecting || started.current) return;
          started.current = true;
          const t0 = performance.now();
          const tick = (t: number) => {
            const p = Math.min((t - t0) / (duration * 1000), 1);
            const eased = 1 - Math.pow(1 - p, 3);
            setValue(from + (to - from) * eased);
            if (p < 1) requestAnimationFrame(tick);
          };
          requestAnimationFrame(tick);
          io.disconnect();
        });
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [to, from, duration]);

  return (
    <span ref={ref} className="tabular-nums">
      {prefix}
      {value.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}
