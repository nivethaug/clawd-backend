import { useEffect, useRef, useState, ReactNode, ElementType } from "react";

/**
 * Reveal — scroll-triggered entrance animation (Framer-style, zero deps).
 *
 * Wraps any content; fades/slides it in when it scrolls into view.
 * Use `delay` for staggered children (0.1 steps look best).
 *
 *   <Reveal><h1>…</h1></Reveal>
 *   <Reveal delay={0.1}><Card /></Reveal>
 *   <Reveal variant="scale">…</Reveal>   // fade-up | fade | slide-left | slide-right | scale
 */
type Variant = "fade-up" | "fade" | "slide-left" | "slide-right" | "scale";

const VARIANT_CLASS: Record<Variant, string> = {
  "fade-up": "opacity-0 translate-y-8",
  fade: "opacity-0",
  "slide-left": "opacity-0 translate-x-8",
  "slide-right": "opacity-0 -translate-x-8",
  scale: "opacity-0 scale-95",
};

export function Reveal({
  children,
  delay = 0,
  variant = "fade-up",
  as: Tag = "div",
  className = "",
}: {
  children: ReactNode;
  delay?: number;
  variant?: Variant;
  as?: ElementType;
  className?: string;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            setShown(true);
            io.disconnect();
          }
        });
      },
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <Tag
      ref={ref}
      style={{ transitionDelay: `${delay}s` }}
      className={`transition-all duration-700 ease-out will-change-transform ${
        shown ? "opacity-100 translate-x-0 translate-y-0 scale-100" : VARIANT_CLASS[variant]
      } ${className}`}
    >
      {children}
    </Tag>
  );
}
