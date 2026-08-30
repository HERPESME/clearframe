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

---

# Phase 8 — Bring your own footage + rights ledger

**Status:** Implemented 2026-08-22, same branch.

Three features requested after Phase 7, in dependency order.

## 1. Footage upload

`POST /api/productions` (multipart) stores the clip under `<out>/media/{pid}/`,
creates the Production with the chosen territories and distribution media, and
streams the pipeline over the existing SSE channel. 512MB cap enforced while
streaming; extension whitelist (`.mp4/.m4v/.mov/.webm`); the uploaded filename
is discarded and replaced with `footage<ext>` so nothing path-traversal-shaped
reaches the filesystem.

**Demo mode refuses with 409.** It replays fixtures, so analysing an upload
would hand back Golden Hour's findings as if they were the user's footage.
Saying so is better than a silent lie.

## 2. Video player with box overlay

`GET /api/productions/{pid}/media` serves the clip. `VideoPlayer` overlays an
SVG whose viewBox is `0 0 1 1`, so the normalized detection boxes map straight
onto the video element (which fills its box at `width:100%; height:auto`).
Boxes appear only while the playhead is inside a finding's time range; each
carries a label with the identity verdict and coverage state. Clicking a
finding card scrubs the player to a beat before it appears.

Productions without media (the demo scene) fall back to the `FramePosition`
schematic — the geometry without the footage.

## 3. Rights ledger

`licensing.py` matches each finding's researched owner against the licence
register using the same token-overlap rule as drift and corroboration, then
checks the three gaps that sink real productions: **territory**, **term**, and
**media scope**.

States: `COVERED` / `PARTIAL` (gaps enumerated) / `NOT_COVERED` / `UNKNOWN`.
UNKNOWN is used whenever ownership or identity is unresolved — the demo's
Adidas duffel has a matching grant on file (LIC-005) but a disputed identity,
so it reads UNKNOWN rather than falsely covered. A licence cannot cover a
finding we cannot name.

Ledgers upload as CSV or JSON (`POST /api/licences`, role-gated to
legal/producer), merge or replace, and surface through MCP as `list_licences`
and `check_coverage`. Auto-approve honours the ledger: COVERED accepts on that
basis; PARTIAL routes to license with the gap named.

## Test corpus

`scripts/fetch_test_clips.sh` pulls six ~2MB public-domain commercials from
archive.org/details/ctvc (Bayer, Jell-O, Lipton, Texaco, Playtex, Volkswagen)
plus a hand-written `ground_truth.json`. The films are public domain; the marks
in them are still live and still owned — the exact gap the product exists to
flag. `docs/sample-rights-ledger.csv` produces covered / gapped / unlicensed
states against that corpus.

## Defects fixed

- Uploaded ledgers without an `id` column were numbered by row position, which
  silently overwrote existing entries on merge (`assign_ids`).
- The state directory now also holds `licences.json`, which raw
  `glob("*.json")` calls tried to parse as production state
  (`LocalJsonStore.production_ids()`).

## Still not done

- **Audio fingerprinting.** Music is detected, categorised, weighted highest
  (1.0) and routed to the deepest research tier — but identification is a
  language model listening and naming a track, and `CORROBORATABLE` excludes
  MUSIC_SYNC so every song is permanently SINGLE_SOURCE. That title flows into
  an ASCAP/BMI cue sheet, which is a legal filing. Needs an ACRCloud/AudD key.
