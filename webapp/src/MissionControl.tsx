import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { CourtHolding, PipelineEvent } from "./types";

type AgentStatus = "idle" | "active" | "done";

interface AgentCard {
  key: string;
  name: string;
  role: string;
  status: AgentStatus;
  line: string;
}

const INITIAL_AGENTS: AgentCard[] = [
  { key: "script", name: "Script Reader", role: "Gemini · pre-production", status: "idle", line: "Standing by" },
  { key: "scan", name: "Scene Scanner", role: "Gemini · video analysis", status: "idle", line: "Standing by" },
  { key: "audit", name: "E&O Auditor", role: "Gemini · second-pass review", status: "idle", line: "Standing by" },
  { key: "triage", name: "Triage", role: "deterministic rules", status: "idle", line: "Standing by" },
  { key: "corroborate", name: "Identity Corroborator", role: "logo catalogue · second opinion", status: "idle", line: "Standing by" },
  { key: "preview", name: "Preliminary Report", role: "footage-derived · no research", status: "idle", line: "Standing by" },
  { key: "planner", name: "Budget Planner", role: "escalation ladder", status: "idle", line: "Standing by" },
  { key: "research", name: "Rights Researchers", role: "Parallel Task API · fan-out", status: "idle", line: "Standing by" },
  { key: "signals", name: "Live Signals", role: "Parallel Search · real time", status: "idle", line: "Standing by" },
  { key: "risk", name: "Risk Engine", role: "reproducible scoring", status: "idle", line: "Standing by" },
  { key: "territory", name: "Territory Analyst", role: "per-jurisdiction exposure", status: "idle", line: "Standing by" },
  { key: "remediation", name: "Remediation Drafter", role: "license / blur / memo drafts", status: "idle", line: "Standing by" },
  { key: "court", name: "Clearance Court", role: "counsel v. advocate · judge", status: "idle", line: "Standing by" },
];

const HOLDING_LABEL: Record<CourtHolding, string> = {
  clear_required: "CLEAR REQUIRED",
  defensible: "DEFENSIBLE",
  escalate: "ESCALATE",
};

const fmtTime = (s: number | null | undefined) => {
  if (s === null || s === undefined) return "--:--";
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
};

interface RowItem {
  id: string;
  text: string;
  chip?: string;
  chipClass?: string;
}

