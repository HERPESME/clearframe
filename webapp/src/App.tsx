import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, setRole } from "./api";
import { ElementCard } from "./ElementCard";
import { MissionControl } from "./MissionControl";
import { Timeline } from "./Timeline";
import { Uploader } from "./Uploader";
import { SignIn } from "./SignIn";
import { signOut, type SessionUser } from "./auth";
import { VideoPlayer } from "./VideoPlayer";
import type { Action, ProductionState, Risk, RiskBand, Role } from "./types";

const BANDS: RiskBand[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export default function App() {
  const [state, setState] = useState<ProductionState | null>(null);
  const [mission, setMission] = useState<string | null>(null);
  const [mode, setMode] = useState<"demo" | "live">("demo");
  const [loading, setLoading] = useState(true);
  const [role, setRoleState] = useState<Role>("legal");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [checking, setChecking] = useState(false);
  const [freshNote, setFreshNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The upload form is the point of the home screen, so it is open by
  // default rather than hidden behind a second click.
  const [showUpload, setShowUpload] = useState(true);
  const [resuming, setResuming] = useState<string | null>(null);
  // Restored a run that never finished. Distinct from "still analysing": there
  // is no server-side task to wait for, so polling would never end — which is
  // what used to happen, re-rendering this production every three seconds and
  // overwriting the upload form the moment it was opened.
  const [interrupted, setInterrupted] = useState(false);
  // Authentication, when the deployment has it switched on. `null` while we do
  // not yet know, so the app never flashes a sign-in screen at someone who is
  // already signed in — or a review screen at someone who is not.
  const [authOn, setAuthOn] = useState<boolean | null>(null);
  // This deployment lets a visitor choose a role rather than be granted one.
  // A demo has nobody to ask; it must be labelled, never assumed.
  const [openRoles, setOpenRoles] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMode(m.mode);
        setAuthOn(m.auth);
        setOpenRoles(m.open_roles);
        setUser(m.user);
      })
      .catch(() => setAuthOn(false));
    // ?autorun starts a fresh paced pipeline run on load — used for demo
    // recordings so Mission Control opens without a click.
    if (new URLSearchParams(window.location.search).has("autorun")) {
      setLoading(false);
      loadDemo();
      return;
    }
    // Restore whatever you were last looking at. The list comes back newest
    // first; if that run is still going, keep pulling until it finishes rather
    // than presenting a half-finished report as though it were the answer.
    api
      .listProductions()
      .then(async (list) => {
        if (list.length === 0) return;
        const newest = list[0];
        setState(await api.getProduction(newest.id));
        if (newest.running) setResuming(newest.id);
        setInterrupted(Boolean(newest.interrupted));
      })
      .catch(() => setError("Could not reach the ClearFrame API. Is the server running?"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A restored run is still executing server-side. Poll until it finishes, so
  // a page refresh mid-analysis picks up where it left off instead of freezing
  // on a partial report.
  useEffect(() => {
    if (!resuming) return;
    const id = window.setInterval(async () => {
      try {
        const fresh = await api.getProduction(resuming);
        setState(fresh);
        const list = await api.listProductions();
        const row = list.find((r) => r.id === resuming);
        if (row && !row.running) setResuming(null);
      } catch {
        setResuming(null);
      }
    }, 3000);
    return () => window.clearInterval(id);
  }, [resuming]);

  // Warm the boxes for the moments a reviewer will actually pause on.
  //
  // Grounding a cold frame is a model round trip on a still and takes about
  // eight seconds. Done only on demand that IS the interaction: pause, wait,
  // and meanwhile the only box available is the scan's union across the whole
  // appearance, which is right about what and only roughly right about where.
  // The appearance timecodes are already known, so the wait is avoidable.
  const warmed = useRef<string | null>(null);
  useEffect(() => {
    const pid = state?.production?.id;
    if (!pid || !state?.production?.has_media || resuming) return;
    if (warmed.current === pid) return;
    warmed.current = pid;
    fetch(`/api/productions/${pid}/preground`, { method: "POST" }).catch(() => {});
  }, [state?.production?.id, state?.production?.has_media, resuming]);

  const changeRole = (r: Role) => {
    setRole(r);
    setRoleState(r);
  };

  // The way back. Without it a loaded production was terminal: the hero only
  // renders when `state` is null, so the upload panel became unreachable and
  // the only escape was reloading the browser.
  const newProduction = () => {
    setState(null);
    setMission(null);
    setShowUpload(true);
    setError(null);
  };

  const loadDemo = async () => {
    setError(null);
    try {
      await api.startPacedDemo(0.45);
      setState(null);
      setArtifacts([]);
      setMission("demo");
    } catch {
      setError("Demo production could not be started.");
    }
  };

  const enterReview = async (pid: string = "demo") => {
    try {
      const fresh = await api.getProduction(pid);
      setState(fresh);
      setMission(null);
      // Handing over at the preliminary report means the run is still going.
      // Keep pulling so the cards fill in rather than freezing half-done.
      const list = await api.listProductions();
      const row = list.find((r) => r.id === pid);
      if (row?.running) setResuming(pid);
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

  if (loading || authOn === null) {
    return (
      <div className="hero">
        <div className="slate">Loading…</div>
      </div>
    );
  }

  // The gate, above every other screen: a deployment with authentication on
  // has nothing to show a stranger — not the findings, not the footage, and
  // certainly not the upload form that starts a paid pipeline run.
  if (authOn && !user) {
    return (
      <SignIn
        onSignedIn={setUser}
        openRoles={openRoles}
        onPickRole={(r) => changeRole(r as Role)}
      />
    );
  }

  if (mission) {
    return (
      <MissionControl productionId={mission} onComplete={() => enterReview(mission)} />
    );
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
            onStarted={(pid) => {
              setState(null);
              setMission(pid);
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
    liability,
    preview,
    sponsor_conflicts,
    assessed_exposures,
    cast,
    subsumed_ids,
    source_work_summary,
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
  // Risk lands at stage 9; findings land at stage 3. Restoring a run in
  // between meant `risk[el.id]` was undefined and the whole view threw — a
  // blank screen, which is the worst possible way to render partial progress.
  //
  // The preview stage already banded every finding at stage 6, and that
  // provisional score is an upper bound, so it is the correct stand-in until
  // the real one arrives.
  const previewById = Object.fromEntries(
    (preview ?? []).map((f) => [f.element_id, f]),
  );
  const riskFor = (id: string): Risk => {
    const final = risk?.[id];
    if (final) return final;
    const p = previewById[id];
    return {
      element_id: id,
      score: p?.provisional_score ?? 0,
      band: (p?.provisional_band ?? "LOW") as Risk["band"],
      factors: {},
      de_minimis: false,
    };
  };

  const sorted = [...elements].sort((a, b) => riskFor(b.id).score - riskFor(a.id).score);
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
    BANDS.map((b) => [b, elements.filter((el) => riskFor(el.id).band === b).length]),
  );

  const jumpTo = (id: string) => {
    setActiveId(id);
    const el = elements.find((e) => e.id === id);
    const first = el?.time_ranges?.[0];
    if (first && videoRef.current && production.has_media) {
      // Land INSIDE the appearance, not a beat before it. Every box rule —
      // here and in overlay.py — is start_s <= t <= end_s, so seeking to
      // start_s - 0.25 put the playhead outside the range and correctly drew
      // nothing: clicking a finding showed no box at all. And pause, because
      // boxes are only drawn while paused.
      videoRef.current.currentTime = Math.max(first.start_s + 0.15, 0);
      videoRef.current.pause();
    }
    cardRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // Jump to ONE appearance rather than the first. A finding that shows up in
  // four shots has four boxes now, and the only way to see the third is to be
  // able to land in it.
  const seekTo = (seconds: number, id: string) => {
    setActiveId(id);
    if (videoRef.current && production.has_media) {
      videoRef.current.currentTime = Math.max(seconds + 0.15, 0);
      videoRef.current.pause();
    }
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
        {authOn && user && !openRoles ? (
          // A role you can prove. The switcher below is honest only when there
          // is nobody to ask — with auth on and roles granted, the server
          // decides and the client saying otherwise is the bypass that closed.
          <div className="whoami" title={user.email ?? user.uid}>
            <span className="whoami-name">{user.name || user.email || user.uid}</span>
            <span className="whoami-role">{user.role}</span>
            <button
              type="button"
              className="topbtn"
              onClick={() => void signOut().then(() => setUser(null))}
            >
              sign out
            </button>
          </div>
        ) : (
          <>
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
            {openRoles && user && (
              <div className="whoami" title={user.email ?? user.uid}>
                <span
                  className="whoami-role open"
                  title="Roles are open on this deployment so anyone can try every control. Your decisions are still recorded against your email."
                >
                  chosen
                </span>
                <span className="whoami-name">
                  {user.name || user.email || user.uid}
                </span>
                <button
                  type="button"
                  className="topbtn"
                  onClick={() => void signOut().then(() => setUser(null))}
                >
                  sign out
                </button>
              </div>
            )}
          </>
        )}
        <button
          className="topbtn"
          onClick={newProduction}
          title="Clear this production and upload another"
        >
          + New
        </button>
        {isDemo && (
          <button
            className="topbtn"
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
          mediaVersion={production.media_version ?? ""}
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
        {source_work_summary && source_work_summary.subsumed > 0 && (
          <div className="work-banner">
            <strong>This footage IS “{source_work_summary.title}”.</strong>{" "}
            {source_work_summary.headline} There is one counterparty and one
            action here, not {source_work_summary.subsumed}.
            <div className="work-action">{source_work_summary.action}</div>
            <div className="work-caveat">{source_work_summary.caveat}</div>
          </div>
        )}
        {(cast?.length ?? 0) > 0 && (
          <div className="cast-banner">
            <strong>Cast recognised, not flagged.</strong> {cast.length} face
            {cast.length === 1 ? "" : "s"} on screen belong to credited performers.
            These are not clearance findings and carry no box: you engaged them, so
            their consent is a cast agreement rather than a rights lookup. Anyone the
            scan could <em>not</em> name is still in the list below and still needs a
            release.
            <ul>
              {cast.map((c) => (
                <li key={c.id}>
                  <strong>{c.performer}</strong>
                  {c.character && <> as {c.character}</>} — {c.screen_time_s.toFixed(1)}s
                  on screen
                </li>
              ))}
            </ul>
            Confirm the executed performer agreements and any guild paperwork cover this
            production's media, territory and term — the same three gaps that catch a
            music licence.
          </div>
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
        {resuming && (
          <div className="resuming-banner">
            <strong>Still analysing.</strong> This run is continuing on the server —
            the findings below are what has landed so far and will keep filling in.
            Refreshing or closing the tab will not stop it.
          </div>
        )}
        {!resuming && interrupted && (
          <div className="resuming-banner">
            <strong>This analysis never finished.</strong> The server was restarted
            while it was running, so the stages below are as far as it got. Nothing
            is working on it now — upload the clip again for a complete report.
          </div>
        )}
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
            risk={riskFor(el.id)}
            options={remediation[el.id] ?? []}
            decision={decisions[el.id]}
            court={court?.[el.id]}
            plan={research_plan?.[el.id]}
            route={routes?.[el.id]}
            liability={liability?.[el.id]}
            pending={Boolean(resuming)}
            corroboration={corroboration?.[el.id]}
            coverage={coverage?.[el.id]}
            freshness={freshness?.[el.id] ?? []}
            territory={territory_risk?.[el.id] ?? []}
            subsumed={(subsumed_ids ?? []).includes(el.id)}
            unscripted={unscriptedIds.has(el.id)}
            candidates={candidates?.[el.id] ?? []}
            fps={production.fps}
            role={role}
            onDecide={onDecide}
            cardRef={(node) => {
              cardRefs.current[el.id] = node;
            }}
            onHover={() => setActiveId(el.id)}
            onSeek={(s) => seekTo(s, el.id)}
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
