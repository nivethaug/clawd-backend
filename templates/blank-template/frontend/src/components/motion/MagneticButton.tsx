import { useRef, ReactNode, MouseEvent } from "react";

/**
 * MagneticButton — button/link that gently follows the cursor (Framer
 * signature interaction). Renders an <a> when `href` is given, else <button>.
 *
 *   <MagneticButton href="/signup">Get started</MagneticButton>
 *   <MagneticButton onClick={fn} variant="ghost">Learn more</MagneticButton>
 *
 * `strength` (default 0.3) tunes the pull; 0 disables the effect.
 */
export function MagneticButton({
  children,
  href,
  onClick,
  variant = "primary",
  strength = 0.3,
  className = "",
}: {
  children: ReactNode;
  href?: string;
  onClick?: () => void;
  variant?: "primary" | "ghost";
  strength?: number;
  className?: string;
}) {
  const ref = useRef<HTMLElement | null>(null);

  const handleMove = (e: MouseEvent) => {
    const el = ref.current;
    if (!el || strength === 0) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const rect = el.getBoundingClientRect();
    const x = e.clientX - rect.left - rect.width / 2;
    const y = e.clientY - rect.top - rect.height / 2;
    el.style.transform = `translate(${x * strength}px, ${y * strength}px)`;
  };

  const handleLeave = () => {
    const el = ref.current;
    if (el) el.style.transform = "translate(0, 0)";
  };

  const base =
    "inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-semibold transition-[transform,background-color,box-shadow] duration-300 ease-out will-change-transform motion-reduce:transform-none";
  const styles =
    variant === "primary"
      ? "bg-primary text-primary-foreground shadow-glow hover:shadow-glow-lg"
      : "border bg-background/60 backdrop-blur text-foreground hover:bg-accent";

  const props = {
    ref: ref as never,
    onMouseMove: handleMove,
    onMouseLeave: handleLeave,
    className: `${base} ${styles} ${className}`,
  };

  return href ? (
    <a href={href} {...props}>
      {children}
    </a>
  ) : (
    <button type="button" onClick={onClick} {...props}>
      {children}
    </button>
  );
}
