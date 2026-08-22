import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, setRole } from "./api";
import { ElementCard } from "./ElementCard";
import { MissionControl } from "./MissionControl";
import { Timeline } from "./Timeline";
import { Uploader } from "./Uploader";
import { VideoPlayer } from "./VideoPlayer";
import type { Action, ProductionState, RiskBand, Role } from "./types";

const BANDS: RiskBand[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export default function App() {
  const [state, setState] = useState<ProductionState | null>(null);
  const [mission, setMission] = useState(false);
  const [mode, setMode] = useState<"demo" | "live">("demo");
  const [loading, setLoading] = useState(true);
  const [role, setRoleState] = useState<Role>("legal");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [checking, setChecking] = useState(false);
  const [freshNote, setFreshNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    api.meta().then((m) => setMode(m.mode)).catch(() => {});
    // ?autorun starts a fresh paced pipeline run on load — used for demo
    // recordings so Mission Control opens without a click.
    if (new URLSearchParams(window.location.search).has("autorun")) {
      setLoading(false);
      loadDemo();
      return;
    }
    api
      .listProductions()
      .then(async (list) => {
        if (list.length > 0) setState(await api.getProduction(list[0].id));
      })
      .catch(() => setError("Could not reach the ClearFrame API. Is the server running?"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const changeRole = (r: Role) => {
    setRole(r);
    setRoleState(r);
  };

  // The way back. Without it a loaded production was terminal: the hero only
  // renders when `state` is null, so the upload panel became unreachable and
  // the only escape was reloading the browser.
  const newProduction = () => {
    setState(null);
    setMission(false);
    setShowUpload(true);
    setError(null);
  };

  const loadDemo = async () => {
    setError(null);
    try {
      await api.startPacedDemo(0.45);
      setState(null);
      setArtifacts([]);
      setMission(true);
    } catch {
      setError("Demo production could not be started.");
    }
  };

  const enterReview = async () => {
    try {
      setState(await api.getProduction("demo"));
      setMission(false);
    } catch {
      setError("Could not load the finished production.");
    }
  };

  const onDecide = useCallback(
    async (elementId: string, action: Action, note: string) => {
      if (!state) return;
      setError(null);
      try {
        await api.recordDecision(state.production.id, elementId, action, note);
        setState(await api.getProduction(state.production.id));
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) {
          setError("Editors have read-only access. Switch to Legal or Producer to record decisions.");
        } else {
          setError("Decision could not be saved.");
        }
      }
    },
    [state],
  );

  const checkFreshness = async () => {
    if (!state) return;
    setChecking(true);
    setFreshNote(null);
    setError(null);
    try {
      const r = await api.checkFreshness(state.production.id);
      setState(await api.getProduction(state.production.id));
      setFreshNote(
        r.material_signals > 0
          ? `${r.material_signals} enforcement signal${r.material_signals === 1 ? "" : "s"} across ${r.holders} rights holders`
          : `No new enforcement activity across ${r.holders} rights holders`,
      );
    } catch {
      setError("Live signal check failed.");
    } finally {
      setChecking(false);
    }
  };

  const generate = async () => {
    if (!state) return;
    setError(null);
    try {
      const res = await api.generateDossier(state.production.id);
      setArtifacts(res.artifacts);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("Findings still await review — every element needs a decision first.");
      } else {
        setError("Dossier generation failed.");
      }
    }
  };

  if (loading) {
    return (
      <div className="hero">
        <div className="slate">Loading…</div>
      </div>
    );
  }

  if (mission) {
    return <MissionControl onComplete={enterReview} />;
  }

  if (!state) {
    return (
      <div className="hero">
        <div className="slate">ClearFrame · automated clearance department</div>
        {mode === "demo" && (
          <div className="mode-chip" title="Replays recorded Gemini/Parallel responses through the identical pipeline code path — live mode swaps only the two API clients.">
            DEMO MODE · recorded fixtures, identical code path
          </div>
        )}
        <h1>
          Every frame, <em>cleared.</em>
        </h1>
        <p>
          Gemini watches the footage and finds everything that needs legal clearance.
          Parallel researches who owns it. You make the call — with evidence attached.
        </p>
        <div className="hero-actions">
          <button className="generate" onClick={loadDemo}>
            Run the demo scene
          </button>
          <button className="secondary" onClick={() => setShowUpload((v) => !v)}>
            {showUpload ? "Hide upload" : "Upload my own footage"}
          </button>
        </div>
        {showUpload && (
          <Uploader
            onStarted={() => {
              setState(null);
              setMission(true);
            }}
            onLedger={() => {}}
          />
        )}
        {error && <div className="error-banner">{error}</div>}
      </div>
    );
  }

  const {
    production,
    elements,
    research,
    risk,
    remediation,
    decisions,
    court,
    research_plan,
    routes,
    sponsor_conflicts,
    assessed_exposures,
    platform_outcomes,
    drift,
    candidates,
    watches,
    alerts,
    corroboration,
    freshness,
    territory_risk,
    territories,
    coverage,
  } = state;
  const unscriptedIds = new Set(drift?.unscripted_element_ids ?? []);
  const sorted = [...elements].sort((a, b) => risk[b.id].score - risk[a.id].score);
  const pending = elements.filter((el) => !decisions[el.id]);
  const disputed = elements.filter(
    (el) => corroboration?.[el.id]?.verdict === "CONFLICTED",
  );
  // FINGERPRINTED is a stronger verdict than CORROBORATED, not a separate
  // outcome — both mean a second, independent system confirmed identity.
  const corroborated = elements.filter((el) => {
    const v = corroboration?.[el.id]?.verdict;
    return v === "CORROBORATED" || v === "FINGERPRINTED";
  });
  const isDemo = production.id === "demo";
  const byId = Object.fromEntries(elements.map((el) => [el.id, el]));
  // Only the outcomes a platform would actually act on automatically. The
  // manual-complaint rows are real but far less likely, and putting them in a
  // banner would train the reader to ignore it.
  const claimed = (platform_outcomes ?? []).filter(
    (o) => o.action === "CLAIM_LIKELY" || o.action === "CLAIM_POSSIBLE",
  );
  const covCount = (s: string) =>
    elements.filter((el) => coverage?.[el.id]?.status === s).length;
  const materialSignals = Object.values(freshness ?? {})
    .flat()
    .filter((s) => s.material).length;
  const bandCounts = Object.fromEntries(
    BANDS.map((b) => [b, elements.filter((el) => risk[el.id].band === b).length]),
  );

  const jumpTo = (id: string) => {
    setActiveId(id);
    const el = elements.find((e) => e.id === id);
    if (el && videoRef.current && production.has_media) {
      // land a beat before the element appears so the box is already on screen
      videoRef.current.currentTime = Math.max(el.time_ranges[0].start_s - 0.25, 0);
    }
    cardRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <>
      <header className="topbar">
        <button
          className="brand brand-home"
          onClick={newProduction}
          title="Back to the start — clear this production and choose another"
        >
          CLEAR<b>FRAME</b>
        </button>
        {mode === "demo" && (
          <span
            className="mode-chip"
            title="Recorded fixtures replayed through the identical pipeline code path."
          >
            DEMO
          </span>
        )}
        <span className="prod-title">“{production.title}”</span>
        <span className="prod-meta">
          {production.duration_s.toFixed(0)}s · {production.fps}fps · {elements.length}{" "}
          findings
        </span>
        <span className="spacer" />
        <nav className="roles" aria-label="Reviewer role">
          {(["legal", "producer", "editor"] as Role[]).map((r) => (
            <button
              key={r}
              className={role === r ? "active" : ""}
              onClick={() => changeRole(r)}
            >
              {r}
            </button>
          ))}
        </nav>
        <span className="role-hint">
          {role === "editor" ? "read-only" : "can record decisions"}
        </span>
        <button
          className="roles"
          style={{ padding: "5px 12px", background: "transparent", color: "var(--muted)" }}
          onClick={newProduction}
          title="Clear this production and upload another"
        >
          + New
        </button>
        {isDemo && (
          <button
            className="roles"
            style={{ padding: "5px 12px", background: "transparent", color: "var(--muted)" }}
            onClick={loadDemo}
            title="Run the demo pipeline again from scratch"
          >
            Re-run demo
          </button>
        )}
      </header>

      {production.has_media && (
        <VideoPlayer
          ref={videoRef}
          pid={production.id}
          elements={elements}
          risk={risk}
          corroboration={corroboration ?? {}}
          coverage={coverage ?? {}}
          fps={production.fps}
          activeId={activeId}
          onPick={jumpTo}
        />
      )}

      <Timeline
        elements={sorted}
        risk={risk}
        durationS={production.duration_s}
        fps={production.fps}
        activeId={activeId}
        onJump={jumpTo}
      />

      {error && <div className="error-banner">{error}</div>}

      {(alerts ?? []).length > 0 && (
        <div className="alert-banner">
          ⚠ Standing watch alert — review reopened.{" "}
          {alerts.map((a, i) => (
            <span key={i}>
              <strong>{elements.find((el) => el.id === a.element_id)?.label}</strong>:{" "}
              {a.summary}{" "}
              {a.source_url && <a href={a.source_url}>[source]</a>}
            </span>
          ))}
        </div>
      )}

      <div className="summary">
        {BANDS.map((b) =>
          bandCounts[b] > 0 ? (
            <span className={`chip ${b}`} key={b}>
              <span className="n">{bandCounts[b]}</span> {b}
            </span>
          ) : null,
        )}
        <span className="chip">
          <span className="n">
            {elements.filter((el) => !research[el.id] || research[el.id].status !== "complete").length}
          </span>{" "}
          research incomplete
        </span>
        <span className="chip">
          <span className="n">{pending.length}</span> awaiting decision
        </span>
        {covCount("COVERED") > 0 && (
          <span className="chip ok" title="Already licensed — a matching grant is on file in the rights ledger.">
            <span className="n">{covCount("COVERED")}</span> already licensed
          </span>
        )}
        {covCount("PARTIAL") > 0 && (
          <span className="chip HIGH" title="A licence exists but does not reach this use — territory, term or media gap.">
            <span className="n">{covCount("PARTIAL")}</span> licence gaps
          </span>
        )}
        {covCount("NOT_COVERED") > 0 && (
          <span className="chip CRITICAL" title="Rights holder identified, but no licence on file.">
            <span className="n">{covCount("NOT_COVERED")}</span> unlicensed
          </span>
        )}
        {(sponsor_conflicts?.length ?? 0) > 0 && (
          <span
            className="chip HIGH"
            title="A competitor's mark is on screen while a sponsor is paying. Not an infringement — a contract exposure, since category exclusivity is standard in brand deals."
          >
            <span className="n">{sponsor_conflicts.length}</span> sponsor conflict
            {sponsor_conflicts.length === 1 ? "" : "s"}
          </span>
        )}
        {claimed.length > 0 && (
          <span
            className="chip CRITICAL"
            title="The platform will match this automatically on upload. Content ID does not evaluate fair use."
          >
            <span className="n">{claimed.length}</span> platform claim
            {claimed.length === 1 ? "" : "s"}
          </span>
        )}
        {corroborated.length > 0 && (
          <span
            className="chip ok"
            title="A second, independent detector confirmed these identifications."
          >
            <span className="n">{corroborated.length}</span> ID corroborated
          </span>
        )}
        {disputed.length > 0 && (
          <span
            className="chip CRITICAL"
            title="Detectors disagree on what these elements are. Research is blocked until a human resolves identity."
          >
            <span className="n">{disputed.length}</span> ID disputed
          </span>
        )}
        {materialSignals > 0 && (
          <span
            className="chip HIGH"
            title="Enforcement activity found by the live Parallel Search pass."
          >
            <span className="n">{materialSignals}</span> live enforcement signals
          </span>
        )}
        {drift && drift.unscripted_element_ids.length > 0 && (
          <span className="chip HIGH">
            <span className="n">{drift.unscripted_element_ids.length}</span> not in script
          </span>
        )}
        {(territories ?? []).length > 0 && (
          <span
            className="chip"
            title="Clearance is jurisdictional — each finding is banded per release territory."
          >
            territories: <span className="n">{territories.join(" · ")}</span>
          </span>
        )}
        {Object.keys(watches ?? {}).length > 0 && (
          <span className="chip">
            <span className="n">{Object.keys(watches).length}</span> standing watches
          </span>
        )}
      </div>

      <main className="cards">
        {claimed.length > 0 && (
          <div className="platform-banner">
            <strong>Platform enforcement — {claimed[0].platform}.</strong> Separate from
            legal merit: automated content matching does not evaluate fair use, so a
            finding with a strong legal defence can still be claimed on upload.
            <ul>
              {claimed.map((o) => (
                <li key={o.element_id}>
                  <span className="chip CRITICAL">{o.action.replace(/_/g, " ")}</span>{" "}
                  {byId[o.element_id]?.label ?? o.element_id} — <em>{o.remedy}</em>
                  {o.revenue_impact && <> {o.revenue_impact}</>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {(assessed_exposures?.length ?? 0) > 0 && (
          <div className="exposure-banner">
            <strong>On-screen exposure.</strong> None of this is intellectual property
            and nobody owns any of it — which is exactly why it gets missed. Severity is
            set by the strictest release territory, because a publication cannot be
            un-made in one country and left standing in another.
            <ul>
              {assessed_exposures.map((x) => (
                <li key={x.id}>
                  <span className={`chip ${x.band}`}>{x.band}</span> {x.description}{" "}
                  <em>{x.remedy}</em>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(sponsor_conflicts?.length ?? 0) > 0 && (
          <div className="sponsor-banner">
            <strong>Sponsor conflict.</strong> A competitor's mark is on screen while a
            sponsor is paying for this production. Nothing is being infringed — but
            category exclusivity is standard in sponsorship contracts, so this can breach
            the deal even though the depiction is lawful. Check the exclusivity clause
            before delivery.
            <ul>
              {sponsor_conflicts.map((c) => (
                <li key={c.element_id}>
                  {c.label} ({c.detected_owner}) competes with {c.conflicts_with} in{" "}
                  {c.sector}
                </li>
              ))}
            </ul>
          </div>
        )}
        {sorted.map((el) => (
          <ElementCard
            key={el.id}
            element={el}
            research={research[el.id]}
            risk={risk[el.id]}
            options={remediation[el.id] ?? []}
            decision={decisions[el.id]}
            court={court?.[el.id]}
            plan={research_plan?.[el.id]}
            route={routes?.[el.id]}
            corroboration={corroboration?.[el.id]}
            coverage={coverage?.[el.id]}
            freshness={freshness?.[el.id] ?? []}
            territory={territory_risk?.[el.id] ?? []}
            unscripted={unscriptedIds.has(el.id)}
            candidates={candidates?.[el.id] ?? []}
            fps={production.fps}
            role={role}
            onDecide={onDecide}
            cardRef={(node) => {
              cardRefs.current[el.id] = node;
            }}
            onHover={() => setActiveId(el.id)}
          />
        ))}
      </main>

      <footer className="bottombar">
        {artifacts.length === 0 ? (
          <>
            <span className="pending-note">
              {pending.length === 0
                ? "All findings reviewed."
                : `${pending.length} finding${pending.length === 1 ? "" : "s"} await review.`}
            </span>
            {freshNote && <span className="fresh-note">{freshNote}</span>}
            <span className="spacer" />
            <button
              className="secondary"
              onClick={checkFreshness}
              disabled={checking}
              title="Runs a live Parallel Search over every identified rights holder — deep research is a snapshot, this is right now."
            >
              {checking ? "Checking…" : "Check live signals"}
            </button>
            <button className="generate" disabled={pending.length > 0} onClick={generate}>
              Generate clearance dossier
            </button>
          </>
        ) : (
          <>
            <span className="pending-note">Dossier generated:</span>
            <div className="artifacts">
              {artifacts.map((name) => (
                <a
                  key={name}
                  href={api.artifactUrl(production.id, name)}
                  target="_blank"
                  rel="noreferrer"
                >
                  {name}
                </a>
              ))}
            </div>
          </>
        )}
      </footer>
    </>
  );
}
