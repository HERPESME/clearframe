# ClearFrame

**An autonomous rights-clearance department for film & TV.**

Every film must legally "clear" everything visible and audible in frame — logos, artwork, music, tattoos, faces — before distributors or E&O insurers will touch it. One uncleared tattoo nearly stopped *The Hangover Part II*'s $580M release. Today this is done frame-by-frame, by hand.

ClearFrame automates the department: **Gemini** watches raw footage and detects every clearable element; a deterministic multi-agent pipeline deep-researches each rights holder via the **Parallel Task API** (with citations and calibrated confidence as the legal audit trail), scores risk reproducibly, drafts remediation (license outreach emails, VFX blur estimates, de-minimis memos), and produces the industry-standard **clearance dossier**, **NLE timeline markers**, and an **ASCAP/BMI cue sheet** — with a human clearance coordinator approving every finding.

Built for the Google Cloud **Agentic Cinema** hackathon, **Parallel** partner track.

![ClearFrame review UI](docs/images/review-ui.png)

## How it works

```
footage ──▶ 1 SCAN (Gemini video, Vertex AI) ──▶ 2 TRIAGE (rules + dedupe)
        ──▶ 3 RIGHTS RESEARCH (Parallel Task API deep research, concurrent fan-out)
        ──▶ 4 RISK SCORE (deterministic, reproducible rubric)
        ──▶ 5 REMEDIATION (license drafts / blur / reshoot / de-minimis memo)
        ──▶ [human review — role-gated web app] ──▶ 6 DOSSIER

outputs: dossier.html (E&O-ready report) · dossier.json · markers.edl (Resolve)
         markers.csv · cue_sheet.csv (ASCAP/BMI)
```

- The pipeline runs both as a plain orchestrator and as a **Google ADK `SequentialAgent`** (`src/clearframe/adk/agents.py`) deployable to Agent Engine.
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

## Live mode (Vertex AI Gemini + Parallel Task API)

```bash
pip install -e ".[dev,cloud]"
export CLEARFRAME_MODE=live GOOGLE_CLOUD_PROJECT=<project> PARALLEL_API_KEY=<key>
python -m clearframe run --live --footage gs://bucket/scene.mp4 --title "Golden Hour" --duration-s 62 --out out
```

See [docs/deploy.md](docs/deploy.md) for Cloud Run and Agent Engine deployment.

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
