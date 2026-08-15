# ClearFrame

**An autonomous rights-clearance department for film & TV.**

Every film must legally "clear" everything visible and audible in frame — logos, artwork, music, tattoos, faces — before distributors or E&O insurers will touch it. One uncleared tattoo nearly stopped *The Hangover Part II*'s $580M release. Today this is done frame-by-frame, by hand.

ClearFrame automates the department: **Gemini** watches raw footage and detects every clearable element; a deterministic multi-agent pipeline deep-researches each rights holder via the **Parallel Task API** (with citations and calibrated confidence as the legal audit trail), scores risk reproducibly, drafts remediation (license outreach emails, VFX blur estimates, de-minimis memos), and produces the industry-standard **clearance dossier** plus **NLE timeline markers** — with a human clearance coordinator approving every finding.

Built for the Google Cloud **Agentic Cinema** hackathon, **Parallel** partner track.

## Pipeline

```
footage ──▶ 1 SCAN (Gemini video) ──▶ 2 TRIAGE ──▶ 3 RIGHTS RESEARCH (Parallel Task API, fan-out)
        ──▶ 4 RISK SCORE (deterministic) ──▶ 5 REMEDIATION ──▶ [human review] ──▶ 6 DOSSIER
outputs: dossier.html (E&O-ready report) · dossier.json · markers.edl (Resolve) · markers.csv
```

## Quickstart (demo mode — zero credentials)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m clearframe run --demo --out out --auto-approve
open out/dossier.html
```

Demo mode replays recorded Gemini/Parallel responses through the identical pipeline code path. Run the test suite with `pytest`.

Live mode (Vertex AI Gemini + Parallel Task API + Agent Engine deployment) lands in Phase 2 — see `docs/superpowers/specs/` for the design spec and `docs/superpowers/plans/` for the build plan.

## License

MIT — see [LICENSE](LICENSE).

*ClearFrame output is automated decision support, not legal advice.*
