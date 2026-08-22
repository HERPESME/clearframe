# ClearFrame Phase 9 — The Escalation Ladder

**Status:** Implemented 2026-08-22 (branch `feat/corroboration-search-territory`).
231 tests, smoke green. Tasks 1, 2, 3, 5 and 7 shipped; 4, 6 and 8 remain (see
"What is deliberately not done yet" at the end).

**Problem.** A 21.8s clip took ~20 minutes. Measured cause: 16 Parallel deep-research
Task runs, 6 of which returned no owner at all. Category mix was 7
RIGHT_OF_PUBLICITY, 4 TEXT_ON_SCREEN, 2 COPYRIGHT_ART, 1 TRADEMARK, 1 MUSIC_SYNC,
1 LOCATION — deep research spent on faces and the editor's own captions.

**Goal.** A complete, timestamped, risk-banded clearance report in ~60 seconds,
with ownership certainty streaming in behind it. Not by detecting less — by
resolving each finding at the cheapest level that can actually answer it.

---

## 1. What the litigation record actually says

The routing policy below is derived from who sues productions and wins, not from
our category enum. Sources are recorded in `data/rights/litigation.json`.

| Rightsholder class | Sues? | Evidence | Outcome pattern |
| --- | --- | --- | --- |
| Music publishers + labels | Systematically | NMPA v. Fullscreen; Content ID at industrial scale; $750–$150k/work statutory | Defendant reliably loses |
| Visual artists (mural/graffiti) | Frequently, contingency-funded | Falkner v. GM (survived dismissal); Revok v. H&M (settled for artist) | Settles; VARA moral rights add exposure |
| Photographers / stock agencies | Yes, at scale | Ringgold v. BET (poster in background — actionable); Sandoval v. New Line (out-of-focus — de minimis) | Turns on recognizability + duration |
| Tattoo artists | Occasionally | Alexander v. Take-Two (plaintiff won, **$3,750**); Solid Oak v. 2K (defendant won on de minimis + implied licence + fair use) | Real but low-value |
| Brand owners (trademark) | Rarely, and usually lose | Wham-O v. Paramount dismissed; Rogers v. Grimaldi; In-Sink-Erator/NBC resolved by digital removal | Loses on expressive use |
| Individuals (right of publicity) | Yes — but solved by process | Release forms, crowd notices | No research can produce a release |
| Architecture | Almost never (US) | 17 U.S.C. §120(a) | Already in `territory.py` |

**Two conclusions that reshape the product:**

1. **Risk is inverted relative to detection effort.** The industry builds logo
   detectors; logos are the category most likely to win in court. Music, where
   the defendant reliably loses, is currently identified by a language model
   naming a track. This is the same finding that motivates audio fingerprinting
   (`AUDIO`, below) — it is not a coincidence, it is the same root cause.

2. **For trademark the risk variable is not identity, it is depiction.** Wham-O
   lost because exaggeration made endorsement implausible; NBC erased
   In-Sink-Erator only because the scene was unflattering. So the signal worth
   extracting is *depiction context* — disparagement, implied endorsement,
   sensitive juxtaposition. Gemini can report it from footage we already send,
   at zero additional call cost. No competitor in the positioning table markets
   anything equivalent.

**Constraint from underwriting.** E&O carriers do not accept fair-use argument in
place of clearance, and distributors reject "incidental use" without
documentation. Therefore the cheap routes must emit a **documented position**
(de minimis memo citing Sandoval; release-form requirement; panorama finding),
never a silent skip. This is strictly better than researching everything, and
it is free.

---

## 2. The escalation ladder

Replaces "plan a processor tier for every element" with "resolve at the cheapest
level that can answer". Each finding enters at L0 and stops at the first level
that resolves it.

| Level | Resolver | Latency | Cost | Answers |
| --- | --- | --- | --- | --- |
| **L0** | Known-rights table, PD registry, prior-run cache | 0 ms | $0 | Owner of a famous mark; already-researched element |
| **L1** | Deterministic law | 0 ms | $0 | De minimis, panorama, PD term, own content, unnamed person |
| **L2** | Structured registries — AudD, USPTO TSDR, MusicBrainz, VI catalogue | 0.2–3 s | ~$0 | Verified identity |
| **L3** | **Parallel Search** | ~2 s | $0.005 | Posture, enforcement news, contact route |
| **L4** | **Parallel Task** | minutes | $0.01–0.30 | Genuinely unknown ownership chains |

L4 is reserved for what is genuinely not in any registry: unattributed murals,
music that failed fingerprinting, unknown small marks, chain-of-title.

