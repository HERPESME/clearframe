import { useState } from "react";
import type {
  Action,
  CandidateEntity,
  Corroboration,
  Coverage,
  CourtOpinion,
  Decision,
  Element,
  FreshnessSignal,
  RemediationOption,
  Research,
  ResearchPlan,
  ResearchRoute,
  Risk,
  Role,
  TerritoryRisk,
} from "./types";
import { FramePosition } from "./FramePosition";
import { tc } from "./timecode";

const HOLDING_TEXT = {
  clear_required: "CLEAR REQUIRED",
  defensible: "DEFENSIBLE",
  escalate: "ESCALATE",
} as const;

// What answered this finding. LOCAL and STATUTE cost nothing and take no time,
// which is precisely why they must be labelled rather than left to look like
// research that quietly did not happen.
// Rights holders object to how a brand is SHOWN far more often than to its
// presence. NBC digitally erased In-Sink-Erator from Heroes because a hand got
// mangled in the disposal, not because the logo was visible.
const TONE_TEXT: Record<string, string> = {
  FAVOURABLE: "SHOWN FAVOURABLY",
  NEUTRAL: "SHOWN NEUTRALLY",
  UNFLATTERING: "SHOWN UNFLATTERINGLY",
  DISPARAGING: "SHOWN DISPARAGINGLY",
};

const ROUTE_TEXT: Record<string, string> = {
  LOCAL: "OWNER KNOWN LOCALLY",
  STATUTE: "SETTLED BY LAW",
  SEARCH: "LIVE SEARCH",
  DEEP: "DEEP RESEARCH",
  BLOCKED: "NOT RESEARCHED",
};

const VERDICT_TEXT = {
  FINGERPRINTED: "ID FINGERPRINTED",
  CORROBORATED: "ID CORROBORATED",
  SINGLE_SOURCE: "ID SINGLE-SOURCE",
  CONFLICTED: "ID DISPUTED",
} as const;

const COVERAGE_TEXT: Record<string, string> = {
  COVERED: "ALREADY LICENSED",
  PARTIAL: "LICENCE GAP",
  NOT_COVERED: "UNLICENSED",
  UNKNOWN: "COVERAGE UNKNOWN",
};

