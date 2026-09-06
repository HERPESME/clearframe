import { useState } from "react";
import { Uploader } from "./Uploader";
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

/**
 * Where you land: everything you have analysed, then the way to add more.
 *
 * The productions list was always fetched and all but the first row thrown
 * away, so there was no way back to an earlier analysis — the app dropped you
 * into whichever one was newest and that was the whole navigation model.
 */
export function Dashboard({
  productions,
  onOpen,
  onDemo,
  onStarted,
  onLedger,
  demoMode,
}: {
  productions: ProductionSummary[];
  onOpen: (pid: string) => void;
  onDemo: () => void;
  onStarted: (pid: string) => void;
  onLedger: (n: number) => void;
  demoMode: boolean;
}) {
  const hasDemo = productions.some((p) => p.id === "demo");

  return (
    <div className="dash">
      <header className="dash-hero">
        <div className="dash-hero-art" aria-hidden="true" />
        <div className="dash-hero-copy">
          <div className="brand">
            CLEAR<b>FRAME</b>
          </div>
          {demoMode && (
            <span
              className="mode-chip"
              title="Replays recorded Gemini/Parallel responses through the identical pipeline code path — live mode swaps only the two API clients."
            >
              DEMO MODE · recorded fixtures, identical code path
            </span>
          )}
          <h1>
            Every frame, <em>cleared.</em>
          </h1>
          <p>
            Gemini watches the footage and finds everything that needs legal
            clearance. Parallel researches who owns it. You make the call — with
            evidence attached.
          </p>
        </div>
      </header>

      <section className="dash-section">
        <div className="dash-section-head">
          <h2>Your productions</h2>
          <span className="dash-count">
            {productions.length} {productions.length === 1 ? "analysis" : "analyses"}
          </span>
        </div>

        <div className="rail">
          {productions.map((p) => {
            const done = stagesDone(p.stage_status);
            return (
              <button
                key={p.id}
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
          })}

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
        </div>
      </section>

      <section className="dash-section">
        <div className="dash-section-head">
          <h2>Clear something new</h2>
        </div>
        <Uploader onStarted={onStarted} onLedger={onLedger} />
      </section>
    </div>
  );
}
