import {
  Reveal,
  GradientText,
  Orbs,
  Marquee,
  MagneticButton,
  Counter,
  SpotlightCard,
} from "@/components/motion";

/**
 * Welcome — the template's living example page.
 *
 * This is a REFERENCE COMPOSITION of the design system (components/motion):
 * hero → marquee → stats → feature cards. The AI replaces this content with
 * the real site but should KEEP THE PATTERNS: font-display headlines,
 * GradientText accents, Reveal stagger (0.1 steps), Orbs behind heroes,
 * SpotlightCards for feature grids, Counters for stats.
 */
export default function Welcome() {
  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* ── HERO ── parent relative + overflow-hidden, Orbs behind, content z-10 */}
      <section className="relative flex min-h-[90vh] items-center justify-center overflow-hidden px-4">
        <Orbs />
        <div className="relative z-10 mx-auto max-w-3xl text-center">
          <Reveal variant="fade">
            <span className="inline-flex items-center gap-2 rounded-full border bg-card/60 px-4 py-1.5 text-xs font-medium text-muted-foreground backdrop-blur">
              ✦ Template starter
            </span>
          </Reveal>
          <Reveal delay={0.1}>
            <h1 className="mt-6 font-display text-5xl font-bold leading-[1.05] sm:text-6xl">
              Ship something people
              <br />
              <GradientText>actually remember</GradientText>
            </h1>
          </Reveal>
          <Reveal delay={0.2}>
            <p className="mx-auto mt-6 max-w-xl text-lg text-muted-foreground">
              This starter ships with a motion design system — scroll reveals,
              gradient text, magnetic buttons, spotlight cards. Replace the
              words, keep the craft.
            </p>
          </Reveal>
          <Reveal delay={0.3} className="mt-8 flex items-center justify-center gap-4">
            <MagneticButton href="#features">Get started</MagneticButton>
            <MagneticButton href="#features" variant="ghost">
              Learn more
            </MagneticButton>
          </Reveal>
        </div>
      </section>

      {/* ── MARQUEE strip ── */}
      <section className="border-y bg-card/40 py-6">
        <Marquee items={["Scroll reveals", "Gradient text", "Magnetic buttons", "Spotlight cards", "Animated counters", "Reduced-motion safe"]} />
      </section>

      {/* ── STATS ── Counter animates when scrolled into view */}
      <section className="mx-auto max-w-5xl px-4 py-20">
        <div className="grid grid-cols-1 gap-8 text-center sm:grid-cols-3">
          {[
            { to: 7, suffix: "", label: "Motion primitives" },
            { to: 0, suffix: "", label: "Extra dependencies" },
            { to: 60, suffix: "fps", label: "GPU-friendly CSS" },
          ].map((s, i) => (
            <Reveal key={s.label} delay={i * 0.1}>
              <div className="font-display text-5xl font-bold">
                <Counter to={s.to} suffix={s.suffix} />
              </div>
              <div className="mt-2 text-sm text-muted-foreground">{s.label}</div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ── FEATURES ── SpotlightCard grid with staggered reveals */}
      <section id="features" className="mx-auto max-w-5xl px-4 pb-24">
        <Reveal>
          <h2 className="font-display text-3xl font-bold sm:text-4xl">
            Built-in <GradientText animate={false}>interactions</GradientText>
          </h2>
        </Reveal>
        <div className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-3">
          {[
            {
              title: "Reveal on scroll",
              body: "IntersectionObserver-driven entrances with staggered delays — content slides in as you scroll.",
            },
            {
              title: "Cursor spotlight",
              body: "Cards track the pointer with a soft radial glow — the Framer pricing-card effect.",
            },
            {
              title: "Magnetic pull",
              body: "Primary buttons lean toward the cursor and snap back — subtle, premium, delightful.",
            },
          ].map((f, i) => (
            <Reveal key={f.title} delay={i * 0.1}>
              <SpotlightCard className="h-full p-6">
                <h3 className="font-display text-lg font-semibold">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{f.body}</p>
              </SpotlightCard>
            </Reveal>
          ))}
        </div>
      </section>
    </div>
  );
}
