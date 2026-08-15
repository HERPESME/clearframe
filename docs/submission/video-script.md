# ClearFrame — 3-Minute Demo Video Script

Rules require: the agent **functioning as built** (not a cinematic trailer), English, public on YouTube/Vimeo.

## The salted demo scene (shoot first — ~1 hour)

Shoot one continuous ~60s scene on a phone (1080p is fine, landscape). Two people in a room + short walk outside. Deliberately place:

| Prop | Element it creates | Expected result |
| --- | --- | --- |
| Coca-Cola can on table | trademark | MEDIUM |
| Nike hoodie on one actor | trademark (litigious) | HIGH |
| Band poster on wall | copyright artwork | MEDIUM |
| Phone playing a recognizable hit song ~12s, characters react | music sync | CRITICAL |
| Walk past a street mural | copyright artwork, unknown artist | escalate |
| Passerby in background ~1s | right of publicity | de-minimis LOW |

Keep the song clearly audible; keep logos in focus for a few seconds each. (The irony that the demo scene itself is uncleared is the joke — say it in the video.)

## Script

**0:00–0:25 — The hook (voiceover over stills/text cards)**
> "In 2011, one tattoo nearly stopped a $580 million movie. Warner Bros. was sued over Mike Tyson's face tattoo in The Hangover Part II — because every logo, artwork, song, and face in every frame of every film must be legally cleared before release. Today, clearance coordinators do this frame by frame. By hand. Meet ClearFrame: an autonomous clearance department."

**0:25–0:50 — The scan (screen recording)**
- Show the raw scene playing for ~5s.
- Terminal: `python -m clearframe run --live --footage scene.mp4 ...` kicking off.
> "Gemini watches the footage the way a clearance coordinator would — and finds every clearable element: the song on the phone, the swoosh on the hoodie, the mural, even the passerby's face. Six findings, timestamped, with prominence measured."

**0:50–1:45 — Mission Control + the Court (the star section)**
- Open `http://localhost:8000/?autorun` → Mission Control plays live: agents lighting up, researcher rows landing with owners, the Court issuing rulings.
> "Watch the department work. A second Gemini agent audits the first — and catches a background TV broadcast the first pass missed. A Budget Planner decides how much research each finding deserves and buys the right Parallel processor tier — five cents for the famous swoosh, three dollars of deep research for the unidentified mural. Then, for every contested finding, court convenes: a Studio Counsel agent argues the risk, a Fair Use Advocate argues the defense — both citing real case law through Parallel research — and a Judge rules."
- Enter review; click the CRITICAL music lane → card scrolls into view; expand the Counsel brief showing *Ringgold* and §504(c).
> "This isn't a chatbot guess. Every research field carries citations and calibrated confidence, and every ruling shows both sides' briefs. For the mural nobody could identify — it says so honestly, and escalates."

**1:40–2:20 — The human + the dossier**
- Switch role to Editor → decision buttons disable. Switch back to Legal.
> "Governance is built in: editors read, legal decides."
- Record decisions rapidly (Approve risk / Pursue license / Escalate).
- Click **Generate clearance dossier** → open dossier.html, scroll.
> "Every decision is logged, and out comes the artifact this industry actually runs on: the E&O clearance report — plus timeline markers that drop straight into DaVinci Resolve, and the ASCAP cue sheet for the music."
- Show markers.edl imported in Resolve (Timeline → Import → Timeline Markers from EDL) with colored risk markers on the timeline.

**(insert at ~2:10, 15s) — The kicker: living clearance**
- Fire the mock monitor webhook (curl or a button) while on the review screen.
> "And clearance doesn't end at delivery. ClearFrame leaves standing watches on every risky finding through Parallel's monitors — three weeks later, when the rights holder files a new lawsuit, your dossier reopens itself."
- The amber alert banner appears live: *review reopened*.

**2:20–2:50 — Architecture + impact (diagram card)**
> "Under the hood: a deterministic six-stage agent pipeline built with Google's Agent Development Kit, Gemini on Vertex AI for video understanding, and Parallel's Task API for rights research, deployed on Cloud Run. Deterministic scoring — no LLM guessing on risk. For studios, this turns weeks of manual review into hours. For indie filmmakers, it's the difference between getting distribution and not."

**2:50–3:00 — Close**
> "ClearFrame. Every frame, cleared. — And yes, we noticed our own demo scene needs clearance. That's the point."

## Recording notes

- Use live mode for the pipeline run so the video shows real Gemini + Parallel calls (submission requires demonstrating actual runtime use).
- Record UI at 1400×900, 125% zoom for legibility.
- If live Gemini misses an element, that's fine — show what it found; honesty reads well. Keep the fixture demo as backup.
