import { useState } from "react";
import type { Action, Decision, Element, RemediationOption, Research, Risk, Role } from "./types";
import { tc } from "./timecode";

const ACTION_LABEL: Record<Action, string> = {
  approve_risk: "Approve risk",
  license: "Pursue license",
  blur: "Blur in post",
  reshoot: "Flag for reshoot",
  escalate: "Escalate to counsel",
};

const STAMP_LABEL: Record<Action, string> = {
  approve_risk: "Risk approved",
  license: "License pursued",
  blur: "Blur ordered",
  reshoot: "Reshoot flagged",
  escalate: "Escalated",
};

interface Props {
  element: Element;
  research: Research | undefined;
  risk: Risk;
  options: RemediationOption[];
  decision: Decision | undefined;
  fps: number;
  role: Role;
  onDecide: (elementId: string, action: Action, note: string) => Promise<void>;
  cardRef: (node: HTMLDivElement | null) => void;
  onHover: () => void;
}

export function ElementCard({
  element,
  research,
  risk,
  options,
  decision,
  fps,
  role,
  onDecide,
  cardRef,
  onHover,
}: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const canDecide = role === "legal" || role === "producer";
  const complete = research && research.status === "complete";

  const decide = async (action: Action) => {
    setBusy(true);
    try {
      await onDecide(element.id, action, note);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`card ${risk.band}`} ref={cardRef} onMouseEnter={onHover}>
      {decision && (
        <div className={`stamp ${decision.action === "escalate" ? "escalate" : ""}`}>
          {STAMP_LABEL[decision.action]}
        </div>
      )}

      <div className="card-head">
        <span className="el-label">{element.label}</span>
        <span className="badge cat">{element.category.replace(/_/g, " ")}</span>
        <span className={`badge ${risk.band}`}>
          {risk.band} · {risk.score}
        </span>
        {risk.de_minimis && <span className="badge dim">DE MINIMIS</span>}
      </div>
      <div className="tc-line">
        {element.time_ranges
          .map((r) => `${tc(r.start_s, fps)}–${tc(r.end_s, fps)}`)
          .join("  ·  ")}
      </div>
      <div className="el-desc">{element.description}</div>
      <div className="factors">
        {Object.entries(risk.factors)
          .map(([k, v]) => `${k} ${v}`)
          .join("  ·  ")}
      </div>

      <div className="sec evidence">
        <div className="sec-title">Rights research</div>
        {complete ? (
          <>
            <div className="owner">
              {research.owner}{" "}
              <span className="kv">({research.owner_confidence} confidence)</span>
            </div>
            <div className="kv">
              Posture: {research.licensing_posture}
              {research.licensing_contact && <> · Contact: {research.licensing_contact}</>}
              {research.estimated_license_cost_band && (
                <> · Est. cost: {research.estimated_license_cost_band}</>
              )}
            </div>
            {research.litigation_history.length > 0 && (
              <div className="kv">
                Enforcement: {research.litigation_history.join(" — ")}
              </div>
            )}
            {research.basis.map((b, i) => (
              <div className="citation" key={i}>
                [{b.field}] <a href={b.url}>{b.url}</a> — “{b.excerpt}”{" "}
                <span className="conf">{b.confidence}</span>
                <div>{b.reasoning}</div>
              </div>
            ))}
          </>
        ) : (
          <div className="incomplete">
            RESEARCH INCOMPLETE — rights holder not established from open-web sources.
            Manual investigation required.
          </div>
        )}
      </div>

      <div className="sec">
        <div className="sec-title">Remediation options</div>
        {options.map((o, i) => (
          <details className="option" key={i}>
            <summary>
              <b>{o.kind.replace(/_/g, " ")}</b> — {o.summary}
              {o.est_cost_band ? ` (${o.est_cost_band})` : ""}
            </summary>
            {o.kind === "license" ? (
              <pre>{o.detail}</pre>
            ) : (
              <div className="plain">{o.detail}</div>
            )}
          </details>
        ))}
      </div>

      {decision ? (
        <div className="stamp-note">
          {decision.note || "No note."} — {decision.reviewer} ({decision.role})
        </div>
      ) : (
        <div className="decide">
          {(Object.keys(ACTION_LABEL) as Action[]).map((a) => (
            <button
              key={a}
              className="action"
              disabled={!canDecide || busy}
              onClick={() => decide(a)}
              title={canDecide ? undefined : "Editors have read-only access"}
            >
              {ACTION_LABEL[a]}
            </button>
          ))}
          <input
            placeholder="Decision note (optional)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={!canDecide}
          />
        </div>
      )}
    </div>
  );
}
