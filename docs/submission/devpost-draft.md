# Devpost Submission Draft

**Track:** Parallel
**Project name:** ClearFrame
**Tagline:** Ship the film, not the lawsuit.

---

## Inspiration

In 2011, Warner Bros. nearly lost the release date of a $580M film over a **tattoo**. The artist behind Mike Tyson's face tattoo filed for a preliminary injunction against *The Hangover Part II* weeks before opening (*Whitmill v. Warner Bros.*). In 1996 an architect actually **got** an injunction against *12 Monkeys* while it was in theatres (*Woods v. Universal*). A story quilt visible for 27 seconds of background made BET liable (*Ringgold*). And music clearance gaps shelved *The Wonder Years* for twenty years and *WKRP in Cincinnati* for decades.

Every film must clear everything visible and audible in frame — logos, artwork, music, tattoos, faces — before an E&O insurer will underwrite it and a distributor will touch it. In 2026 this is still done frame-by-frame, by hand. Studios have clearance departments; independent filmmakers and documentarians have a choice between a multi-thousand-dollar report and never releasing at all.

Meanwhile YouTube's Content ID processed **2.5 billion claims** last year — all in the wrong direction. Content ID finds *your* IP in other people's video. Nothing finds *other people's* IP in **yours** — before you ship. So we built it.

## What it does

Upload raw footage and a screenplay; get back the document an insurer asks for, with every claim cited.

A deterministic **13-stage pipeline**: script pre-scan → **three independent Gemini video passes** → triage → corroboration → script-vs-screen drift → a preliminary report → **Parallel deep research** → live enforcement signals → risk → territory → licence coverage → remediation → an adversarial **Clearance Court** — then a human review app and an E&O dossier in HTML and Word.

The design decisions that matter:

- **Detectors observe; code decides.** Risk is a pure-code rubric, never an LLM opinion:

$$\text{score} = B_{\text{category}} \cdot f_{\text{prominence}} \cdot f_{\text{duration}} \cdot f_{\text{posture}} \cdot f_{\text{context}} \cdot f_{\text{territory}}$$

  Every factor is recorded with the score, so any band is re-derivable from stored inputs. A preliminary score pins rights-holder posture at worst case, so a band can only *fall* when research lands — never fall because a lookup failed.

- **An escalation ladder decides what each finding costs.** LOCAL (rights table, \$0) → STATUTE (settled law, \$0) → SEARCH (Parallel Search, ~\$0.005) → DEEP (Parallel Task, up to \$0.30). Ownership of a famous mark is a lookup; ownership of an anonymous mural *is* the question, so art goes deep. The record splits on real litigation: brand owners mostly **lose** against expressive works (*Rogers*, *Caterpillar v. Disney*, *Louis Vuitton v. WB*) and win against **adverts** (*Falkner v. GM*) — so an advertisement scores 1.4× and a film gets the Rogers shield.

- **Identity is corroborated, not guessed.** Cloud Video Intelligence logo recognition and acoustic fingerprinting independently confirm what Gemini saw. A conflict *blocks* research — we won't bill you to investigate the wrong brand.

- **Evidence, in dollars and citations.** Every Parallel research result carries Basis citations as the audit trail. Every HIGH finding gets a cost block — statutory range (17 U.S.C. §504(c): \$750–\$150{,}000 per work), clear-now vs fix-in-post, and injunction risk read from the actual litigation record. The Clearance Court argues each contested finding — studio counsel vs a fair-use advocate, a judge ruling with precedent.

- **Pause the video, get a measured box.** Gemini samples video coarsely and returns union rectangles, so we re-measure every paused frame with a grounding call on the still — warmed in advance, ~900ms cold, 7ms warm.

- **A human signs everything.** Role-gated review, append-only audit trail naming a verified email, and the dossier exports with signatories. The system's job is evidence, not verdicts.

## How we built it

**Google Cloud end to end:** Gemini on Vertex AI (three concurrent video passes + an adversarial audit pass + frame grounding), Cloud Video Intelligence, two Cloud Run services (public API + private worker) with a Cloud Tasks queue between them, Firestore, Cloud Storage, Firebase Authentication, Cloud Build CI/CD, and an ADK `SequentialAgent` wrapper over the pipeline. A measured deployed run: 42s clip, **preliminary report in ~3 minutes, full dossier in 9**, about \$0.03 of compute — Gemini video is ~\$0.019 per minute per pass.

**Parallel at runtime, load-bearing:** the Task API with per-finding processor tiers chosen by a Budget Planner with recorded rationale; Parallel Search for the live "is this holder enforcing right now" pass; run-based FindAll to enumerate candidate owners of unidentifiable works. We deliberately never assert litigation posture from a local table — whether a rights holder is suing people *this quarter* is exactly what a static database cannot know, and exactly what keeps Parallel on the critical path of every material finding.

**Engineering:** a framework-free deterministic core; fixture/live client twins sharing one parser, so demo mode replays recorded responses through the *identical* code path with zero credentials; **937 tests**, a full-transport smoke script, and a 25-check probe run against the deployed site with two real accounts.

## Challenges we ran into

- **A prompt is not a contract — four times.** The model wrote "replicating" where we matched "replicated", answered x-first to a y-first bbox spec, phrased cast attribution three ways, and labelled subtitles with their own dialogue. Every check that reads model prose now has a code guard for how the model *actually* writes.
- **Recall is the product's central claim, so we measured it**: ~60% per scan pass across identical runs, and no video parameter fixed it (we tested and rejected two). The fix was three independent passes — on a live clip, three real findings were each caught by exactly *one* pass.
- **Two processes are not one.** The split topology silently broke things a green suite couldn't see: Cloud Tasks' default 600s deadline severing long runs, a heartbeat that went quiet during the scan, a rights ledger written to one container's disk and read from another's. Each was found by running the real deployment.
- **Security before the URL went public**: five ways one account could reach another's clearance work — including an XSS through the dossier itself — found, fixed, and re-probed over the network.

## What we learned

A green test suite is not a working product — every important defect was found by uploading a real clip and clicking. Latency tracks the number of findings, not the input, so "faster" usually means "found less." And in legal automation, the deliverable isn't the answer — it's the *provenance*: citations, reproducible scores, and a named human signature are what make an AI-generated document usable.

## What's next

Differently-primed scan passes to push recall past the three-pass ceiling; feeding script-vs-screen drift back as a targeted second look; USPTO TSDR as a free registry rung on the ladder; and a pilot with a documentary team — the people for whom \$0.50 of research versus a \$3,000 report is the difference between releasing and not.
