import { ReactNode } from "react";

/**
 * Marquee — infinite horizontal scroller for logos, tags, or content rows.
 *
 *   <Marquee items={["Fast", "Secure", "Modern"]} />
 *   <Marquee>{customNodes}</Marquee>
 *
 * Items render inside pill spans; children override for custom markup.
 * `reverse` flips direction; `speed` (seconds per loop) tunes pace.
 */
export function Marquee({
  items = [],
  children,
  reverse = false,
  speed = 30,
  className = "",
}: {
  items?: ReactNode[];
  children?: ReactNode;
  reverse?: boolean;
  speed?: number;
  className?: string;
}) {
  const inner = children ?? (
    <>
      {items.map((it, i) => (
        <span
          key={i}
          className="mx-3 inline-flex items-center rounded-full border bg-card px-5 py-2 text-sm font-medium text-card-foreground"
        >
          {it}
        </span>
      ))}
    </>
  );

  return (
    <div className={`group relative overflow-hidden ${className}`}>
      <div
        className="flex w-max items-center"
        style={{
          animation: `marquee ${speed}s linear infinite ${reverse ? "reverse" : ""}`,
        }}
      >
        <div className="flex items-center pr-3 motion-reduce:animate-none">{inner}</div>
        <div className="flex items-center pr-3 motion-reduce:animate-none" aria-hidden>
          {inner}
        </div>
      </div>
      {/* Edge fades */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-background to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-background to-transparent" />
    </div>
  );
}
