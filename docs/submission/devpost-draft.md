# Devpost Submission Draft

**Track:** Parallel
**Project name:** ClearFrame
**Tagline:** Every frame, cleared. An autonomous rights-clearance department for film & TV.

## Inspiration

In 2011 Warner Bros. was sued over Mike Tyson's face tattoo in *The Hangover Part II* — the case nearly blocked a $580M theatrical release. Shows like *WKRP in Cincinnati* had their soundtracks gutted on streaming because music was never cleared for future media. Every film, series, and documentary must legally clear **everything** visible and audible in frame — logos, artwork, music, tattoos, faces, locations — before E&O insurers will underwrite it and distributors will touch it. In 2026, this is still done frame-by-frame, by hand, by clearance coordinators and law firms. Indie filmmakers who can't afford that get stuck at the distribution gate forever.

## What it does

ClearFrame is the clearance department, automated — with a human lawyer still making every call:

1. **Scan** — Gemini (video-native, on Vertex AI) watches raw footage and detects every clearable element with timestamps and prominence measurements (screen time, frame coverage, centrality, plot relevance).
2. **Audit** — a second Gemini agent adversarially reviews the first scan ("what did the coordinator miss?") and catches overlooked elements — agents auditing agents.
3. **Triage** — deterministic rules map each element to its legal category: trademark, copyright artwork, music sync, right of publicity, location.
4. **Plan & research** — a Budget Planner allocates a **Parallel processor tier per finding with recorded rationale** (lite for a famous swoosh, ultra for an unidentified mural), then a concurrent fan-out of researcher agents calls the **Parallel Task API** — every field returned with Basis citations, excerpts, and calibrated confidence. Provenance is what makes an AI-generated legal document usable.
5. **Score** — a reproducible, pure-code risk rubric (prominence × category weight × rights-holder posture, with de-minimis heuristics). No LLM guessing on risk.
6. **Remediate** — drafts the license outreach email, estimates VFX blur cost, flags reshoots, writes de-minimis memos.
7. **The Clearance Court** — for every contested finding, two opposing agents argue: Studio Counsel briefs the risk, a Fair Use Advocate briefs the defense (de minimis, *Rogers v. Grimaldi*, fair use), both citing real precedent (*Ringgold*, *Sandoval*, *Caterpillar v. Disney*, VARA); a Judge issues a practical ruling. Opinions attach reasoning — they never override the deterministic score.
8. **Review & deliver** — a role-gated review app (legal/producer decide; editors read) where every decision is logged; then it emits the artifacts the industry actually runs on: the **E&O clearance report**, **timeline markers that import into DaVinci Resolve**, and the **ASCAP/BMI cue sheet**.

## How we built it

- **Google Cloud:** Gemini on Vertex AI (video understanding with structured output and explicit safety settings), Agent Development Kit — the eight-stage pipeline runs as a deterministic ADK `SequentialAgent` of nine stage agents (`clearframe run --demo --adk --auto-approve` executes it under the real ADK Runner) — Cloud Run hosts the review app and the MCP server with scale-to-zero CI/CD via Cloud Build.
- **Parallel:** the Task API with schema-driven output specs and per-finding processor-tier allocation (lite→ultra, chosen by a Budget Planner with recorded rationale); async task polling with bounded retries; run-based FindAll candidate enumeration for unidentifiable owners (matched candidates ranked first, capped for reviewability); standing watches that create Parallel Monitors when the key includes that beta and fall back to local stand-ins otherwise, with a webhook that reopens review; Basis citations stored verbatim and surfaced in the UI and dossier as the audit trail. All of it exercised against the live API.
- **Engineering:** framework-free deterministic core (Pydantic v2), fixture-backed demo mode that replays recorded API responses through the identical code path (judges can run everything with zero credentials), 90 tests plus a full-transport smoke script, FastAPI + React.

## Challenges we ran into

- Making an AI output *legally credible*: the answer was calibrated confidence + citations per field (Parallel's Basis), deterministic scoring, and honest "RESEARCH INCOMPLETE" states instead of hallucinated owners.
- Judging prominence from video (a 1-second background logo ≠ a 12-second plot-integral song) — solved by having Gemini measure screen time, coverage, and centrality, and doing the risk math in code.
- Building against APIs before having keys: we coded live clients from docs with fixture twins sharing one parser, then validated on keys-day — the Task API worked unchanged; FindAll needed a rewrite to its real run-based flow; the Monitors beta turned out to be gated for our key, so live mode degrades honestly to local stand-in watches instead of pretending.

## Accomplishments we're proud of

- The dossier isn't a chat answer — it's the actual document E&O underwriters ask for, and the markers drop into the editor's real timeline.
- A human decides every finding; the system's job is evidence, not verdicts.

## What's next

Firestore + Pub/Sub event-driven research at scale, IAP-backed roles, per-territory clearance rules, and studio-wide risk analytics across productions.

## Built with

`gemini` `vertex-ai` `google-adk` `agent-engine` `cloud-run` `parallel-task-api` `python` `fastapi` `react` `typescript`

## Links

- Hosted project: https://clearframe-220710110855.us-central1.run.app (+ MCP: https://clearframe-mcp-220710110855.us-central1.run.app/mcp)
- Repo: `<GitHub URL>` (MIT license)
- Video: `<YouTube URL>`
