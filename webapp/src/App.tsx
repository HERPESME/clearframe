import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, setRole } from "./api";
import { ElementCard } from "./ElementCard";
import { Timeline } from "./Timeline";
import type { Action, ProductionState, RiskBand, Role } from "./types";

const BANDS: RiskBand[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export default function App() {
  const [state, setState] = useState<ProductionState | null>(null);
  const [loading, setLoading] = useState(true);
  const [role, setRoleState] = useState<Role>("legal");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});

  useEffect(() => {
    api
      .listProductions()
      .then(async (list) => {
        if (list.length > 0) setState(await api.getProduction(list[0].id));
      })
      .catch(() => setError("Could not reach the ClearFrame API. Is the server running?"))
      .finally(() => setLoading(false));
  }, []);

  const changeRole = (r: Role) => {
    setRole(r);
    setRoleState(r);
  };

  const loadDemo = async () => {
    setLoading(true);
    setError(null);
    try {
      setState(await api.createDemo());
    } catch {
      setError("Demo production could not be created.");
    } finally {
      setLoading(false);
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

  if (!state) {
    return (
      <div className="hero">
        <div className="slate">ClearFrame · automated clearance department</div>
        <h1>
          Every frame, <em>cleared.</em>
        </h1>
        <p>
          Gemini watches the footage and finds everything that needs legal clearance.
          Parallel researches who owns it. You make the call — with evidence attached.
        </p>
        <button className="generate" onClick={loadDemo}>
          Load demo production
        </button>
        {error && <div className="error-banner">{error}</div>}
      </div>
    );
  }

  const { production, elements, research, risk, remediation, decisions } = state;
  const sorted = [...elements].sort((a, b) => risk[b.id].score - risk[a.id].score);
  const pending = elements.filter((el) => !decisions[el.id]);
  const bandCounts = Object.fromEntries(
    BANDS.map((b) => [b, elements.filter((el) => risk[el.id].band === b).length]),
  );

  const jumpTo = (id: string) => {
    setActiveId(id);
    cardRefs.current[id]?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <>
      <header className="topbar">
        <span className="brand">
          CLEAR<b>FRAME</b>
        </span>
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
      </header>

      <Timeline
        elements={sorted}
        risk={risk}
        durationS={production.duration_s}
        fps={production.fps}
        activeId={activeId}
        onJump={jumpTo}
      />

      {error && <div className="error-banner">{error}</div>}

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
      </div>

      <main className="cards">
        {sorted.map((el) => (
          <ElementCard
            key={el.id}
            element={el}
            research={research[el.id]}
            risk={risk[el.id]}
            options={remediation[el.id] ?? []}
            decision={decisions[el.id]}
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
            <span className="spacer" />
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
