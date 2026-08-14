# ClearFrame — Design Spec

**Date:** 2026-08-15
**Status:** Approved direction (user delegated decisions); implementation plan to follow
**Target:** Google Cloud "Agentic Cinema" hackathon, Parallel partner track, deadline Sep 10 2026 (2:30am GMT+5:30)

## 1. Overview

ClearFrame is an autonomous rights-clearance department for film & TV. It ingests raw footage, uses Gemini's video-native multimodal understanding to detect every legally "clearable" element (logos, artwork, music, tattoos, faces, locations, on-screen text), deep-researches each element's rights holder via the Parallel Task API, scores legal risk deterministically, proposes remediation, and produces the industry-standard clearance dossier that E&O insurers and distributors require — with a human clearance coordinator approving every finding.

The output artifacts are real industry documents: an E&O-ready clearance report, timeline markers importable into DaVinci Resolve/NLEs (EDL/CSV), and (stretch) an ASCAP/BMI cue sheet for detected music.

### Goals
- A deterministic, multi-step multi-agent pipeline built on Google ADK, deployable to Agent Engine (Gemini Enterprise Agent Platform).
- Deep runtime integration with Parallel Task API: schema-driven deep research whose Basis output (citations, per-field reasoning, confidence) becomes the audit trail of the legal dossier.
- A complete product experience: upload → detection timeline → research cards → risk heat-map → human review → exported dossier + NLE markers.
- Runnable by judges: live mode (GCP + Parallel keys) and demo mode (recorded fixtures, zero credentials) both work end-to-end.

### Non-goals
- Not legal advice; the dossier is decision support for counsel (prominent disclaimer).
- No actual license negotiation, payments, or e-signature.
- No production-grade auth beyond role separation (producer / legal / editor) suitable for the demo; Cloud IAP notes documented for real deployment.
- No mobile UI.

## 2. Personas & product flow

- **Producer** uploads footage to a production, watches pipeline progress, sees cost/risk summary.
- **Clearance coordinator / legal** reviews each flagged element: research evidence, risk band, remediation options; approves, overrides, or escalates. Every decision is logged.
- **Editor** exports timeline markers to see risk flags on their own timeline in the NLE.

Flow: create production → upload footage (or pick demo scene) → pipeline runs (visible stage-by-stage) → review queue → decisions → generate dossier + exports.

## 3. Architecture

### 3.1 Agent pipeline (ADK, Python)

A `SequentialAgent` pipeline with a parallel fan-out in stage 3. All stages exchange typed Pydantic models via ADK session state; control flow is deterministic (workflow agents, not LLM-routed).

1. **SceneScannerAgent** — Gemini (video-native, via Vertex AI; `gemini-3-pro-preview`, fallback `gemini-2.5-pro`). Input: GCS URI of footage. Output: `DetectedElement[]` with timestamp ranges, bounding descriptions, element type guess, and prominence data (screen time, frame coverage, centrality, plot relevance). Uses `response_schema` structured output. Long footage is chunked by scene with results merged.
2. **TriageAgent** — maps each element to a clearance category: `TRADEMARK`, `COPYRIGHT_ART`, `MUSIC_SYNC`, `RIGHT_OF_PUBLICITY`, `LOCATION`, `TEXT_ON_SCREEN`. Deterministic rule table first, Gemini fallback for ambiguous cases. Also merges duplicate detections of the same element across shots.
3. **RightsResearchAgent** (fan-out; one Parallel task per element, `ParallelAgent`-style concurrent execution) — calls **Parallel Task API** (`POST /v1/tasks/runs`, `pro` processor) with a task spec output schema: `owner`, `owner_confidence`, `licensing_contact`, `licensing_posture`, `litigation_history[]`, `estimated_license_cost_band`, plus Parallel's Basis (citations, reasoning, confidence per field). Results arrive async (webhook in prod, polling locally).
4. **RiskScorerAgent** — pure deterministic code (no LLM): `risk = prominence × category_weight × holder_posture`, banded LOW / MEDIUM / HIGH / CRITICAL with de-minimis heuristics (fleeting, out-of-focus, incidental background). Every score is reproducible and explainable.
5. **RemediationAgent** — Gemini drafts per-element options: license (outreach email draft + cost band from research), VFX blur (effort estimate), reshoot/reframe, or fair-use/de-minimis memo. Options ranked by cost and risk reduction.
6. **DossierAgent** — assembles the clearance report from approved decisions only; renders HTML dossier (print-to-PDF ready), EDL + CSV markers, (stretch) cue sheet.

Human review (stage 5→6 gate) happens in the web app; the pipeline pauses at `AWAITING_REVIEW` and the DossierAgent runs only on explicit "generate dossier" after review.

### 3.2 Google Cloud services

- **Vertex AI / Gemini Enterprise Agent Platform**: Gemini models; pipeline deployed to **Agent Engine**; also runnable locally via ADK `Runner` for dev.
- **Cloud Storage**: footage uploads.
- **Firestore**: productions, elements, research results, decisions, reports (repository pattern; local JSON store used in dev/demo so the whole system runs offline).
- **Pub/Sub**: Parallel webhook events → pipeline resume (prod); local polling in dev.
- **Cloud Run**: FastAPI web app (review UI) and webhook receiver.
- **Cloud IAM / IAP**: documented role mapping for production deployment; in-app role switcher for the demo.

