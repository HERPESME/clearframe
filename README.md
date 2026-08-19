# ClearFrame

**An autonomous rights-clearance department for film & TV.**

Every film must legally "clear" everything visible and audible in frame — logos, artwork, music, tattoos, faces — before distributors or E&O insurers will touch it. One uncleared tattoo nearly stopped *The Hangover Part II*'s $580M release. Today this is done frame-by-frame, by hand.

ClearFrame automates the department: **Gemini** watches raw footage and detects every clearable element; a deterministic multi-agent pipeline deep-researches each rights holder via the **Parallel Task API** (with citations and calibrated confidence as the legal audit trail), scores risk reproducibly, drafts remediation (license outreach emails, VFX blur estimates, de-minimis memos), and produces the industry-standard **clearance dossier**, **NLE timeline markers**, and an **ASCAP/BMI cue sheet** — with a human clearance coordinator approving every finding.

Built for the Google Cloud **Agentic Cinema** hackathon, **Parallel** partner track.

**🌐 Live demo (Cloud Run, demo mode):** [clearframe-220710110855.us-central1.run.app](https://clearframe-220710110855.us-central1.run.app) · **MCP endpoint:** `https://clearframe-mcp-220710110855.us-central1.run.app/mcp` (streamable HTTP)

![ClearFrame review UI](docs/images/review-ui.png)

## How it works — an agent team, not a prompt

```
footage ─▶ SCENE SCANNER (Gemini video) ─▶ E&O AUDITOR (2nd Gemini pass: "what did they miss?")
        ─▶ TRIAGE (rules + dedupe) ─▶ BUDGET PLANNER (allocates Parallel processor tiers + rationale)
        ─▶ RIGHTS RESEARCHERS (Parallel Task API fan-out, citations + confidence)
        ─▶ RISK ENGINE (deterministic, reproducible rubric) ─▶ REMEDIATION DRAFTER
        ─▶ THE CLEARANCE COURT ⚖  (Studio Counsel vs Fair Use Advocate vs Judge)
        ─▶ [human review — role-gated web app] ─▶ DOSSIER

outputs: dossier.html (E&O-ready report w/ court opinions + audit trail) · dossier.json
         markers.edl (Resolve) · markers.csv · cue_sheet.csv (ASCAP/BMI)
```

![Mission Control](docs/images/mission-control.png)

### The Clearance Court

Every contested finding (MEDIUM risk and up) is argued by two opposing agents: **Studio Counsel** briefs why the use is a risk; the **Fair Use Advocate** briefs the strongest good-faith defense — de minimis, *Rogers v. Grimaldi* expressive-work protection, fair use. Both cite real case law (*Ringgold v. BET*, *Sandoval v. New Line*, *Caterpillar v. Disney*, *Falkner v. GM*, VARA, §504(c)). A **Judge** weighs the briefs against practical cost and issues a ruling: `CLEAR REQUIRED`, `DEFENSIBLE`, or `ESCALATE`. Opinions attach reasoning to the dossier — they never alter the deterministic risk score, and the human still makes the call.

- The pipeline runs both as a plain orchestrator and as a **Google ADK `SequentialAgent`** (`src/clearframe/adk/agents.py`) — try it: `python -m clearframe run --demo --adk --auto-approve --out out` executes the full run under the real ADK Runner.
- Every research finding carries Parallel's **Basis** output — citations, per-field reasoning, calibrated confidence — because a legal document without provenance is worthless.
- Risk scores are pure code (`src/clearframe/scoring.py`): reproducible from stored inputs, never an LLM guess.

## Quickstart — demo mode (zero credentials, zero network)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# CLI: run pipeline + generate all artifacts
python -m clearframe run --demo --out out --auto-approve
open out/dossier.html

# Or the full review experience:
python -m clearframe serve --out out --port 8000
# open http://127.0.0.1:8000 → Load demo production → review → Generate dossier
```

Demo mode replays recorded Gemini/Parallel responses through the identical pipeline code path. `pytest` runs the whole suite.

## MCP server

The whole clearance department is also an **MCP server** — any MCP client (Gemini Enterprise, Claude, IDEs) can drive it as tools:

```bash
python -m clearframe.mcp --out out   # stdio transport
# tools: run_clearance · get_status · list_findings · get_finding · record_decision · generate_dossier
```

Role gating and the append-only audit trail apply identically across all three transports (CLI, web app, MCP) — one shared review service owns the rules. See [docs/deploy.md](docs/deploy.md) for client registration.

## Living clearance — the dossier that refuses to go stale

Clearance isn't an event; it's a subscription. ClearFrame covers the whole lifecycle:

- **Script pre-scan** (pre-production): Gemini reads the screenplay and flags clearables before a frame is shot.
- **Script-vs-screen drift**: elements on camera that were never scripted get a `NOT IN SCRIPT` flag — the set-dressing surprises nobody budgeted clearance for.
- **FindAll leads**: when deep research can't identify an owner (the unsigned mural), a recall-first Parallel FindAll pass enumerates candidate rights holders — registries, the building's owner, archives — instead of leaving a dead end.
- **Standing watch** (post-delivery): after the dossier, a watch is registered per risky finding — new lawsuits, filings, policy changes by the rights holder. Live mode creates Parallel Monitors when the API key includes the Monitors beta, and falls back to local stand-in watches otherwise (demo mode uses the same stand-ins); the webhook alert path is identical either way — an alert **reopens review automatically** and lands in the audit trail. Your dossier can't silently rot.

Run everything yourself: `./scripts/smoke.sh` verifies the full lifecycle across every transport (CLI, web, SSE, webhook, MCP stdio) in one command.

## Guardrails

- **Deterministic risk scoring** — pure code, reproducible from stored inputs; no LLM in the scoring path.
- **Server-side role gating** — only `legal`/`producer` record decisions, enforced in the review service, not the UI.
- **Append-only audit trail** — every decision (including revisions) and dossier generation is logged and printed in the dossier.
- **Research spend cap** — `CLEARFRAME_MAX_RESEARCH` (default 25) bounds the Parallel fan-out; overflow surfaces as RESEARCH INCOMPLETE, never silently dropped.
- **Gemini safety settings** — explicit `BLOCK_ONLY_HIGH` thresholds on the scan config.
- **Honest failure states** — unidentifiable rights holders escalate; unscanned footage ranges are listed in the report as not covered.
- **Stale-dossier protection** — revising any decision reopens review so an outdated report can't circulate.

## Live mode (Vertex AI Gemini + Parallel Task API)

```bash
pip install -e ".[dev,cloud]"
export CLEARFRAME_MODE=live GOOGLE_CLOUD_PROJECT=<project> PARALLEL_API_KEY=<key>
python -m clearframe run --live --footage gs://bucket/scene.mp4 --title "Golden Hour" --duration-s 62 --out out
```

See [docs/deploy.md](docs/deploy.md) for Cloud Run and Agent Engine deployment.

## Deployment (Cloud Run, scale-to-zero)

One image, two services, `min-instances=0` — compute cost is $0 with no traffic. `cloudbuild.yaml` builds and deploys both on every push to `main` (Cloud Build CI/CD):

```bash
gcloud builds submit --config cloudbuild.yaml .   # manual deploy
```

| Service | What | Demo-mode state |
| --- | --- | --- |
| `clearframe` | review webapp + API | `/tmp/out` (ephemeral — resets at scale-to-zero, by design for demo) |
| `clearframe-mcp` | MCP server, streamable HTTP at `/mcp`, stateless | same |

Connect an MCP client to the deployed server:

```bash
claude mcp add --transport http clearframe https://clearframe-mcp-220710110855.us-central1.run.app/mcp
```

## Repository map

```
src/clearframe/
  models.py scoring.py triage.py remediation.py dossier.py   # core domain (no cloud deps)
  pipeline.py stages/            # deterministic 6-stage orchestrator
  integrations/                  # Gemini + Parallel clients (live & fixture) + recorded fixtures
  exporters/                     # dossier HTML, EDL, CSV markers, cue sheet
  adk/                           # Google ADK SequentialAgent wrapper
  webapp/server.py               # FastAPI review API (server-side role enforcement)
webapp/                          # React review UI (prebuilt dist committed)
docs/superpowers/specs|plans/    # design spec and implementation plans
```

## License

MIT — see [LICENSE](LICENSE).

*ClearFrame output is automated decision support, not legal advice.*
