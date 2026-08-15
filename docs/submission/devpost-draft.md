# Devpost Submission Draft

**Track:** Parallel
**Project name:** ClearFrame
**Tagline:** Every frame, cleared. An autonomous rights-clearance department for film & TV.

## Inspiration

In 2011 Warner Bros. was sued over Mike Tyson's face tattoo in *The Hangover Part II* — the case nearly blocked a $580M theatrical release. Shows like *WKRP in Cincinnati* had their soundtracks gutted on streaming because music was never cleared for future media. Every film, series, and documentary must legally clear **everything** visible and audible in frame — logos, artwork, music, tattoos, faces, locations — before E&O insurers will underwrite it and distributors will touch it. In 2026, this is still done frame-by-frame, by hand, by clearance coordinators and law firms. Indie filmmakers who can't afford that get stuck at the distribution gate forever.

## What it does

ClearFrame is the clearance department, automated — with a human lawyer still making every call:

1. **Scan** — Gemini (video-native, on Vertex AI) watches raw footage and detects every clearable element with timestamps and prominence measurements (screen time, frame coverage, centrality, plot relevance).
2. **Triage** — deterministic rules map each element to its legal category: trademark, copyright artwork, music sync, right of publicity, location.
3. **Research** — a concurrent fan-out of agents calls the **Parallel Task API**: one deep-research task per element, returning owner, licensing contact, enforcement history, and cost band — every field with Parallel's Basis output: citations, excerpts, reasoning, calibrated confidence. Provenance is what makes an AI-generated legal document usable.
4. **Score** — a reproducible, pure-code risk rubric (prominence × category weight × rights-holder posture, with de-minimis heuristics). No LLM guessing on risk.
5. **Remediate** — drafts the license outreach email, estimates VFX blur cost, flags reshoots, writes de-minimis memos.
6. **Review & deliver** — a role-gated review app (legal/producer decide; editors read) where every decision is logged; then it emits the artifacts the industry actually runs on: the **E&O clearance report**, **timeline markers that import into DaVinci Resolve**, and the **ASCAP/BMI cue sheet**.

## How we built it

- **Google Cloud:** Gemini on Vertex AI (video understanding with structured output), Agent Development Kit — the pipeline runs as a deterministic ADK `SequentialAgent` of six custom agents, deployable to Agent Engine — Cloud Run for the review app.
- **Parallel:** the Task API (`pro` processor) with a schema-driven output spec; async task runs with polling/webhooks; Basis citations stored verbatim and surfaced in the UI and dossier as the audit trail.
- **Engineering:** framework-free deterministic core (Pydantic v2), fixture-backed demo mode that replays recorded API responses through the identical code path (judges can run everything with zero credentials), 51 tests, FastAPI + React.

## Challenges we ran into

- Making an AI output *legally credible*: the answer was calibrated confidence + citations per field (Parallel's Basis), deterministic scoring, and honest "RESEARCH INCOMPLETE" states instead of hallucinated owners.
- Judging prominence from video (a 1-second background logo ≠ a 12-second plot-integral song) — solved by having Gemini measure screen time, coverage, and centrality, and doing the risk math in code.

## Accomplishments we're proud of

- The dossier isn't a chat answer — it's the actual document E&O underwriters ask for, and the markers drop into the editor's real timeline.
- A human decides every finding; the system's job is evidence, not verdicts.

## What's next

Firestore + Pub/Sub event-driven research at scale, IAP-backed roles, per-territory clearance rules, and studio-wide risk analytics across productions.

## Built with

`gemini` `vertex-ai` `google-adk` `agent-engine` `cloud-run` `parallel-task-api` `python` `fastapi` `react` `typescript`

## Links

- Hosted project: `<Cloud Run URL>`
- Repo: `<GitHub URL>` (MIT license)
- Video: `<YouTube URL>`