export function MissionControl({
  productionId = "demo",
  onComplete,
}: {
  // Was hardcoded to "demo", so an upload opened a stream to the demo
  // production's event queue — which is empty. The run was progressing fine
  // server-side while the screen sat blank, which is exactly what it looked
  // like: nothing happening and no way to tell why.
  productionId?: string;
  onComplete: () => void;
}) {
  const [agents, setAgents] = useState<AgentCard[]>(INITIAL_AGENTS);
  const [previewRows, setPreviewRows] = useState<RowItem[]>([]);
  // The preliminary report is complete at this point — every finding
  // timestamped and banded — and only ownership is still landing. Making
  // someone stare at a progress roster until the slowest rights lookup
  // finishes is a UI decision, not a technical constraint.
  const [previewReady, setPreviewReady] = useState(false);
  const [researchRows, setResearchRows] = useState<RowItem[]>([]);
  const [courtRows, setCourtRows] = useState<RowItem[]>([]);
  const [idRows, setIdRows] = useState<RowItem[]>([]);
  const [finished, setFinished] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const patch = (key: string, changes: Partial<AgentCard>) =>
    setAgents((prev) => prev.map((a) => (a.key === key ? { ...a, ...changes } : a)));

  useEffect(() => {
    // Reconnect rather than give up.
    //
    // `onerror` used to close the stream for good, so ANY interruption froze
    // the screen permanently with no error shown — a 404 in the seconds before
    // the worker writes its first event, an API container recycling mid-run, a
    // laptop lid closing. The analysis carried on server-side and the reviewer
    // watched "Standing by" until they gave up.
    //
    // Replay is safe, which is what makes reconnecting the right answer: the
    // server keeps the whole log and streams it from the top, and every handler
    // below is a `patch(key, {...})` setter rather than an increment, so
    // reprocessing events converges on the same screen.
    let closed = false;
    let attempts = 0;
    let timer: number | undefined;
    let source: EventSource;

    const connect = () => {
      if (closed) return;
      source = new EventSource(api.eventsUrl(productionId));
      sourceRef.current = source;
      wire(source);
    };

    const retry = () => {
      source?.close();
      if (closed || attempts >= 40) return;
      // Backoff to 5s: a cold worker is seconds away, a recycling container
      // rather longer, and neither is helped by hammering.
      const wait = Math.min(1000 * 2 ** Math.min(attempts, 3), 5000);
      attempts += 1;
      timer = window.setTimeout(connect, wait);
    };

    const wire = (source: EventSource) => {
    source.onmessage = (msg) => {
      const e: PipelineEvent = JSON.parse(msg.data);
      switch (e.type) {
        case "stage_start":
          if (e.stage === "script") {
            patch("script", { status: "active", line: "Reading the screenplay…" });
          } else if (e.stage === "drift") {
            patch("triage", { status: "active", line: "Comparing script vs screen…" });
          } else if (e.stage === "scan") {
            patch("scan", { status: "active", line: "Watching footage…" });
          } else if (e.stage === "research") {
            patch("planner", { status: "active", line: "Allocating research budget…" });
            patch("research", { status: "active", line: "Dispatching researchers…" });
          } else if (e.stage === "corroborate") {
            patch("corroborate", { status: "active", line: "Cross-checking identities…" });
          } else if (e.stage === "freshness") {
            patch("signals", { status: "active", line: "Searching for enforcement activity…" });
          } else if (e.stage === "territory") {
            patch("territory", { status: "active", line: "Banding per territory…" });
          } else if (e.stage === "court") {
            patch("court", { status: "active", line: "Court is in session" });
          } else {
            patch(e.stage!, { status: "active", line: "Working…" });
          }
          break;
        case "script_mentions":
          patch("script", {
            status: "done",
            line: e.count
              ? `${e.count} clearables flagged in the script`
              : "No script provided",
          });
          break;
        case "drift_computed":
          patch("triage", {
            status: "done",
            line: `${(e as { unscripted?: number }).unscripted ?? 0} on-screen elements were never scripted`,
          });
          break;
        case "corroboration_done": {
          const ok = (e.CORROBORATED ?? 0) + (e.FINGERPRINTED ?? 0);
          const bad = e.CONFLICTED ?? 0;
          patch("corroborate", {
            status: "done",
            line: bad
              ? `${ok} identities confirmed · ${bad} disputed`
              : `${ok} identities independently confirmed`,
          });
          break;
        }
        case "identity_conflict":
          setIdRows((rows) => [
            ...rows,
            {
              id: `id-${e.element_id}`,
              text: `${e.label} — detector read “${e.detected_label}”`,
              chip: "DISPUTED",
              chipClass: "clear_required",
            },
          ]);
          break;
        case "research_blocked":
          setResearchRows((rows) => [
            ...rows,
            {
              id: `blk-${e.element_id}`,
              text: `${e.label} — not researched`,
              chip: "ID DISPUTED",
              chipClass: "warn",
            },
          ]);
          break;
        case "freshness_checked":
          setResearchRows((rows) => [
            ...rows,
            {
              id: `fresh-${e.element_id}`,
              text: `↳ ${e.label}: ${e.material ?? 0} enforcement signal(s) live`,
              chip: (e.material ?? 0) > 0 ? "ACTIVE" : "QUIET",
              chipClass: (e.material ?? 0) > 0 ? "warn" : "ok",
            },
          ]);
          break;
        case "territory_assessed":
          patch("territory", {
            status: "done",
            line: `${e.territories} territories · ${e.divergent} findings band differently`,
          });
          break;
        case "candidates_found":
          setResearchRows((rows) => [
            ...rows,
            {
              id: `cand-${e.element_id}`,
              text: `↳ ${e.count} candidate owners enumerated (FindAll)`,
              chip: "LEADS",
              chipClass: "tier",
            },
          ]);
          break;
        case "scan_found":
          patch("scan", { line: `${e.count} clearable elements found` });
          patch("audit", { status: "active", line: "Auditing the first pass…" });
          break;
        case "audit_found":
          patch("audit", {
            status: "done",
            line: e.count ? `Caught ${e.count} missed element${e.count === 1 ? "" : "s"}` : "Nothing missed",
          });
          break;
        case "stage_complete":
          if (e.stage === "scan") {
            patch("scan", { status: "done", line: "Scan complete" });
          } else if (e.stage === "triage") {
            patch("triage", { status: "done", line: "Findings categorized & deduped" });
          } else if (e.stage === "research") {
            patch("research", { status: "done", line: "All research returned" });
          } else if (e.stage === "freshness") {
            patch("signals", { status: "done", line: "Live signal sweep complete" });
          } else if (e.stage === "risk") {
            patch("risk", { status: "done", line: "Every score reproducible" });
          } else if (e.stage === "remediation") {
            patch("remediation", { status: "done", line: "Options drafted per finding" });
          } else if (e.stage === "court") {
            patch("court", { status: "done", line: "All rulings issued" });
          }
          break;
        case "preview_ready": {
          const awaiting = e.awaiting_research ?? 0;
          patch("preview", {
            status: "done",
            line: `${e.count ?? 0} findings timestamped and banded · ${e.resolved_now ?? 0} already actionable · ${awaiting} awaiting ownership`,
          });
          setPreviewReady(true);
          setPreviewRows(
            (e.findings ?? []).map((f) => ({
              id: f.element_id,
              text: `${fmtTime(f.start_s)}  ${f.label}`,
              chip: f.band,
              chipClass: `band ${f.band}`,
            })),
          );
          break;
        }
        case "research_planned": {
          const r = e.routes ?? {};
          const free = (r.LOCAL ?? 0) + (r.STATUTE ?? 0);
          const deep = e.deep_runs ?? 0;
          patch("planner", {
            status: "done",
            line:
              free > 0
                ? `${free} resolved free · ${r.SEARCH ?? 0} live search · ${deep} deep · $${(e.total_est_cost_usd ?? 0).toFixed(2)}`
                : `${deep} deep research runs · $${(e.total_est_cost_usd ?? 0).toFixed(2)}`,
          });
          break;
        }
        case "research_resolved":
          setResearchRows((rows) => [
            ...rows,
            {
              id: e.element_id!,
              text: e.label ?? "",
              chip: e.tier === "BLOCKED" ? "blocked" : "no research needed",
              chipClass: "tier",
            },
          ]);
          break;
        case "research_start":
          setResearchRows((rows) => [
            ...rows,
            { id: e.element_id!, text: e.label ?? "", chip: e.processor, chipClass: "tier" },
          ]);
          break;
        case "research_done":
          setResearchRows((rows) =>
            rows.map((r) =>
              r.id === e.element_id
                ? {
                    ...r,
                    chip: e.status === "complete" ? "OWNER FOUND" : "INCOMPLETE",
                    chipClass: e.status === "complete" ? "ok" : "warn",
                  }
                : r,
            ),
          );
          break;
        case "case_opened":
          setCourtRows((rows) => [...rows, { id: e.element_id!, text: e.label ?? "" }]);
          break;
        case "case_ruled":
          setCourtRows((rows) =>
            rows.map((r) =>
              r.id === e.element_id
                ? { ...r, chip: HOLDING_LABEL[e.holding!], chipClass: e.holding }
                : r,
            ),
          );
          break;
        case "run_complete":
          setFinished(true);
          closed = true;
          source.close();
          break;
      }
      // A message arriving means the connection is healthy again.
      attempts = 0;
    };
    source.onerror = () => retry();
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      sourceRef.current?.close();
    };
  }, [productionId]);

  return (
    <div className="mission">
      <div className="mission-beam" aria-hidden="true" />
      <div className="mission-head">
        <div className="brand">
          CLEAR<b>FRAME</b>
        </div>
        <span className="slate">Mission Control</span>
        <h2>The clearance department is working</h2>
      </div>
      <div className="agent-grid">
        {agents.map((a) => (
          <div key={a.key} className={`agent ${a.status}`}>
            <div className="agent-name">
              <span className={`dot ${a.status}`} />
              {a.name}
            </div>
            <div className="agent-role">{a.role}</div>
            <div className="agent-line">{a.line}</div>
            {a.key === "preview" && previewRows.length > 0 && (
              <div className="agent-rows">
                {previewRows.map((r) => (
                  <div key={r.id} className="agent-row">
                    <span className="row-text">{r.text}</span>
                    {r.chip && <span className={`row-chip ${r.chipClass ?? ""}`}>{r.chip}</span>}
                  </div>
                ))}
              </div>
            )}
            {a.key === "research" && researchRows.length > 0 && (
              <div className="agent-rows">
                {researchRows.map((r) => (
                  <div key={r.id} className="agent-row">
                    <span className="row-text">{r.text}</span>
                    {r.chip && <span className={`row-chip ${r.chipClass ?? ""}`}>{r.chip}</span>}
                  </div>
                ))}
              </div>
            )}
            {a.key === "corroborate" && idRows.length > 0 && (
              <div className="agent-rows">
                {idRows.map((r) => (
                  <div key={r.id} className="agent-row">
                    <span className="row-text">{r.text}</span>
                    {r.chip && <span className={`row-chip ${r.chipClass ?? ""}`}>{r.chip}</span>}
                  </div>
                ))}
              </div>
            )}
            {a.key === "court" && courtRows.length > 0 && (
              <div className="agent-rows">
                {courtRows.map((r) => (
                  <div key={r.id} className="agent-row">
                    <span className="row-text">{r.text}</span>
                    <span className={`row-chip ${r.chipClass ?? "pending"}`}>
                      {r.chip ?? "IN SESSION"}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="mission-foot">
        {finished ? (
          <button className="generate" onClick={onComplete}>
            Enter review — all findings ready
          </button>
        ) : previewReady ? (
          <>
            <span className="pending-note">
              <span className="spinner" /> Ownership research still running…
            </span>
            <button className="generate" onClick={onComplete}>
              See findings now — {previewRows.length} timestamped and banded
            </button>
          </>
        ) : (
          <span className="pending-note">
            <span className="spinner" /> Streaming live from the pipeline…
          </span>
        )}
      </div>
    </div>
  );
}
