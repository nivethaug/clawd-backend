import { ReactNode } from "react";

/**
 * GradientText — animated gradient text for headlines and accents.
 *
 *   <GradientText as="span">10x faster</GradientText>
 *   <GradientText className="from-primary via-accent to-primary" >…</GradientText>
 *
 * Colors default to primary→accent; override with Tailwind gradient stops.
 * Pass `animate={false}` for a static gradient.
 */
export function GradientText({
  children,
  className = "",
  animate = true,
}: {
  children: ReactNode;
  className?: string;
  animate?: boolean;
}) {
  return (
    <span
      className={`bg-gradient-to-r from-primary via-accent to-primary bg-clip-text text-transparent ${
        animate ? "animate-gradient-pan bg-[length:200%_auto]" : ""
      } ${className}`}
    >
      {children}
    </span>
  );
}
