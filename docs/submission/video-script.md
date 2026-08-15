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

**0:50–1:40 — The research (review UI, the star section)**
- Open the review UI. Pan the clearance timeline lanes.
- Click the CRITICAL music lane → card scrolls into view.
> "Then a fleet of research agents goes to work through Parallel's Task API — deep web research, one agent per finding. This isn't a chatbot guess: every field comes back with citations, excerpts, and calibrated confidence. Who owns the song. How litigious they are. What a license costs. The evidence trail a lawyer can actually rely on."
- Hover a citation; open the license email draft.
> "ClearFrame even drafts the outreach email — and for the mural it couldn't identify, it says so honestly and escalates."

**1:40–2:20 — The human + the dossier**
- Switch role to Editor → decision buttons disable. Switch back to Legal.
> "Governance is built in: editors read, legal decides."
- Record decisions rapidly (Approve risk / Pursue license / Escalate).
- Click **Generate clearance dossier** → open dossier.html, scroll.
> "Every decision is logged, and out comes the artifact this industry actually runs on: the E&O clearance report — plus timeline markers that drop straight into DaVinci Resolve, and the ASCAP cue sheet for the music."
- Show markers.edl imported in Resolve (Timeline → Import → Timeline Markers from EDL) with colored risk markers on the timeline.

**2:20–2:50 — Architecture + impact (diagram card)**
> "Under the hood: a deterministic six-stage agent pipeline built with Google's Agent Development Kit, Gemini on Vertex AI for video understanding, and Parallel's Task API for rights research, deployed on Cloud Run. Deterministic scoring — no LLM guessing on risk. For studios, this turns weeks of manual review into hours. For indie filmmakers, it's the difference between getting distribution and not."

**2:50–3:00 — Close**
> "ClearFrame. Every frame, cleared. — And yes, we noticed our own demo scene needs clearance. That's the point."

## Recording notes

- Use live mode for the pipeline run so the video shows real Gemini + Parallel calls (submission requires demonstrating actual runtime use).
- Record UI at 1400×900, 125% zoom for legibility.
- If live Gemini misses an element, that's fine — show what it found; honesty reads well. Keep the fixture demo as backup.
