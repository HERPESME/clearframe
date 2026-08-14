# ClearFrame Core Engine (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build ClearFrame's deterministic multi-agent clearance pipeline running end-to-end in demo mode (fixtures, zero credentials): footage metadata → Gemini-shaped detections → triage → Parallel-shaped rights research → risk scoring → remediation → clearance dossier (HTML) + NLE markers (EDL/CSV), driven by a CLI, wrapped in Google ADK agents.

**Architecture:** Framework-free core (Pydantic models, pure-code scoring/triage/exporters) with integration clients behind protocols (`GeminiClient`, `ParallelClient`) that have fixture-backed and live implementations. A deterministic `Pipeline` orchestrator runs six stages and persists state after each; a thin ADK adapter (`BaseAgent` subclasses in a `SequentialAgent`) exposes the same stages to the Google Agent stack. Demo and live modes share every code path except the two client implementations.

**Tech Stack:** Python 3.11+, Pydantic v2, Jinja2, httpx, pytest + pytest-asyncio; `google-adk` and `google-genai` behind a `cloud` extra.

**Spec:** `docs/superpowers/specs/2026-08-15-clearframe-design.md`

## Global Constraints

- Python `>=3.11`; src layout (`src/clearframe/`).
- Pydantic v2 APIs only (`model_validate`, `model_dump`), no v1 idioms.
- Core modules (`models`, `scoring`, `triage`, `exporters`, `pipeline`) must not import `google.*` — cloud deps live only in `integrations/` live clients and `adk/`.
- Every risk score must be reproducible from stored inputs (no LLM in scoring path).
- Demo mode must run with zero network and zero credentials.
- MIT license file at repo root.
- Commit after every task (green tests) with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
pyproject.toml, LICENSE, README.md
src/clearframe/
  __init__.py, models.py, scoring.py, triage.py, timecode.py, store.py, pipeline.py, cli.py, __main__.py
  integrations/__init__.py, gemini_client.py, parallel_client.py
  integrations/fixtures/demo_scene.json, research/*.json
  stages/__init__.py, scan.py, triage_stage.py, research.py, risk.py, remediation.py, dossier.py
  exporters/__init__.py, edl.py, csv_markers.py, dossier_html.py
  adk/__init__.py, agents.py
tests/  (one test module per source module)
```

---

### Task 1: Project scaffold + domain models

**Files:**
- Create: `pyproject.toml`, `LICENSE` (MIT), `README.md` (stub), `.gitignore`, `src/clearframe/__init__.py`, `src/clearframe/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces (used by every later task):
  - Enums: `ElementType{LOGO,ARTWORK,MUSIC,FACE,TATTOO,LOCATION,TEXT}`, `ClearanceCategory{TRADEMARK,COPYRIGHT_ART,MUSIC_SYNC,RIGHT_OF_PUBLICITY,LOCATION,TEXT_ON_SCREEN}`, `RiskBand{LOW,MEDIUM,HIGH,CRITICAL}`, `LicensingPosture{PERMISSIVE,STANDARD,LITIGIOUS,UNKNOWN}`
  - `TimeRange(start_s: float, end_s: float)` — validates `end_s > start_s >= 0`; property `duration_s`.
  - `Prominence(screen_time_s: float, frame_coverage: float, centrality: float, plot_integral: bool)` — coverage/centrality in `[0,1]`.
  - `DetectedElement(id: str, label: str, element_type: ElementType, description: str, time_ranges: list[TimeRange], prominence: Prominence)`
  - `TriagedElement(DetectedElement + category: ClearanceCategory)`
  - `BasisCitation(field: str, url: str, excerpt: str, reasoning: str, confidence: str)`
  - `ResearchResult(element_id: str, owner: str|None, owner_confidence: str, licensing_contact: str|None, licensing_posture: LicensingPosture, litigation_history: list[str], estimated_license_cost_band: str|None, basis: list[BasisCitation], status: Literal["complete","incomplete"])`
  - `RiskAssessment(element_id: str, score: int, band: RiskBand, factors: dict[str, float], de_minimis: bool)`
  - `RemediationOption(kind: Literal["license","blur","reshoot","fair_use_memo"], summary: str, detail: str, est_cost_band: str|None)`
  - `Decision(element_id: str, action: Literal["approve_risk","license","blur","reshoot","escalate"], reviewer: str, role: str, note: str)`
  - `Production(id: str, title: str, footage_uri: str, fps: float = 24.0, duration_s: float)`
  - `ProductionState(production: Production, stage_status: dict[str, str], detections: list[DetectedElement], elements: list[TriagedElement], research: dict[str, ResearchResult], risk: dict[str, RiskAssessment], remediation: dict[str, list[RemediationOption]], decisions: dict[str, Decision], unscanned_ranges: list[TimeRange])` — all collections default empty.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "clearframe"
version = "0.1.0"
description = "Autonomous rights-clearance pipeline for film & TV (Gemini + Parallel)"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = ["pydantic>=2.7", "jinja2>=3.1", "httpx>=0.27"]

[project.optional-dependencies]
cloud = ["google-adk>=1.0", "google-genai>=1.0"]
dev = ["pytest>=8", "pytest-asyncio>=0.23"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/clearframe"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

MIT `LICENSE` with `Copyright (c) 2026 ClearFrame contributors`. `.gitignore`: `__pycache__/`, `*.egg-info/`, `.venv/`, `out/`, `.pytest_cache/`. `README.md` stub: one paragraph + "docs/ for spec".

- [ ] **Step 2: Write failing model tests** — `tests/test_models.py`

```python
import pytest
from pydantic import ValidationError
from clearframe.models import (TimeRange, Prominence, DetectedElement, ElementType,
                               ProductionState, Production)

def test_time_range_validates_order():
    with pytest.raises(ValidationError):
        TimeRange(start_s=5.0, end_s=2.0)

def test_time_range_duration():
    assert TimeRange(start_s=1.0, end_s=3.5).duration_s == 2.5

def test_prominence_bounds():
    with pytest.raises(ValidationError):
        Prominence(screen_time_s=1, frame_coverage=1.5, centrality=0.5, plot_integral=False)

def test_production_state_roundtrip():
    state = ProductionState(production=Production(
        id="p1", title="Demo", footage_uri="demo://scene", duration_s=62.0))
    data = state.model_dump_json()
    assert ProductionState.model_validate_json(data).production.title == "Demo"
```

- [ ] **Step 3: Run to verify failure** — `pip install -e ".[dev]" && pytest tests/test_models.py -v` → FAIL (module missing).

- [ ] **Step 4: Implement `src/clearframe/models.py`** with the exact interfaces above. `TimeRange` order check via `@model_validator(mode="after")`; bounds via `Field(ge=0, le=1)`; `duration_s` as `@property`. `__init__.py`: `__version__ = "0.1.0"`.

- [ ] **Step 5: Run tests → PASS, then commit** — `git add -A && git commit -m "feat: scaffold project and domain models"`.

---

### Task 2: Deterministic risk scoring engine

**Files:**
- Create: `src/clearframe/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `TriagedElement`, `ResearchResult`, `RiskAssessment`, enums (Task 1).
- Produces: `score_element(element: TriagedElement, research: ResearchResult | None) -> RiskAssessment`; constants `CATEGORY_WEIGHT: dict[ClearanceCategory, float]`, `POSTURE_FACTOR: dict[LicensingPosture, float]`.

**Rubric (exact, from spec §3.1 stage 4):**
- `screen_time_norm = min(prominence.screen_time_s / 10.0, 1.0)`
- `prominence_score = 0.4*screen_time_norm + 0.3*frame_coverage + 0.2*centrality + (0.1 if plot_integral else 0.0)`
- `CATEGORY_WEIGHT`: MUSIC_SYNC 1.0, COPYRIGHT_ART 0.9, RIGHT_OF_PUBLICITY 0.9, TRADEMARK 0.8, TEXT_ON_SCREEN 0.6, LOCATION 0.5
- `POSTURE_FACTOR`: LITIGIOUS 1.0, STANDARD 0.7, UNKNOWN 0.7, PERMISSIVE 0.4; `research is None` or `status=="incomplete"` → UNKNOWN factor.
- `score = round(100 * prominence_score * weight * posture_factor)`
- De minimis: `screen_time_s < 2.0 and frame_coverage < 0.05 and centrality < 0.3 and not plot_integral` → `de_minimis=True` and band capped at LOW.
- Bands: `<20` LOW, `<45` MEDIUM, `<70` HIGH, else CRITICAL.
- `factors` dict records: `screen_time_norm`, `prominence_score`, `category_weight`, `posture_factor` (rounded to 3 dp).

- [ ] **Step 1: Write failing golden tests** — `tests/test_scoring.py`

```python
from clearframe.models import (TriagedElement, ElementType, ClearanceCategory, TimeRange,
                               Prominence, ResearchResult, LicensingPosture, RiskBand)
from clearframe.scoring import score_element

def make_element(**kw):
    base = dict(id="e1", label="x", element_type=ElementType.MUSIC,
                description="", time_ranges=[TimeRange(start_s=0, end_s=12)],
                category=ClearanceCategory.MUSIC_SYNC,
                prominence=Prominence(screen_time_s=12, frame_coverage=0.0,
                                      centrality=1.0, plot_integral=True))
    base.update(kw)
    return TriagedElement(**base)

def make_research(posture=LicensingPosture.LITIGIOUS, status="complete"):
    return ResearchResult(element_id="e1", owner="X Corp", owner_confidence="high",
                          licensing_contact="a@b.c", licensing_posture=posture,
                          litigation_history=[], estimated_license_cost_band=None,
                          basis=[], status=status)

def test_prominent_litigious_song_is_critical():
    r = score_element(make_element(), make_research())
    assert r.score == 70 and r.band == RiskBand.CRITICAL

def test_de_minimis_background_face_capped_low():
    el = make_element(element_type=ElementType.FACE,
                      category=ClearanceCategory.RIGHT_OF_PUBLICITY,
                      prominence=Prominence(screen_time_s=1.2, frame_coverage=0.03,
                                            centrality=0.2, plot_integral=False))
    r = score_element(el, make_research(LicensingPosture.UNKNOWN))
    assert r.de_minimis is True and r.band == RiskBand.LOW

def test_missing_research_uses_unknown_posture():
    r = score_element(make_element(), None)
    assert r.factors["posture_factor"] == 0.7

def test_band_boundaries():
    from clearframe.scoring import band_for
    assert band_for(19) == RiskBand.LOW and band_for(20) == RiskBand.MEDIUM
    assert band_for(44) == RiskBand.MEDIUM and band_for(45) == RiskBand.HIGH
    assert band_for(69) == RiskBand.HIGH and band_for(70) == RiskBand.CRITICAL
```

- [ ] **Step 2: Run → FAIL** (`scoring` missing).
- [ ] **Step 3: Implement `scoring.py`** exactly per rubric; expose `band_for(score: int) -> RiskBand`.
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** — `"feat: deterministic risk scoring engine"`.

---

### Task 3: Triage rules + duplicate merge

**Files:**
- Create: `src/clearframe/triage.py`
- Test: `tests/test_triage.py`

**Interfaces:**
- Produces: `triage(detections: list[DetectedElement]) -> list[TriagedElement]`; `CATEGORY_RULES: dict[ElementType, ClearanceCategory]`.
- Rules: LOGO→TRADEMARK, ARTWORK→COPYRIGHT_ART, MUSIC→MUSIC_SYNC, FACE→RIGHT_OF_PUBLICITY, TATTOO→COPYRIGHT_ART, LOCATION→LOCATION, TEXT→TEXT_ON_SCREEN.
- Dedupe: group by `(element_type, label.casefold().strip())`; merged element keeps first id/description, concatenates+sorts time_ranges, prominence = sum of screen_time_s, max coverage, max centrality, OR of plot_integral.

- [ ] **Step 1: Failing tests**

```python
from clearframe.models import DetectedElement, ElementType, TimeRange, Prominence, ClearanceCategory
from clearframe.triage import triage

def det(id, label, t, start, end, st=2.0, cov=0.1, cen=0.5, plot=False):
    return DetectedElement(id=id, label=label, element_type=t, description="d",
        time_ranges=[TimeRange(start_s=start, end_s=end)],
        prominence=Prominence(screen_time_s=st, frame_coverage=cov, centrality=cen, plot_integral=plot))

def test_tattoo_maps_to_copyright():
    out = triage([det("a", "tribal tattoo", ElementType.TATTOO, 0, 2)])
    assert out[0].category == ClearanceCategory.COPYRIGHT_ART

def test_duplicates_merge_across_shots():
    out = triage([det("a", "Nike hoodie", ElementType.LOGO, 0, 5, st=5),
                  det("b", "nike hoodie ", ElementType.LOGO, 20, 30, st=10, cov=0.2, plot=True)])
    assert len(out) == 1
    merged = out[0]
    assert merged.prominence.screen_time_s == 15
    assert merged.prominence.frame_coverage == 0.2
    assert merged.prominence.plot_integral is True
    assert [r.start_s for r in merged.time_ranges] == [0, 20]
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: triage rules and duplicate merge"`.

---

### Task 4: Timecode + marker exporters (EDL + CSV)

**Files:**
- Create: `src/clearframe/timecode.py`, `src/clearframe/exporters/__init__.py`, `src/clearframe/exporters/edl.py`, `src/clearframe/exporters/csv_markers.py`
- Test: `tests/test_timecode.py`, `tests/test_edl.py`, `tests/test_csv_markers.py`

**Interfaces:**
- `timecode.seconds_to_tc(seconds: float, fps: float = 24.0, offset_s: float = 3600.0) -> str` — `HH:MM:SS:FF`, frames = `round((seconds+offset_s)*fps)` then div/mod (offset gives the standard 01:00:00:00 timeline start).
- `edl.render_edl(title: str, entries: list[MarkerEntry], fps: float) -> str` where `MarkerEntry(start_s: float, end_s: float, label: str, band: RiskBand, category: ClearanceCategory)` (dataclass in `edl.py`, re-exported by `csv_markers`).
- Band→Resolve color: CRITICAL→RED, HIGH→YELLOW, MEDIUM→CYAN, LOW→GREEN.
- EDL format (CMX3600 with locator lines, importable via Resolve "Timeline Markers from EDL"):

```
TITLE: <title>
FCM: NON-DROP FRAME

001  001      V     C        01:00:12:00 01:00:12:01 01:00:12:00 01:00:12:01
* LOC: 01:00:12:00 RED CRITICAL|MUSIC_SYNC|Blinding Lights - The Weeknd
```

(one numbered event per marker at its start timecode, duration 1 frame; locator carries `BAND|CATEGORY|label`.)
- `csv_markers.render_csv(entries: list[MarkerEntry], fps: float) -> str` — header `timecode_in,timecode_out,label,category,risk_band` plus one row per entry, RFC-4180 quoting via `csv` module, `\r\n` line endings.
- Both: `elements_to_markers(elements: list[TriagedElement], risk: dict[str, RiskAssessment]) -> list[MarkerEntry]` in `edl.py` — one marker per TimeRange, label = element label, sorted by start.

- [ ] **Step 1: Failing tests** (all three files)

```python
# tests/test_timecode.py
from clearframe.timecode import seconds_to_tc
def test_basic():
    assert seconds_to_tc(12.5, fps=24, offset_s=0) == "00:00:12:12"
def test_default_hour_offset():
    assert seconds_to_tc(0) == "01:00:00:00"

# tests/test_edl.py
from clearframe.exporters.edl import render_edl, MarkerEntry
from clearframe.models import RiskBand, ClearanceCategory
def test_edl_golden():
    e = MarkerEntry(start_s=12.0, end_s=14.0, label="Blinding Lights - The Weeknd",
                    band=RiskBand.CRITICAL, category=ClearanceCategory.MUSIC_SYNC)
    out = render_edl("ClearFrame Risk Markers", [e], fps=24)
    assert out.splitlines()[0] == "TITLE: ClearFrame Risk Markers"
    assert "* LOC: 01:00:12:00 RED CRITICAL|MUSIC_SYNC|Blinding Lights - The Weeknd" in out

# tests/test_csv_markers.py
from clearframe.exporters.edl import MarkerEntry
from clearframe.exporters.csv_markers import render_csv
from clearframe.models import RiskBand, ClearanceCategory
def test_csv_golden():
    e = MarkerEntry(start_s=1.0, end_s=2.0, label='Poster, "Tranquility"',
                    band=RiskBand.MEDIUM, category=ClearanceCategory.COPYRIGHT_ART)
    rows = render_csv([e], fps=24).split("\r\n")
    assert rows[0] == "timecode_in,timecode_out,label,category,risk_band"
    assert rows[1] == '01:00:01:00,01:00:02:00,"Poster, ""Tranquility""",COPYRIGHT_ART,MEDIUM'
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement all three modules.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: timecode and EDL/CSV marker exporters"`.

---

### Task 5: Parallel Task API client (parser + fixture + live)

**Files:**
- Create: `src/clearframe/integrations/__init__.py`, `src/clearframe/integrations/parallel_client.py`
- Test: `tests/test_parallel_client.py`

**Interfaces:**
- `ParallelClient` protocol: `async def research(self, element: TriagedElement, production_title: str) -> ResearchResult`.
- `parse_task_output(element_id: str, output: dict) -> ResearchResult` — parses Parallel Task API result `output` object: `content` (fields per our task schema) + `basis` list (`{"field", "citations":[{"url","excerpts":[...]}], "reasoning", "confidence"}` → flattened to one `BasisCitation` per (field, citation) with first excerpt or `""`). `status="incomplete"` when `content.owner` is null/missing; unknown posture strings → `LicensingPosture.UNKNOWN`.
- `RESEARCH_OUTPUT_SCHEMA: dict` — JSON schema sent as `task_spec.output_schema.json_schema`: object with properties `owner` (string|null), `owner_confidence` (enum low/medium/high), `licensing_contact` (string|null), `licensing_posture` (enum permissive/standard/litigious/unknown), `litigation_history` (array of string), `estimated_license_cost_band` (string|null).
- `build_research_input(element, production_title) -> str` — the research prompt: identifies the element (label, description, category) and asks who owns it, licensing contact, posture, litigation history, typical cost band for indie film licensing.
- `LiveParallelClient(api_key: str, base_url: str = "https://api.parallel.ai", processor: str = "pro")` — httpx.AsyncClient; `POST /v1/tasks/runs` (headers `{"x-api-key": key}`, body `{"input": ..., "processor": ..., "task_spec": {"output_schema": {"type": "json", "json_schema": RESEARCH_OUTPUT_SCHEMA}}}`); poll `GET /v1/tasks/runs/{run_id}` every 10s until `status in {"completed","failed"}` (max 10 min); `GET /v1/tasks/runs/{run_id}/result` → `parse_task_output`. On failure/timeout return `ResearchResult(..., status="incomplete", owner=None, posture=UNKNOWN)` — never raise into the pipeline. *(Executor: verify endpoint/field names against docs.parallel.ai before live use; parser is shape-tolerant via `.get`.)*
- `FixtureParallelClient(fixtures_dir: Path)` — loads `research/{slug(label)}.json` (the stored `output` object) through the same `parse_task_output`; missing file → incomplete result. `slug`: casefold, alnum→keep, spaces→`-`.

- [ ] **Step 1: Failing tests**

```python
import pytest
from pathlib import Path
from clearframe.integrations.parallel_client import parse_task_output, FixtureParallelClient, slug
from clearframe.models import LicensingPosture

SAMPLE = {
  "content": {"owner": "The Weeknd XO, Inc. / Universal Music Group",
              "owner_confidence": "high", "licensing_contact": "sync@umusic.com",
              "licensing_posture": "litigious",
              "litigation_history": ["Multiple sync infringement claims 2019-2024"],
              "estimated_license_cost_band": "$50k-$250k"},
  "basis": [{"field": "owner",
             "citations": [{"url": "https://www.umusicpub.com/", "excerpts": ["Universal Music Publishing Group administers…"]}],
             "reasoning": "Publisher listing confirms administration.",
             "confidence": "high"}]}

def test_parse_complete_output():
    r = parse_task_output("e1", SAMPLE)
    assert r.status == "complete" and r.licensing_posture == LicensingPosture.LITIGIOUS
    assert r.basis[0].url.startswith("https://www.umusicpub.com")

def test_parse_missing_owner_marks_incomplete():
    r = parse_task_output("e1", {"content": {"owner": None}, "basis": []})
    assert r.status == "incomplete" and r.licensing_posture == LicensingPosture.UNKNOWN

def test_slug():
    assert slug("Blinding Lights - The Weeknd") == "blinding-lights-the-weeknd"

async def test_fixture_client_missing_file_is_incomplete(tmp_path):
    from clearframe.models import TriagedElement, ElementType, ClearanceCategory, TimeRange, Prominence
    el = TriagedElement(id="e9", label="Unknown Mural", element_type=ElementType.ARTWORK,
        description="", category=ClearanceCategory.COPYRIGHT_ART,
        time_ranges=[TimeRange(start_s=0, end_s=1)],
        prominence=Prominence(screen_time_s=1, frame_coverage=0.1, centrality=0.1, plot_integral=False))
    (tmp_path / "research").mkdir()
    r = await FixtureParallelClient(tmp_path).research(el, "Demo")
    assert r.status == "incomplete"
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: Parallel Task API client with fixture mode"`.

---

### Task 6: Gemini scan client (parser + fixture) + demo scene fixture

**Files:**
- Create: `src/clearframe/integrations/gemini_client.py`, `src/clearframe/integrations/fixtures/demo_scene.json`
- Test: `tests/test_gemini_client.py`

**Interfaces:**
- `GeminiClient` protocol: `async def scan(self, footage_uri: str, duration_s: float) -> ScanResult`; `ScanResult(detections: list[DetectedElement], unscanned_ranges: list[TimeRange])` (Pydantic model in this module).
- `parse_scan_payload(payload: dict) -> ScanResult` — validates `{"elements": [...], "unscanned_ranges": [...]}` via the Task-1 models; invalid element entries are skipped and counted, never crash (spec §6: fail loud happens at re-prompt layer in live mode, Phase 2).
- `FixtureGeminiClient(fixtures_dir: Path)` — `scan()` loads `demo_scene.json`.
- `SCAN_PROMPT: str` and `SCAN_RESPONSE_SCHEMA: dict` defined now (used by Phase-2 live client): prompt instructs Gemini to act as a clearance coordinator watching footage and return every clearable element with timestamps and prominence estimates.
- `demo_scene.json` — exactly these six detections (ids `e1`–`e6`), for a 62s demo scene `demo://salted-scene`:
  1. `e1` "Blinding Lights - The Weeknd" MUSIC, 12–24s, prominence: st 12, cov 0.0, cen 1.0, plot true — audible from phone speaker.
  2. `e2` "Coca-Cola can" LOGO, 5–11s, st 6, cov 0.08, cen 0.6, plot false.
  3. `e3` "Nike hoodie swoosh" LOGO, ranges 8–18s & 40–45s, st 15, cov 0.12, cen 0.7, plot false.
  4. `e4` "Arctic Monkeys tour poster" ARTWORK, 20–25s, st 5, cov 0.2, cen 0.6, plot false.
  5. `e5` "Street mural (unknown artist)" ARTWORK, 30–36s, st 6, cov 0.3, cen 0.5, plot false.
  6. `e6` "Background passerby face" FACE, 47–48.2s, st 1.2, cov 0.03, cen 0.2, plot false.
  Plus `"unscanned_ranges": []`.

- [ ] **Step 1: Failing tests**

```python
from pathlib import Path
from clearframe.integrations.gemini_client import parse_scan_payload, FixtureGeminiClient

FIXTURES = Path("src/clearframe/integrations/fixtures")

async def test_fixture_scan_returns_six_elements():
    result = await FixtureGeminiClient(FIXTURES).scan("demo://salted-scene", 62.0)
    assert len(result.detections) == 6
    labels = [d.label for d in result.detections]
    assert "Blinding Lights - The Weeknd" in labels

def test_parser_skips_invalid_entries():
    payload = {"elements": [{"label": "broken"}], "unscanned_ranges": []}
    assert parse_scan_payload(payload).detections == []
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement module + write the fixture JSON with the exact values above.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: Gemini scan client with demo scene fixture"`.

---

### Task 7: Research fixtures + remediation drafter

**Files:**
- Create: `src/clearframe/integrations/fixtures/research/` — five JSON files; `src/clearframe/remediation.py`
- Test: `tests/test_remediation.py` (+ extend `tests/test_parallel_client.py` with one fixture-load test)

**Research fixtures** (each is a Parallel `output` object: `content` + `basis` with ≥1 real-looking citation; `blinding-lights-the-weeknd.json` uses the SAMPLE payload from Task 5):
- `blinding-lights-the-weeknd.json` — owner "The Weeknd XO, Inc. / Universal Music Group", litigious, contact sync@umusic.com, cost "$50k-$250k".
- `coca-cola-can.json` — "The Coca-Cola Company", standard, brand.clearance@coca-cola.com, history [], cost "$0 (product placement) - $15k".
- `nike-hoodie-swoosh.json` — "Nike, Inc.", litigious, history ["Aggressive trademark enforcement program; hundreds of USPTO oppositions"], cost "no paid clearance program; typically denied — blur recommended".
- `arctic-monkeys-tour-poster.json` — "Domino Recording Co. (artwork) / poster designer", standard, licensing@dominomusic.com, cost "$500-$5k".
- `street-mural-unknown-artist.json` — content owner null → parses incomplete (VARA/mural copyright note in reasoning).
- (`background-passerby-face` has NO fixture file → exercises the missing-file→incomplete path.)

**Interfaces:**
- `remediation.draft_options(element: TriagedElement, research: ResearchResult, risk: RiskAssessment, production: Production) -> list[RemediationOption]` — deterministic templates:
  - license option when `research.licensing_contact` — detail = full outreach email (To/Subject/body with production title, element label, first timecode range via `seconds_to_tc`, usage description, cost band).
  - blur option always for visual categories (not MUSIC_SYNC): est cost band by coverage (`<0.1` → "$300-$800/shot", else "$800-$2500/shot").
  - `fair_use_memo` option when `risk.de_minimis` — detail = short de-minimis memo paragraph citing fleeting/incidental use.
  - `reshoot` option when `risk.band == CRITICAL`.
  - MUSIC_SYNC gets license (or escalate note inside license detail if no contact) — never blur.
  - Order: license, blur, reshoot, fair_use_memo (only those applicable).

- [ ] **Step 1: Failing tests**

```python
from clearframe.remediation import draft_options
from clearframe.models import (TriagedElement, ElementType, ClearanceCategory, TimeRange,
    Prominence, ResearchResult, LicensingPosture, RiskAssessment, RiskBand, Production)

PROD = Production(id="p1", title="Golden Hour", footage_uri="demo://x", duration_s=62)

def _el(cat=ClearanceCategory.TRADEMARK, t=ElementType.LOGO):
    return TriagedElement(id="e1", label="Nike hoodie swoosh", element_type=t, description="",
        category=cat, time_ranges=[TimeRange(start_s=8, end_s=18)],
        prominence=Prominence(screen_time_s=15, frame_coverage=0.12, centrality=0.7, plot_integral=False))

def _res():
    return ResearchResult(element_id="e1", owner="Nike, Inc.", owner_confidence="high",
        licensing_contact="tm@nike.com", licensing_posture=LicensingPosture.LITIGIOUS,
        litigation_history=[], estimated_license_cost_band="denied", basis=[], status="complete")

def _risk(band=RiskBand.HIGH, dm=False):
    return RiskAssessment(element_id="e1", score=50, band=band, factors={}, de_minimis=dm)

def test_license_email_contains_production_and_timecode():
    opts = draft_options(_el(), _res(), _risk(), PROD)
    lic = next(o for o in opts if o.kind == "license")
    assert "Golden Hour" in lic.detail and "01:00:08:00" in lic.detail

def test_music_never_gets_blur():
    el = _el(cat=ClearanceCategory.MUSIC_SYNC, t=ElementType.MUSIC)
    kinds = [o.kind for o in draft_options(el, _res(), _risk(RiskBand.CRITICAL), PROD)]
    assert "blur" not in kinds and "reshoot" in kinds

def test_de_minimis_gets_fair_use_memo():
    kinds = [o.kind for o in draft_options(_el(), _res(), _risk(RiskBand.LOW, dm=True), PROD)]
    assert "fair_use_memo" in kinds
```

Extend `tests/test_parallel_client.py`:

```python
async def test_real_fixture_dir_loads_weeknd():
    from clearframe.integrations.parallel_client import FixtureParallelClient
    # element labeled "Blinding Lights - The Weeknd" → litigious, complete
```

(full test body: build element as in Task 5 pattern with that label, assert `status=="complete"` and posture LITIGIOUS against `src/clearframe/integrations/fixtures`.)

- [ ] **Step 2: Run → FAIL.** **Step 3: Write five fixture JSONs + implement `remediation.py`.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: research fixtures and remediation drafter"`.

---

### Task 8: Store + pipeline orchestrator + stages

**Files:**
- Create: `src/clearframe/store.py`, `src/clearframe/pipeline.py`, `src/clearframe/stages/__init__.py`, `stages/scan.py`, `stages/triage_stage.py`, `stages/research.py`, `stages/risk.py`, `stages/remediation.py`
- Test: `tests/test_store.py`, `tests/test_pipeline.py`

**Interfaces:**
- `store.LocalJsonStore(root: Path)`: `save(state: ProductionState) -> None` (writes `{root}/{production.id}.json`, atomic via temp+rename), `load(production_id: str) -> ProductionState`.
- `pipeline.PipelineContext` (dataclass): `state: ProductionState`, `gemini: GeminiClient`, `parallel: ParallelClient`, `store: LocalJsonStore`.
- `pipeline.Stage` protocol: `name: str`; `async def run(self, ctx: PipelineContext) -> None` (mutates `ctx.state`).
- `pipeline.Pipeline(stages: list[Stage])`: `async def run(self, ctx) -> ProductionState` — for each stage: skip if `state.stage_status[stage.name] == "complete"` (resumability), else run, set status `"complete"`, `store.save(state)`. After the five analysis stages it sets `state.stage_status["review"] = "awaiting"` (dossier stage is invoked separately — spec §3.1 human gate).
- Stage names/behavior (each stage a small class):
  - `ScanStage` (`"scan"`): `ctx.gemini.scan(...)` → `state.detections`, `state.unscanned_ranges`.
  - `TriageStage` (`"triage"`): `triage(state.detections)` → `state.elements`.
  - `ResearchStage` (`"research"`): `asyncio.gather` over elements → `state.research[element.id]` (concurrent fan-out per spec §3.1 stage 3).
  - `RiskStage` (`"risk"`): `score_element` per element → `state.risk`.
  - `RemediationStage` (`"remediation"`): `draft_options` per element → `state.remediation`.
- `pipeline.build_demo_pipeline() -> list[Stage]` and `pipeline.demo_context(out_root: Path) -> PipelineContext` (fixture clients, demo `Production(id="demo", title="Golden Hour", footage_uri="demo://salted-scene", duration_s=62.0)`).

- [ ] **Step 1: Failing tests**

```python
# tests/test_store.py
from pathlib import Path
from clearframe.store import LocalJsonStore
from clearframe.models import ProductionState, Production
def test_save_load_roundtrip(tmp_path):
    store = LocalJsonStore(tmp_path)
    s = ProductionState(production=Production(id="p1", title="T", footage_uri="u", duration_s=1))
    store.save(s)
    assert store.load("p1").production.title == "T"

# tests/test_pipeline.py
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.models import RiskBand

async def test_demo_pipeline_end_to_end(tmp_path):
    ctx = demo_context(tmp_path)
    state = await Pipeline(build_demo_pipeline()).run(ctx)
    assert len(state.elements) == 6
    assert state.risk["e1"].band == RiskBand.CRITICAL          # Weeknd track
    assert state.research["e5"].status == "incomplete"          # mural
    assert state.risk["e6"].de_minimis is True                  # passerby face
    assert all(state.remediation[e.id] for e in state.elements)
    assert state.stage_status["review"] == "awaiting"

async def test_pipeline_resumes_skipping_complete_stages(tmp_path):
    ctx = demo_context(tmp_path)
    p = Pipeline(build_demo_pipeline())
    await p.run(ctx)
    ctx.state.detections = []          # would change results if scan re-ran
    state = await p.run(ctx)           # all stages complete → no-op
    assert len(state.elements) == 6
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement store, pipeline, five stage classes.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: pipeline orchestrator with resumable stages"`.

---

### Task 9: Dossier builder + HTML renderer

**Files:**
- Create: `src/clearframe/dossier.py`, `src/clearframe/exporters/dossier_html.py`, `src/clearframe/stages/dossier.py`
- Test: `tests/test_dossier.py`

**Interfaces:**
- `dossier.DossierEntry` (Pydantic): `element: TriagedElement`, `research: ResearchResult | None`, `risk: RiskAssessment`, `options: list[RemediationOption]`, `decision: Decision | None`.
- `dossier.ClearanceDossier` (Pydantic): `production: Production`, `generated_at: str` (ISO, passed in — never `datetime.now()` inside builders; caller supplies), `entries: list[DossierEntry]` (sorted score desc), `summary: dict[str, int]` (count per band + `"incomplete_research"` + `"pending_decisions"`), `unscanned_ranges: list[TimeRange]`, `disclaimer: str` (fixed constant: decision-support, not legal advice).
- `dossier.build_dossier(state: ProductionState, generated_at: str) -> ClearanceDossier`.
- `dossier.auto_decisions(state: ProductionState) -> dict[str, Decision]` — demo/auto-approve map by band: LOW→approve_risk, MEDIUM/HIGH→license, CRITICAL→license, research incomplete→escalate; reviewer `"auto-demo"`, role `"legal"`.
- `dossier_html.render_dossier_html(d: ClearanceDossier) -> str` — Jinja2 `Template` from module-level string; print-ready single page: header (production, date, disclaimer), summary band table, per-entry cards (label, category chip, band chip with color, score + factor breakdown, timecode ranges, owner + contact, litigation history, **basis citations as links with excerpt + confidence**, remediation options incl. email draft in `<pre>`, decision line or PENDING). Inline CSS only, band colors: CRITICAL `#c0392b`, HIGH `#e67e22`, MEDIUM `#2980b9`, LOW `#27ae60`.
- `stages/dossier.py` → `DossierStage` (`"dossier"`): runs `build_dossier` + renderers, writes `dossier.html`, `dossier.json`, `markers.edl`, `markers.csv` into an `out_dir: Path` given at construction; requires decisions present for all elements (else raises `ReviewPendingError`).

- [ ] **Step 1: Failing tests**

```python
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
from clearframe.dossier import build_dossier, auto_decisions
from clearframe.exporters.dossier_html import render_dossier_html

async def _ran_state(tmp_path):
    ctx = demo_context(tmp_path)
    return await Pipeline(build_demo_pipeline()).run(ctx)

async def test_dossier_sorted_and_summarised(tmp_path):
    state = await _ran_state(tmp_path)
    state.decisions = auto_decisions(state)
    d = build_dossier(state, generated_at="2026-08-15T12:00:00Z")
    assert d.entries[0].element.id == "e1"                 # highest score first
    assert d.summary["CRITICAL"] == 1 and d.summary["incomplete_research"] == 2

async def test_html_contains_citations_and_disclaimer(tmp_path):
    state = await _ran_state(tmp_path)
    state.decisions = auto_decisions(state)
    html = render_dossier_html(build_dossier(state, generated_at="2026-08-15T12:00:00Z"))
    assert "umusicpub.com" in html and "not legal advice" in html.lower()

async def test_dossier_stage_requires_decisions(tmp_path):
    import pytest
    from clearframe.stages.dossier import DossierStage, ReviewPendingError
    from clearframe.pipeline import PipelineContext
    state = await _ran_state(tmp_path)
    stage = DossierStage(out_dir=tmp_path / "out")
    ctx = demo_context(tmp_path); ctx.state = state
    with pytest.raises(ReviewPendingError):
        await stage.run(ctx)
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement.** **Step 4: Run → PASS.** **Step 5: Commit** `"feat: clearance dossier builder and HTML/export stage"`.

---

### Task 10: CLI + end-to-end demo

**Files:**
- Create: `src/clearframe/cli.py`, `src/clearframe/__main__.py`
- Modify: `README.md` (real quickstart)
- Test: `tests/test_cli.py`

**Interfaces:**
- `python -m clearframe run --demo --out ./out [--auto-approve]` — argparse; runs demo pipeline; with `--auto-approve` applies `auto_decisions` and runs `DossierStage`; prints a summary table (label, band, score, owner, action) and output file paths; exit 0. Without `--auto-approve`, prints "review pending" + element table, exit 0.
- `cli.main(argv: list[str] | None = None) -> int`; `__main__.py` calls `sys.exit(main())`.
- `generated_at` comes from `datetime.now(timezone.utc).isoformat()` in `cli.py` (the only clock call in the codebase).

- [ ] **Step 1: Failing test**

```python
from clearframe.cli import main

def test_cli_demo_auto_approve(tmp_path, capsys):
    rc = main(["run", "--demo", "--out", str(tmp_path), "--auto-approve"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CRITICAL" in out
    assert (tmp_path / "dossier.html").exists()
    assert (tmp_path / "markers.edl").exists()
    assert (tmp_path / "markers.csv").exists()
    assert (tmp_path / "dossier.json").exists()
```

- [ ] **Step 2: Run → FAIL.** **Step 3: Implement CLI; update README** (what it is, demo quickstart `pip install -e ".[dev]" && python -m clearframe run --demo --out out --auto-approve`, architecture sketch, license note). **Step 4: Run full suite `pytest -v` → ALL PASS.** **Step 5: Commit** `"feat: CLI with end-to-end demo mode"`.

---

### Task 11: ADK adapter (SequentialAgent pipeline) + smoke test

**Files:**
- Create: `src/clearframe/adk/__init__.py`, `src/clearframe/adk/agents.py`
- Test: `tests/test_adk_pipeline.py`

**Interfaces:**
- `adk.agents.build_clearframe_agent(ctx: PipelineContext, out_dir: Path) -> SequentialAgent` — wraps each Phase-1 stage in a `StageAgent(BaseAgent)` whose `_run_async_impl` runs the stage against `ctx` and yields one `Event` with `state_delta={"clearframe:"+stage.name: "complete"}`; sub-agents in spec order: scan, triage, research, risk, remediation, dossier (dossier variant applies `auto_decisions` first when `state.decisions` empty — flagged `auto_approve=True` param).
- Runs under `google.adk.runners.Runner` with `InMemorySessionService`.
- Test uses `pytest.importorskip("google.adk")` so the suite passes without the `cloud` extra.
- *(Executor note: `google-adk` v1.x API — `BaseAgent` is a Pydantic model; set `model_config = ConfigDict(arbitrary_types_allowed=True)` and declare `stage`/`pipeline_ctx` as fields. Verify `Event(author=...)`/`EventActions(state_delta=...)` signatures against the installed version and adapt mechanically; the stage logic itself must not change.)*

- [ ] **Step 1: Failing smoke test**

```python
import pytest
from pathlib import Path
adk = pytest.importorskip("google.adk")

async def test_adk_sequential_pipeline_produces_dossier(tmp_path):
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    from clearframe.pipeline import demo_context
    from clearframe.adk.agents import build_clearframe_agent

    ctx = demo_context(tmp_path)
    agent = build_clearframe_agent(ctx, out_dir=tmp_path / "out", auto_approve=True)
    svc = InMemorySessionService()
    await svc.create_session(app_name="clearframe", user_id="u", session_id="s")
    runner = Runner(agent=agent, app_name="clearframe", session_service=svc)
    events = [e async for e in runner.run_async(
        user_id="u", session_id="s",
        new_message=types.Content(role="user", parts=[types.Part(text="run")]))]
    assert (tmp_path / "out" / "dossier.html").exists()
    session = await svc.get_session(app_name="clearframe", user_id="u", session_id="s")
    assert session.state.get("clearframe:dossier") == "complete"
```

- [ ] **Step 2: `pip install -e ".[dev,cloud]"`, run → FAIL** (module missing). If the cloud extra cannot install, mark task blocked and stop — do not fake it.
- [ ] **Step 3: Implement `adk/agents.py`.** **Step 4: Run full suite → ALL PASS.** **Step 5: Commit** `"feat: ADK SequentialAgent wrapper for pipeline"`.

---

## Self-Review (completed)

1. **Spec coverage:** §3.1 stages 1–6 → Tasks 6,3,5,2,7,9; §3.4 modes → fixture clients (5,6) + live Parallel (5); §4 data model → Task 1/8; §6 error handling → incomplete-research paths (5,7,8), unscanned_ranges (6,9), resumability (8); §7 testing → per-task TDD + e2e (8,10); dossier/EDL/CSV artifacts → 4,9,10; ADK requirement → 11. Deferred to Phase 2 (own plans): live Gemini client, webhook/Pub/Sub, web UI, Agent Engine/Cloud Run deployment, cue sheet stretch.
2. **Placeholder scan:** one intentionally abbreviated test body in Task 7 (fixture-load test) is fully specified by its comment + Task 5 pattern; all other code is concrete.
3. **Type consistency:** `MarkerEntry` defined once in `edl.py` (Task 4) and imported elsewhere; `ScanResult` lives in `gemini_client.py`; stage names are the strings used in `stage_status` checks (Tasks 8,9,11) — verified consistent.