### Routing rules (deterministic, pure code)

```
MUSIC_SYNC
  fingerprint hit  → L2 identity, then L3 posture (publisher/label in rightsholders.json)
  fingerprint miss → L4  (this is the one case that genuinely earns a Task run)
COPYRIGHT_ART
  attributable signature/watermark → L3
  unattributed AND above de-minimis → L4 + FindAll   (the mural lead)
  below de-minimis                 → L1 memo citing Sandoval
TRADEMARK
  in known_marks.json  → L0 owner; L3 only if depiction context flags disparagement
  not in table         → L2 USPTO; L4 only if USPTO is silent
RIGHT_OF_PUBLICITY
  named individual → L3 (find the agent, not the "owner")
  unnamed          → L1 release-form requirement. No research can produce a release.
LOCATION
  named venue → L3   ·   generic → L1
TEXT_ON_SCREEN
  brand string     → reclassify as TRADEMARK, re-enter ladder
  production's own → L1 own-content finding
  generic/UI       → L1
```

### Measured effect on the observed 16 elements

| | Before | After |
| --- | --- | --- |
| Resolved L0/L1 (free) | 0 | 9 |
| Resolved L2 | 0 | 4 |
| Parallel Search (L3) | 0 | 2 |
| Parallel Task (L4) | **16** | **0–1** |
| Findings reported | 16 | 16 |

Recall is unchanged. Only the resolver changes.

---

## 3. Latency architecture

```
t=0        upload accepted
t=0–3s     ffmpeg extract → AudD fingerprint      ─┐
t=0–45s    Gemini locate pass                      ├─ concurrent
t=0–45s    Video Intelligence LOGO_RECOGNITION    ─┘
t=45s      triage → corroborate → L0/L1/L2 resolve
           ►► COMPLETE REPORT EMITTED
              timestamps, bboxes, prominence risk, territory bands,
              coverage vs ledger, remediation templates
t=45–55s   L3 searches fan out concurrently → posture fills in
t=55s+     L4 (0–1 items) streams in as it lands
```

**Time to complete report: ~60 s** (was ~20 min). The report is *complete* at 45s;
what arrives late is ownership certainty, and it arrives as live updates over the
existing SSE channel. Risk re-scores on each landing.

### Supporting latency fixes

- `poll_interval_s` 10.0 → 2.0 in `parallel_client.py`.
- Court `counsel` / `advocate` run concurrently (`court_client.py:214–216` is
  sequential today); only `ruling` must wait on both.
- Audio extraction starts at t=0, never after the scan.
- E&O audit second pass moves off the critical path — it streams additions.
- Scene-chunked scanning for footage > 60 s: fixes both parallelism and Gemini
  timestamp drift over long spans. Merge on the existing `triage.py` dedupe.

### Blocker

**`ffmpeg` is not installed on this machine** — the audio path cannot run without
it. Resolve with `pip install imageio-ffmpeg` (ships a static binary, no brew,
no user action) rather than a system package.

---

## 4. Dataset broadening

Goal: a director can ask "am I violating anything, given the permissions I hold?"
and get a grounded answer without any network call.

### 4.1 `data/rights/known_marks.json` (~400 entries)

`label · aliases · owner · parent · posture · evidence · typical_licence_band`.
Seeded from the LogoDet-3K (3,000 classes) and QMUL-OpenLogo (352 classes) class
lists intersected with USPTO ownership. Makes L0 real; a famous mark never needs
a network call.

### 4.2 `data/rights/litigation.json`

The case table from §1, machine-readable: parties, year, category, fact pattern,
holding, citation. Two consumers:
- **Posture** becomes a cited fact rather than an LLM guess.
- **Clearance Court** already consumes case fixtures — this extends that corpus.

### 4.3 `data/rights/rightsholders.json`

Music publishers (UMPG, Sony, Warner Chappell, Kobalt, BMG), labels, stock
agencies (Getty, AP, Reuters, Shutterstock), studios — with enforcement
behaviour. Lets a fingerprint hit resolve straight to a posture.

### 4.4 `data/rights/public_domain.json`

US term rules as data: published works pre-1931 (as of 2026), sound recordings
pre-1926 under the Music Modernization Act rolling schedule, US Government works.
**Exact cutoff dates must be verified against copyright.gov before shipping** —
per the submission-auditor rule, sloppy law is worse than no law.

### 4.5 Ledger: 12 → ~30 grants, 8 gap archetypes

