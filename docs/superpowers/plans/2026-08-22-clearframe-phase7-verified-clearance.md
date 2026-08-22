# ClearFrame Phase 7 Implementation Plan — Verified Clearance

**Status:** Implemented 2026-08-22 (branch `feat/corroboration-search-territory`).

**Goal:** Close the gap between "an AI watched a video" and "this document is
usable by an E&O underwriter". Three additions: independent identity
corroboration, a real-time Parallel Search pass over rights holders, and
per-territory risk banding. Plus the two live-mode defects found while
validating.

**Architecture:** Everything slots behind the existing protocol seams — a new
`CorroborationClient` alongside `GeminiClient`/`ParallelClient`/`CourtClient`,
each with a fixture and a live twin sharing one parser. Two new pure-code core
modules (`corroboration.py`, `territory.py`, plus `freshness.py` for
materiality) keep the deterministic-scoring philosophy: no LLM decides a risk
band or an identity verdict.

## Why these three

1. **Identity corroboration.** The E&O Auditor is Gemini reviewing Gemini —
   the same model, the same priors. It reliably catches *omissions* and
   unreliably catches *misidentifications*. Misidentification is the worse
   failure: a wrong brand routes research to the wrong rights holder and
   produces a dossier certifying a clearance that was never obtained. The fix
   is a second detector of a *different kind* — a closed-vocabulary logo
   catalogue that cannot invent a brand outside it.
2. **Freshness.** Deep research is a snapshot from pipeline time. Decisions get
   made days later, and "has this holder started suing people since?" is
   exactly what a snapshot cannot contain. The Parallel Search API answers it
   per request rather than per Task run, which is what makes it affordable to
   call while a reviewer is on the page.
3. **Territory.** Clearance is jurisdictional and distributors buy territories
   separately. A mural is exposed in the US (17 U.S.C. §120(a) covers
   *buildings only*) and generally fine in Germany (UrhG §59). A single global
   band is a fiction.

## Global constraints

- All prior constraints hold. Core modules must not import `google.*`.
- Identity verdicts and territory bands are deterministic and reproducible from
  stored inputs — LLMs detect, code decides.
- A CONFLICTED identity **blocks** rights research rather than degrading it.
  Silence from the corroborator is `SINGLE_SOURCE`, never a conflict: a mural
  or a song is outside any brand catalogue, so absence is not contradiction.
- Corroboration is best-effort. If Video Intelligence is unavailable,
  unenabled, or errors, identities stay SINGLE_SOURCE and the pipeline runs.
- Demo scene grows 7 → 8 elements (deliberate, as 6 → 7 in Phase 4) so the
  conflict path is visible without credentials.

## Tasks

- [x] **Models** — `BBox`, `DetectorHit`, `IdentityVerdict`, `Corroboration`,
      `WebFinding`, `FreshnessSignal`, `TerritoryRisk`; `DetectedElement.bbox`
      / `.at_s`; `Production.release_territories`; four new `ProductionState`
      fields. Round-trip tested.
- [x] **`matching.py`** — extract the label matcher shared by drift and
      corroboration so one rule governs cross-source comparison.
- [x] **`corroboration.py`** — three-verdict logic, time-window overlap,
      confidence floor, `blocks_research`.
- [x] **`vision_client.py`** — `CorroborationClient` protocol,
      `parse_logo_annotations` (genuine Video Intelligence shape),
      `FixtureVisionClient`, `LiveVideoIntelligenceClient` (LOGO_RECOGNITION,
      gs:// or inline bytes, degrades quietly).
- [x] **Parallel Search** — `search()` on the protocol, live client against
      `POST /v1beta/search` with the `search-extract-2025-10-10` beta header,
      fixture twin, shared `parse_search_results`.
- [x] **`freshness.py`** — deterministic materiality (enforcement language vs
      brand-marketing noise).
- [x] **`territory.py`** — freedom-of-panorama table for US/GB/DE/FR/JP/IN with
      the governing statute per row, band arithmetic, `worst_band`.
- [x] **Stages** — `corroborate` (between triage and research), `freshness`
      (after research), `territory` (after risk). `ANALYSIS_STAGES` 8 → 11.
- [x] **ResearchStage** — skip and emit `research_blocked` for CONFLICTED;
      skip FindAll enumeration for them too.
- [x] **Dossier** — identity block, territory table with authority, live
      signals with enforcement flags, three new summary counters.
- [x] **Exporters** — `markers.csv` gains an `identity` column.
- [x] **Webapp** — `POST /api/productions/{pid}/freshness`.
- [x] **MCP** — `verify_identities`, `territory_report`, `check_freshness`;
      richer `get_finding` / `list_findings`.
- [x] **UI** — verdict badges, blocking conflict banner, live-signal section,
      territory chips, `FramePosition` box diagram, Mission Control agents.
- [x] **Smoke test** — section 5 covers all three; fixed a latent `pipefail`
      race in every `curl | grep` check.

## Defects fixed alongside

- **Live script pre-scan returned nothing.** `scan_script` routed through
  `_generate`, which unconditionally pinned `SCAN_RESPONSE_SCHEMA`, so Gemini
  was forced to answer in the video shape while `parse_script_payload` looked
  for `mentions`. `SCRIPT_RESPONSE_SCHEMA` existed but was referenced nowhere.
  Demo mode masked it (the fixture client reads the JSON directly). Verified
  live: 0 mentions before, 4 after.
- **Planner costs were ~10× Parallel's list price**, so Mission Control
  announced "$4.70 research budget" for a run costing about $0.40.

## What is deliberately NOT done

- **Parallel's managed Task MCP as the research transport.** Verified live
  (`Parallel Task MCP 1.0.5`); its tools return markdown only, with no custom
  output schemas, no processor tiers and no FindAll. Adopting it would delete
  `parse_task_output`, the Budget Planner, and the FindAll mural lead. Our own
  `clearframe-mcp` already tells the MCP story.
- **Audio fingerprinting for music.** The correct fix for the highest-stakes
  hallucination risk (a song title feeding a PRO cue sheet), but it needs a
  third-party key (ACRCloud/AudD). Next phase.
- **Video player + real frame stills.** `FramePosition` renders the box
  geometry without footage; real thumbnails need ffmpeg and an upload path.
