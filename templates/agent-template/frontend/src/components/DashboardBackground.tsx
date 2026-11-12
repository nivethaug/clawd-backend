/**
 * DashboardBackground — minimal, crisp, zero assets.
 *
 * Flat ivory page with quiet accents (per the "keep it simple" spec):
 *   1. A soft sage wave band hugging the bottom edge (pure CSS gradients)
 *   2. Two mascots flanking the content, vertically centered:
 *      left = classic bot · right = female bot (lashes, blush, pink accents)
 *      Both appear only on wide viewports where side margins exist.
 *
 * Everything else stays clean so the dashboard owns the full viewport.
 * Motion respects prefers-reduced-motion.
 */

function MaleBot({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 200 200" className={`animate-bob-robot select-none ${className}`} aria-hidden>
      <line x1="100" y1="40" x2="100" y2="24" stroke="#202522" strokeWidth="3" strokeLinecap="round" />
      <circle cx="100" cy="20" r="6.5" fill="#4FD1C5" opacity="0.9" />
      <rect x="42" y="64" width="11" height="24" rx="5.5" fill="#A8DCC0" />
      <rect x="147" y="64" width="11" height="24" rx="5.5" fill="#A8DCC0" />
      <ellipse cx="100" cy="80" rx="54" ry="47" fill="#FFFDF7" stroke="#E4E0D4" strokeWidth="2.5" />
      <rect x="60" y="56" width="80" height="48" rx="24" fill="#1C2836" />
      <path d="M82 78 q5 -9 10 0" stroke="#4FD1C5" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M108 78 q5 -9 10 0" stroke="#4FD1C5" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path
        d="M66 130 h68 a12 12 0 0 1 12 12 v10 a18 18 0 0 1 -18 18 H72 a18 18 0 0 1 -18 -18 v-10 a12 12 0 0 1 12 -12 z"
        fill="#FFFDF7" stroke="#E4E0D4" strokeWidth="2.5"
      />
      <circle cx="100" cy="149" r="8" fill="#A8DCC0" />
      <ellipse cx="100" cy="183" rx="33" ry="7" fill="none" stroke="#4FD1C5" strokeWidth="3.5" opacity="0.6" />
    </svg>
  );
}

function FemaleBot({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 200 210" className={`animate-bob-robot-f select-none ${className}`} aria-hidden>
      {/* antenna with simple pink tip */}
      <line x1="100" y1="42" x2="100" y2="26" stroke="#202522" strokeWidth="3" strokeLinecap="round" />
      <circle cx="100" cy="22" r="6.5" fill="#F3A8C0" opacity="0.95" />
      {/* ears */}
      <rect x="42" y="66" width="11" height="24" rx="5.5" fill="#F3C4D4" />
      <rect x="147" y="66" width="11" height="24" rx="5.5" fill="#F3C4D4" />
      {/* head — slightly rounder */}
      <ellipse cx="100" cy="82" rx="56" ry="50" fill="#FFFDF7" stroke="#E4E0D4" strokeWidth="2.5" />
      {/* face */}
      <rect x="60" y="58" width="80" height="48" rx="24" fill="#1C2836" />
      {/* eyes with lashes */}
      <path d="M80 80 q5 -9 10 0" stroke="#4FD1C5" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M110 80 q5 -9 10 0" stroke="#4FD1C5" strokeWidth="4" fill="none" strokeLinecap="round" />
      <line x1="81" y1="73" x2="78" y2="69" stroke="#4FD1C5" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="90" y1="71" x2="89" y2="67" stroke="#4FD1C5" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="110" y1="71" x2="111" y2="67" stroke="#4FD1C5" strokeWidth="2.5" strokeLinecap="round" />
      <line x1="119" y1="73" x2="122" y2="69" stroke="#4FD1C5" strokeWidth="2.5" strokeLinecap="round" />
      {/* body */}
      <path
        d="M66 132 h68 a12 12 0 0 1 12 12 v10 a18 18 0 0 1 -18 18 H72 a18 18 0 0 1 -18 -18 v-10 a12 12 0 0 1 12 -12 z"
        fill="#FFFDF7" stroke="#E4E0D4" strokeWidth="2.5"
      />
      <circle cx="100" cy="151" r="8" fill="#F3A8C0" />
      {/* hover ring */}
      <ellipse cx="100" cy="185" rx="33" ry="7" fill="none" stroke="#F3A8C0" strokeWidth="3.5" opacity="0.6" />
    </svg>
  );
}

export function DashboardBackground() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* Soft sage wave band along the bottom (pure gradients — always crisp) */}
      <div
        className="absolute inset-x-0 bottom-0 h-[24vh]"
        style={{
          background:
            "radial-gradient(120% 130% at 8% 100%, hsl(151 43% 76% / 0.45) 0%, hsl(151 43% 80% / 0.22) 42%, transparent 70%)," +
            "radial-gradient(90% 110% at 78% 108%, hsl(176 45% 82% / 0.30) 0%, transparent 65%)",
        }}
      />
      {/* Classic bot — left margin, vertically centered (xl+ viewports) */}
      <div className="absolute left-3 top-1/2 hidden -translate-y-1/2 xl:block 2xl:left-8">
        <MaleBot className="h-32 w-32 opacity-95 2xl:h-40 2xl:w-40" />
      </div>
      {/* Female bot — right margin, vertically centered (xl+ viewports) */}
      <div className="absolute right-3 top-1/2 hidden -translate-y-1/2 xl:block 2xl:right-8">
        <FemaleBot className="h-32 w-32 opacity-95 2xl:h-40 2xl:w-40" />
      </div>
    </div>
  );
}