worldwide/perpetual · US-only (territory gap) · theatrical-only (media gap, the
WKRP problem) · expiring mid-term (term gap) · **festival-only** (the classic
indie trap) · **composition licensed but not master** · wrong entity (parent vs
subsidiary) · expired.

Requires a model change: `LicenceGrant.rights_type: SYNC | MASTER | BOTH | PRINT`.
The composition/master split is the most common music clearance failure in the
industry and is currently unrepresentable — `scope` is a free-text string.

### 4.6 Clip corpus

Extend `scripts/fetch_test_clips.sh` beyond the 6 PD commercials with Prelinger
Archives, Blender open movies (CC-BY), and NASA footage. Extend
`ground_truth.json` to score routing decisions, not just detections.

---

## 5. Implementation order

| # | Task | Status |
| --- | --- | --- |
| 1 | `imageio-ffmpeg` + `integrations/audio_client.py` (protocol + fixture + live AudD); `AUDIO_API_KEY` → `AUDD_API_TOKEN` | **done** |
| 2 | `data/rights/*.json` + `knowledge.py` loader | **done** |
| 3 | `routing.py` — the ladder, pure code, auditable like `planner.py`; `planner.py` becomes L4-only | **done** |
| 4 | Two-phase emit: report at L2, enrich over SSE | open |
| 5 | Latency fixes (poll interval, concurrent Court, concurrent scan/VI/audio) | **done** |
| 6 | Depiction-context signal in `SCAN_PROMPT` + scan schema | open |
| 7 | `LicenceGrant.rights_type` + expanded ledger + corpus | **done** |
| 8 | Scene chunking > 60 s | open |

## What changed during implementation

Three decisions differ from the plan, each because building it made the plan
look wrong:

1. **Music fingerprinting is an identity SOURCE, not a corroborator.** The plan
   said "add `MUSIC_SYNC` to `CORROBORATABLE`". That would have been wrong: the
   video model's "Upbeat Electronic Music" is not a competing identity claim to
   be reconciled, it is the *absence* of one. Comparing them would have produced
   CONFLICTED and blocked research on a song we had just correctly identified.
   `audio.apply_audio_identity` promotes instead, and `FINGERPRINTED` was added
   as a verdict that outranks `CORROBORATED`.

2. **A rung must be able to answer the question its category poses.** The plan
   routed attributable artwork to SEARCH. But for artwork "who owns this" IS the
   question — a poster's rights can sit with the band, the label, the
   photographer or the designer — and a two-second search cannot resolve it.
   Trademark is the opposite: ownership is a local lookup and only posture is
   live. So art goes DEEP and trademark goes SEARCH.

3. **Materiality overrides the ladder.** Cheapest-that-can-answer is the right
   default and the wrong rule for the two or three findings that will actually
   sink a delivery. Anything at or above the HIGH band escalates to a deep run
   regardless of category, because only a deep run produces a licensing contact,
   a cost band and citations an underwriter can follow.

## Defects found and fixed while building

- **False licence matches from corporate name tokens.** `find_licences` matched
  holders on raw token overlap, so "Kobalt Music Group" matched an owner string
  containing "Universal Music Group" on `{music, group}` alone and reported a
  festival-only cue licence as covering a Weeknd master. `matching.holders_match`
  now compares identifying tokens only. Being wrong in the *covered* direction is
  the one failure the ledger must not have.
- **The smoke `has` helper still raced.** It had been "fixed" by buffering the
  body before piping, but `grep -q` stops reading at the first match, so any
  body over the 64KB pipe buffer still killed the writer. The dossier grew past
  that line and a passing check reported failure. Here-strings are file-backed.

## What is deliberately not done yet

- **Two-phase emit (task 4).** `scoring.provisional_score` exists for it; the
  SSE emit is not wired. This is the remaining *perceived*-latency win: a
  complete timestamped risk report at ~45s with ownership arriving behind it.
- **Depiction-context signal (task 6).** The research says brand risk turns on
  *how* a mark is shown. Gemini can report it from footage already sent, free.
- **Scene chunking (task 8).** Needed for feature-length footage, both for
  parallelism and for timestamp accuracy over long spans.
- **USPTO TSDR as a registry rung.** Would resolve unknown marks without a deep
  run; needs an API key.

## Honesty guardrail

Every L0/L1 resolution must appear in the dossier as an explicit, counted,
reasoned class — "7 findings resolved as release-form requirements", "3 findings
are the production's own graphics", each with its basis. A faster tool that
quietly examines less is the exact failure this codebase has refused at every
prior step (RESEARCH INCOMPLETE, SINGLE_SOURCE, UNKNOWN coverage, the demo-mode
upload 409).
