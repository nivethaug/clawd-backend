import { useState } from "react";
import { PAGES } from "./pages";
import { DashboardBackground } from "./components/DashboardBackground";
import { ActiveBadge } from "./components/ui";

/** DreamAgent mark (inline SVG, no assets). */
function LogoMark() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#168F86] shadow-soft">
      <svg viewBox="0 0 24 24" className="h-4 w-4 text-white" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="5" y="8" width="14" height="11" rx="3" />
        <circle cx="10" cy="13" r="1" fill="currentColor" />
        <circle cx="14" cy="13" r="1" fill="currentColor" />
        <path d="M12 8V5" />
        <circle cx="12" cy="4" r="1" fill="currentColor" />
      </svg>
    </div>
  );
}

/**
 * Agent dashboard shell — fits ONE viewport, no page scroll.
 * Fixed-height column: compact header row → main (flex-1, internal scrolls)
 * → slim footer. Sections scroll within their columns instead of the page.
 */
export default function App() {
  const [current, setCurrent] = useState(PAGES[0].name);
  const page = PAGES.find((p) => p.name === current) ?? PAGES[0];
  const Page = page.component;

  return (
    <div className="relative h-screen overflow-hidden">
      <DashboardBackground />

      <div className="relative z-10 flex h-full flex-col">
        {/* Compact top row — logo | divider | title + subtitle | badge */}
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-3 gap-y-1 px-4 pt-3 sm:px-6">
          <LogoMark />
          <div className="hidden h-7 w-px bg-[#E8E2D8] sm:block" />
          <div className="min-w-0 leading-tight">
            <h1 className="text-base font-bold tracking-tight sm:text-lg">Agent Dashboard</h1>
            <p className="text-xs text-muted-foreground">
              Monitor, schedule, and automate your agent jobs
            </p>
          </div>
          {PAGES.length > 1 && (
            <nav className="flex gap-1 overflow-x-auto">
              {PAGES.map((p) => (
                <button
                  key={p.name}
                  onClick={() => setCurrent(p.name)}
                  className={`whitespace-nowrap rounded-full px-3 py-1 text-sm font-medium transition-colors duration-200 ${
                    p.name === page.name
                      ? "bg-[#A8DCC0]/35 text-[#0F6B63]"
                      : "text-muted-foreground hover:bg-[#A8DCC0]/15 hover:text-foreground"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </nav>
          )}
          <div className="ml-auto">
            <ActiveBadge />
          </div>
        </div>

        <main className="mx-auto w-full max-w-7xl min-h-0 flex-1 px-4 pb-1 pt-3 sm:px-6">
          <Page />
        </main>

        {/* Slim footer */}
        <footer className="pb-1.5 text-center text-[11px] text-muted-foreground">
          Powered by <span className="font-semibold text-foreground">DreamAgent</span> · updates every 15s
        </footer>
      </div>
    </div>
  );
}