### 3.3 Parallel integration (the track requirement)

- `integrations/parallel_client.py` — thin typed client over the Task API: create run, poll/receive webhook, parse output + Basis. Imported and called at runtime by RightsResearchAgent (hard requirement: "imported and called in code").
- Basis citations/confidence are stored verbatim per field and surfaced in the review UI and dossier — provenance is the product's legal credibility.
- Demo mode substitutes recorded fixture responses (captured from real API runs) behind the same client interface.

### 3.4 Modes

- `CLEARFRAME_MODE=live`: real Vertex + Parallel calls (needs `GOOGLE_CLOUD_PROJECT`, `PARALLEL_API_KEY`).
- `CLEARFRAME_MODE=demo`: recorded fixtures for both integrations; identical code path through agents, scoring, review, exports. Used by tests and by judges without keys. README documents both; the demo video uses live mode.

## 4. Data model

Collections (Firestore prod / JSON local), all documents carry `production_id`:

- `productions`: title, created_by, footage assets (GCS URI, duration, fps), pipeline status.
- `elements`: detection (type, category, timecodes[], prominence), triage result, dedupe group.
- `research`: per element — Parallel run id, status, structured output, basis[] (citation url, excerpt, reasoning, confidence).
- `decisions`: per element — reviewer role, action (approve-risk / license / blur / reshoot / escalate), note, timestamp (append-only audit log).
- `reports`: generated dossier metadata + rendered artifact paths.

## 5. Web app (review UI)

FastAPI + Vite/React/Tailwind single-page app served from Cloud Run (and `uvicorn` locally).

Screens: production dashboard (pipeline stage progress) → **timeline view** (footage player with detection markers, risk-colored) → **element review card** (clip thumbnail + timecodes, research summary with citations and confidence, risk breakdown, remediation options, decision buttons) → **dossier page** (print-ready clearance report; export buttons: PDF via print, EDL, CSV).

Role switcher (producer / legal / editor) gates decision buttons — demonstrates the governance story without full auth.

## 6. Error handling

- Gemini detection failures per chunk: retry ×2, then mark chunk `UNSCANNED` in the dossier (never silently drop footage).
- Parallel task failure/timeout (>10 min): element flagged `RESEARCH_INCOMPLETE`, still reviewable manually; dossier lists it as unresolved.
- All agent stages idempotent; pipeline resumable from last completed stage per production.
- Structured-output validation errors → one re-prompt with validator feedback, then fail loud.

## 7. Testing

- Unit: risk scoring rubric (golden cases incl. de-minimis), triage rule table, EDL/CSV exporters (byte-exact goldens), Parallel/Gemini response parsing.
- Integration: full pipeline in demo mode from fixture footage metadata → dossier, asserted end-to-end.
- Contract: fixture schemas validated against the same Pydantic models used live.
- TDD per superpowers workflow; pytest.

## 8. Demo plan (3-minute video)

1. (0:00–0:30) Hook: the *Hangover II* tattoo lawsuit — one uncleared tattoo nearly stopped a $580M release; this job is still done frame-by-frame by hand.
2. (0:30–1:45) Shoot our own ~60s scene salted with clearables (branded can, band poster, logo hoodie, real song from a phone, mural). Upload; watch the timeline light up; Parallel research cards fill in with citations and confidence.
3. (1:45–2:30) Risk heat-map, one-click license email draft, role-gated approval, dossier + markers imported into DaVinci Resolve.
4. (2:30–3:00) Impact: indie filmmakers priced out of distribution; studios spending weeks per cut. Architecture card.

Using footage we shot ourselves proves generality and is itself rights-clean.

## 9. Submission checklist mapping

- Hosted project URL → Cloud Run app.
- Public repo (GitHub) with **MIT license** visible in About; full run instructions (live + demo modes).
- Runtime use of Google Cloud (Vertex Gemini, Agent Engine, Firestore, GCS, Cloud Run) and Parallel (Task API in `parallel_client.py`, called by RightsResearchAgent).
- Track selection: Parallel.
- 3-min demo video on YouTube (English).

## 10. Milestones (26 days)

- **Week 1:** risk-first — validate Gemini detection quality on real test footage (days 1–3); ADK pipeline skeleton; core models + scoring engine (TDD).
- **Week 2:** Parallel live integration + async flow; fixtures captured; review UI core screens.
- **Week 3:** dossier + exporters; Agent Engine + Cloud Run deployment; polish.
- **Final 5 days:** shoot demo scene, record video, README/license/runbook, submit with ≥48h buffer.

## 11. Risks

- **Gemini detection quality on real footage** is the make-or-break; validated first. Mitigation: scene chunking, prompt iteration, curated demo scene.
- **Parallel research variance** on obscure elements: demo scene salts elements with findable owners; UI honestly shows low-confidence results (that's a feature — calibrated confidence).
- **Agent Engine deployment friction**: local ADK Runner is the fallback demo path; deployment attempted early (week 2 end).
