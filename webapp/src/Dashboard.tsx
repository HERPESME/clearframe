import { useState } from "react";
import { Uploader, LedgerPanel } from "./Uploader";
import type { ProductionSummary } from "./types";

const STAGES = 13;

function stagesDone(status: Record<string, string> | undefined): number {
  return Object.values(status ?? {}).filter((v) => v === "complete").length;
}

function ago(updatedAt: number): string {
  const secs = Math.max(0, Date.now() / 1000 - updatedAt);
  if (secs < 90) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/**
 * The poster for one production: a frame of its OWN footage.
 *
 * Not stock art and not a studio poster. This is a rights-clearance tool, so
 * decorating it with somebody else's marketing images would be a poor joke at
 * its own expense — and the honest picture is more useful anyway, because the
 * server picks the moment the first finding appears.
 *
 * The server answers 404 when there is no footage or no extractable frame, so
 * the fallback is drawn here rather than shipped as a placeholder file.
 */
function Poster({ p }: { p: ProductionSummary }) {
  const [failed, setFailed] = useState(false);
  const seed = [...p.id].reduce((a, c) => a + c.charCodeAt(0), 0);

  if (!failed) {
    return (
      <img
        className="poster-img"
        src={`/api/productions/${p.id}/thumbnail?v=${p.updated_at}`}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <svg className="poster-img" viewBox="0 0 200 300" preserveAspectRatio="none"
         aria-hidden="true">
      <defs>
        <linearGradient id={`pg-${p.id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.5} />
          <stop offset="100%" stopColor="var(--accent-2)" stopOpacity={0.28} />
        </linearGradient>
      </defs>
      <rect width="200" height="300" fill={`url(#pg-${p.id})`} />
      {[...Array(9)].map((_, i) => (
        <rect key={i} x={5} y={8 + i * 33} width={12} height={12} rx={2}
              fill="var(--bg)" opacity={0.5} />
      ))}
      {[...Array(9)].map((_, i) => (
        <rect key={`r${i}`} x={183} y={8 + i * 33} width={12} height={12} rx={2}
              fill="var(--bg)" opacity={0.5} />
      ))}
      <circle cx={100} cy={140} r={34 + (seed % 12)} fill="none"
              stroke="var(--ink)" strokeWidth={1.5} opacity={0.5} />
    </svg>
  );
}

function PosterCard({ p, onOpen }: { p: ProductionSummary; onOpen: (pid: string) => void }) {
  const done = stagesDone(p.stage_status);
  return (
    <button
      type="button"
      className="poster-card"
      onClick={() => onOpen(p.id)}
      title={`Open ${p.title}`}
    >
      <div className="poster-frame">
        <Poster p={p} />
        <div className="poster-shade" />
        {p.running && <span className="poster-badge live">analysing</span>}
        {p.interrupted && (
          <span
            className="poster-badge warn"
            title="The server restarted mid-run; these are the stages it reached."
          >
            interrupted
          </span>
        )}
        <div className="poster-meta">
          <div className="poster-title">{p.title}</div>
          <div className="poster-sub">
            {done >= STAGES ? "complete" : `${done}/${STAGES} stages`}
            {" · "}
            {ago(p.updated_at)}
          </div>
        </div>
      </div>
    </button>
  );
}

/* Sidebar icons — 20px, stroke-drawn, one concept each. */
const ICONS = {
  overview: (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="2.5" y="2.5" width="6.5" height="6.5" rx="1.5" />
      <rect x="11" y="2.5" width="6.5" height="6.5" rx="1.5" />
      <rect x="2.5" y="11" width="6.5" height="6.5" rx="1.5" />
      <rect x="11" y="11" width="6.5" height="6.5" rx="1.5" />
    </svg>
  ),
  scan: (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="2.5" y="4.5" width="15" height="11" rx="2" />
      <path d="M8.5 8l4 2-4 2z" fill="currentColor" stroke="none" />
    </svg>
  ),
  library: (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <rect x="3" y="3" width="14" height="14" rx="2" />
      <path d="M3 6.5h14M6.5 3v3.5M13.5 3v3.5M3 13.5h14M6.5 17v-3.5M13.5 17v-3.5" />
    </svg>
  ),
  ledger: (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 3v14M4 5.5h12" />
      <path d="M6 5.5L3.5 10a2.5 2.5 0 0 0 5 0L6 5.5zM14 5.5L11.5 10a2.5 2.5 0 0 0 5 0L14 5.5z" />
    </svg>
  ),
  how: (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <circle cx="10" cy="10" r="7.5" />
      <path d="M8 8a2 2 0 1 1 2.6 1.9c-.6.2-.6.7-.6 1.3" />
      <circle cx="10" cy="14" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  ),
};

type View = "overview" | "library" | "new" | "ledger" | "how";

const NAV: { id: View; label: string; icon: keyof typeof ICONS }[] = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "library", label: "Your library", icon: "library" },
  { id: "new", label: "New analysis", icon: "scan" },
  { id: "ledger", label: "Rights ledger", icon: "ledger" },
  { id: "how", label: "How it works", icon: "how" },
];

const BAND_LEGEND: [string, string][] = [
  ["CRITICAL", "Identified holder, enforcement history, prominent use — act before delivery."],
  ["HIGH", "A real counterparty with a real claim. Budget a licence or a fix."],
  ["MEDIUM", "Defensible with documentation. The dossier carries the argument."],
  ["LOW", "Incidental or protected. Recorded so the insurer sees you looked."],
];

const EXPORTS: [string, string][] = [
  ["E&O clearance dossier", "HTML and Word, with every citation — the document insurers ask for."],
  ["EDL markers", "Every finding at its exact timecode, ready to drop into the edit."],
  ["CSV marker list", "The same findings for a spreadsheet or an asset tracker."],
  ["Music cue sheet", "Every cue with usage and timing, shaped for the PROs."],
  ["Audit trail", "Append-only record of who decided what, and when."],
];

/**
 * The studio floor. Sign-in is the front of house; this is where the work
 * happens — and it is laid out in pages, the way channel studios lay it out,
 * because one endless column with a dead right half is not a layout.
 */
export function Dashboard({
  productions,
  onOpen,
  onDemo,
  onStarted,
  onLedger,
  demoMode,
  account,
}: {
  productions: ProductionSummary[];
  onOpen: (pid: string) => void;
  onDemo: () => void;
  onStarted: (pid: string) => void;
  onLedger: (n: number) => void;
  demoMode: boolean;
  account?: React.ReactNode;
}) {
  const [view, setView] = useState<View>("overview");
  const hasDemo = productions.some((p) => p.id === "demo");
  const running = productions.filter((p) => p.running).length;
  const complete = productions.filter(
    (p) => stagesDone(p.stage_status) >= STAGES,
  ).length;

  return (
    <div className="studio">
      <aside className="studio-side">
        <div className="brand studio-brand">
          CLEAR<b>FRAME</b>
        </div>
        <nav className="studio-nav" aria-label="Dashboard pages">
          {NAV.map((n) => (
            <button
              key={n.id}
              type="button"
              className={view === n.id ? "on" : ""}
              onClick={() => setView(n.id)}
            >
              {ICONS[n.icon]}
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
        <div className="studio-side-foot">
          {demoMode && (
            <span
              className="mode-chip"
              title="Replays recorded Gemini/Parallel responses through the identical pipeline code path — live mode swaps only the two API clients."
            >
              Demo mode
            </span>
          )}
          {account}
        </div>
      </aside>

      <div className="studio-main">
        {view === "overview" && (
          <div className="studio-page" key="overview">
            <header className="studio-hero">
              <div className="studio-hero-art" aria-hidden="true" />
              <div className="studio-hero-copy">
                <h1>
                  Every frame, <em>cleared.</em>
                </h1>
                <p>
                  Gemini watches the footage and finds everything that needs
                  legal clearance. Parallel researches who owns it. You make
                  the call — with evidence attached.
                </p>
                <div className="studio-hero-cta">
                  <button type="button" className="cta-main" onClick={() => setView("new")}>
                    Scan new footage
                  </button>
                  <button type="button" className="cta-quiet" onClick={onDemo}>
                    {hasDemo ? "Re-run the demo scene" : "Watch the demo scene"}
                  </button>
                </div>
              </div>
              <div className="studio-stats" aria-label="At a glance">
                <div className="stat">
                  <span className="stat-n">{productions.length}</span>
                  <span className="stat-l">
                    {productions.length === 1 ? "production" : "productions"}
                  </span>
                </div>
                <div className="stat">
                  <span className={`stat-n ${running > 0 ? "hot" : ""}`}>{running}</span>
                  <span className="stat-l">analysing now</span>
                </div>
                <div className="stat">
                  <span className="stat-n">{complete}</span>
                  <span className="stat-l">complete</span>
                </div>
              </div>
            </header>

            <div className="ov-grid">
              <section className="ov-main">
                <div className="dash-section-head">
                  <h2>Continue reviewing</h2>
                  <span className="dash-count">
                    {productions.length}{" "}
                    {productions.length === 1 ? "analysis" : "analyses"}
                  </span>
                  {productions.length > 3 && (
                    <button
                      type="button"
                      className="see-all"
                      onClick={() => setView("library")}
                    >
                      See the whole library
                    </button>
                  )}
                </div>

                <div className="rail">
                  {productions.slice(0, 6).map((p) => (
                    <PosterCard key={p.id} p={p} onOpen={onOpen} />
                  ))}
                  {!hasDemo && (
                    <button type="button" className="poster-card ghost" onClick={onDemo}>
                      <div className="poster-frame">
                        <div className="poster-ghost">
                          <span className="poster-ghost-plus">▸</span>
                          <div className="poster-title">Run the demo scene</div>
                          <div className="poster-sub">Recorded fixtures, no credentials</div>
                        </div>
                      </div>
                    </button>
                  )}
                  <button type="button" className="poster-card ghost" onClick={() => setView("new")}>
                    <div className="poster-frame">
                      <div className="poster-ghost">
                        <span className="poster-ghost-plus">+</span>
                        <div className="poster-title">New analysis</div>
                        <div className="poster-sub">Drop a clip, get a dossier</div>
                      </div>
                    </div>
                  </button>
                </div>
              </section>

              <aside className="ov-side">
                <div className="qa-card glint">
                  <h3>Quick actions</h3>
                  <button type="button" className="qa-btn" onClick={() => setView("new")}>
                    {ICONS.scan}
                    <span>
                      Scan new footage
                      <em>Three passes, every frame</em>
                    </span>
                  </button>
                  <button type="button" className="qa-btn" onClick={onDemo}>
                    {ICONS.library}
                    <span>
                      {hasDemo ? "Re-run the demo scene" : "Run the demo scene"}
                      <em>No credentials, recorded fixtures</em>
                    </span>
                  </button>
                  <button type="button" className="qa-btn" onClick={() => setView("ledger")}>
                    {ICONS.ledger}
                    <span>
                      Load your rights ledger
                      <em>Report covered, not re-priced</em>
                    </span>
                  </button>
                </div>

                <div className="qa-card">
                  <h3>How a clearance runs</h3>
                  <ol className="how-mini">
                    <li>Upload footage and name the release.</li>
                    <li>Agents find, research and argue every element.</li>
                    <li>You decide; the dossier and markers export.</li>
                  </ol>
                  <button type="button" className="qa-link" onClick={() => setView("how")}>
                    Read the full guide
                  </button>
                </div>
              </aside>
            </div>
          </div>
        )}

        {view === "library" && (
          <div className="studio-page" key="library">
            <div className="dash-section-head page-head">
              <h2>Your library</h2>
              <span className="dash-count">
                {productions.length}{" "}
                {productions.length === 1 ? "analysis" : "analyses"}
              </span>
            </div>
            {productions.length === 0 ? (
              <div className="rail-empty">
                <p>
                  Nothing here yet. Scan your first clip, or run the demo scene
                  to see a finished review.
                </p>
                <div className="studio-hero-cta">
                  <button type="button" className="cta-main" onClick={() => setView("new")}>
                    Scan new footage
                  </button>
                  <button type="button" className="cta-quiet" onClick={onDemo}>
                    Run the demo scene
                  </button>
                </div>
              </div>
            ) : (
              <div className="lib-grid">
                {productions.map((p) => (
                  <PosterCard key={p.id} p={p} onOpen={onOpen} />
                ))}
              </div>
            )}
          </div>
        )}

        {view === "new" && (
          <div className="studio-page" key="new">
            <div className="dash-section-head page-head">
              <h2>Clear something new</h2>
              <span className="dash-count">
                the five inputs that decide what a finding scores
              </span>
            </div>
            <Uploader onStarted={onStarted} />
          </div>
        )}

        {view === "ledger" && (
          <div className="studio-page" key="ledger">
            <div className="dash-section-head page-head">
              <h2>Rights you already hold</h2>
              <span className="dash-count">optional, and worth it</span>
            </div>
            <LedgerPanel onLedger={onLedger} />
          </div>
        )}

        {view === "how" && (
          <div className="studio-page" key="how">
            <div className="dash-section-head page-head">
              <h2>How a clearance runs</h2>
            </div>
            <ol className="how-steps">
              <li>
                <span className="how-n">1</span>
                <div>
                  <h3>Upload</h3>
                  <p>
                    Drop footage and say where it will be released. Three
                    independent Gemini passes watch every frame — logos,
                    artwork, tattoos, faces, music, signage.
                  </p>
                </div>
              </li>
              <li>
                <span className="how-n">2</span>
                <div>
                  <h3>Watch the agents work</h3>
                  <p>
                    Every finding is researched — who owns it, how litigious
                    they are, what a licence costs — with source citations
                    attached, and argued against real case law.
                  </p>
                </div>
              </li>
              <li>
                <span className="how-n">3</span>
                <div>
                  <h3>Decide and export</h3>
                  <p>
                    Approve, license, blur or escalate each finding. Export the
                    E&amp;O dossier, EDL markers for the edit and the music cue
                    sheet.
                  </p>
                </div>
              </li>
            </ol>

            <div className="how-grid">
              <div className="band-legend">
                <h3>Reading the risk bands</h3>
                <ul>
                  {BAND_LEGEND.map(([band, line]) => (
                    <li key={band}>
                      <span className={`chip ${band}`}>{band}</span>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="band-legend">
                <h3>What you walk away with</h3>
                <ul className="exports-list">
                  {EXPORTS.map(([name, line]) => (
                    <li key={name}>
                      <strong>{name}</strong>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        )}

        <footer className="studio-foot">
          Content ID finds <em>your</em> IP in other people's video. ClearFrame
          finds <em>other people's</em> IP in yours — before you ship.
        </footer>
      </div>
    </div>
  );
}