const VERDICT_HELP = {
  FINGERPRINTED:
    "An acoustic fingerprint measured this recording against a database — spectral hashing over the audio itself, not a model's impression of it. This is the strongest identity ClearFrame can produce, and it is what a PRO cue sheet needs.",
  CORROBORATED:
    "A second, independent detector named the same thing. Identity is confirmed by two systems, not one model's guess.",
  SINGLE_SOURCE:
    "Only the video model identified this. No closed-vocabulary detector covers it (murals, tattoos, music), so identity is unconfirmed — not contradicted.",
  CONFLICTED:
    "The detectors named DIFFERENT things. Rights research is blocked: researching a disputed mark would attribute rights to the wrong holder.",
} as const;

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
  court: CourtOpinion | undefined;
  plan: ResearchPlan | undefined;
  route: ResearchRoute | undefined;
  corroboration: Corroboration | undefined;
  coverage: Coverage | undefined;
  freshness: FreshnessSignal[];
  territory: TerritoryRisk[];
  unscripted: boolean;
  candidates: CandidateEntity[];
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
  court,
  plan,
  route,
  corroboration,
  coverage,
  freshness,
  territory,
  unscripted,
  candidates,
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
  const disputed = corroboration?.verdict === "CONFLICTED";
  const materialSignals = freshness.filter((s) => s.material);
  const freeRoute = route?.tier === "LOCAL" || route?.tier === "STATUTE";
  const divergent =
    territory.length > 0 && new Set(territory.map((t) => t.band)).size > 1;

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
        {coverage && (
          <span
            className={`badge cov ${coverage.status}`}
            title={coverage.note}
          >
            {COVERAGE_TEXT[coverage.status]}
          </span>
        )}
        {corroboration && (
          <span
            className={`badge verdict ${corroboration.verdict}`}
            title={VERDICT_HELP[corroboration.verdict]}
          >
            {VERDICT_TEXT[corroboration.verdict]}
          </span>
        )}
        {unscripted && (
          <span
            className="badge unscripted"
            title="This element appears on screen but was never in the shooting script — nobody budgeted clearance for it."
          >
            NOT IN SCRIPT
          </span>
        )}
        {element.depiction && (
          <span
            className={`tone-chip ${element.depiction}`}
            title="How the element is portrayed. Brand owners object to depiction far more often than to presence."
          >
            {TONE_TEXT[element.depiction]}
          </span>
        )}
        {route && (
          <span
            className={`route-chip ${route.tier}`}
            title={`${route.rationale}${route.basis ? `\n\nAuthority: ${route.basis}` : ""}`}
          >
            {ROUTE_TEXT[route.tier]}
          </span>
        )}
        {plan && (
          <span className="plan-chip" title={plan.rationale}>
            research: {plan.processor} · ${plan.est_cost_usd.toFixed(2)}
          </span>
        )}
      </div>

      <div className="card-body">
        <div className="card-main">
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
        </div>
        {element.bbox && (
          <FramePosition
            bbox={element.bbox}
            atS={element.at_s}
            fps={fps}
            band={risk.band}
          />
        )}
      </div>

      {disputed && (
        <div className="conflict-banner">
          <strong>IDENTITY DISPUTED — research blocked.</strong> {corroboration!.note}
        </div>
      )}

      {coverage && (
        <div className="sec">
          <div className="sec-title">
            Rights already held
            {coverage.licence_id && <span className="sec-note"> · {coverage.licence_id}</span>}
          </div>
          <div className={coverage.gaps.length ? "gap-note" : "kv"}>
            {coverage.note}
            {coverage.gaps.length > 0 && (
              <ul className="gap-list">
                {coverage.gaps.map((g, i) => (
                  <li key={i}>{g}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {corroboration && !disputed && (
        <div className="sec">
          <div className="sec-title">Identity verification</div>
          <div className="kv">{corroboration.note}</div>
        </div>
      )}

      {route && (
        <div className={`sec route-note ${freeRoute ? "free" : ""}`}>
          <div className="sec-title">How this was resolved</div>
          <div className="kv">{route.rationale}</div>
          {route.basis && <div className="kv basis">Authority: {route.basis}</div>}
          {route.disposition && (
            <div className="disposition">
              <strong>Required action:</strong> {route.disposition}
            </div>
          )}
        </div>
      )}

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
          <>
            <div className="incomplete">
              {disputed
                ? "NOT RESEARCHED — identity must be resolved first."
                : "RESEARCH INCOMPLETE — rights holder not established from open-web sources. Manual investigation required."}
            </div>
            {candidates.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div className="sec-title">Possible rights holders — FindAll leads</div>
                {candidates.map((c, i) => (
                  <div className="citation" key={i}>
                    <a href={c.url}>{c.name}</a>{" "}
                    <span className="conf">{c.kind}</span>
                    <div>{c.note}</div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {freshness.length > 0 && (
        <div className="sec">
          <div className="sec-title">
            Live rights-holder signals
            <span className="sec-note"> · Parallel Search, checked at review time</span>
          </div>
          {materialSignals.length > 0 && (
            <div className="kv signal-count">
              {materialSignals.length} enforcement signal
              {materialSignals.length === 1 ? "" : "s"} found since research ran
            </div>
          )}
          {freshness.map((s, i) => (
            <div className={`citation ${s.material ? "material" : ""}`} key={i}>
              {s.material && <span className="sig-flag">ENFORCEMENT</span>}{" "}
              <a href={s.url}>{s.title}</a>
              <div>“{s.excerpt}”</div>
            </div>
          ))}
        </div>
      )}

      {territory.length > 0 && (
        <div className="sec">
          <div className="sec-title">
            Territory exposure
            {divergent && <span className="sec-note"> · varies by jurisdiction</span>}
          </div>
          <div className="terr-row">
            {territory.map((t) => (
              <span className={`terr-chip ${t.band}`} key={t.territory} title={t.rationale}>
                {t.territory} · {t.band}
              </span>
            ))}
          </div>
          {divergent && (
            <details className="option">
              <summary>Why the band changes across territories</summary>
              <div className="brief">
                {territory.map((t) => (
                  <div className="precedent" key={t.territory}>
                    · <b>{t.territory}</b> — {t.rationale}
                    {t.authority && <div className="pull-quote">{t.authority}</div>}
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      )}

      {court && (
        <div className="sec">
          <div className="sec-title">Clearance court</div>
          <div className={`court-ruling ${court.holding}`}>
            <span className="holding">{HOLDING_TEXT[court.holding]}</span>{" "}
            <span style={{ color: "var(--muted)" }}>({court.confidence} confidence)</span>{" "}
            — {court.reasoning}
          </div>
          {court.briefs.map((b, i) => (
            <details className="option" key={i}>
              <summary>
                <b>{b.side === "counsel" ? "Studio Counsel" : "Fair Use Advocate"}</b> —
                read the brief
              </summary>
              <div className="brief">
                {b.argument}
                {b.precedents.map((p, j) => (
                  <div className="precedent" key={j}>
                    · <em>{p.case_name}</em>, {p.citation} — {p.holding}
                    {p.quote && (
                      <div className="pull-quote">
                        “{p.quote}”{" "}
                        {p.source_url && <a href={p.source_url}>[source]</a>}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      )}

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
