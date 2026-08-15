# Submission Checklist — deadline Sep 10, 2026, 2:30am IST

## Blocked on you (in order)

1. **GitHub repo** — create public repo, push `main`, confirm the MIT license shows in the About sidebar ("MIT License"). `gh repo create clearframe --public --source . --push`
2. **Credentials** — GCP project with Vertex AI enabled + billing; Parallel API key from platform.parallel.ai (they typically give hackathon credits — check the hackathon resources page).
3. **First live run** — `pip install -e ".[dev,cloud]"`, then the live command in README on any short mp4. Iterate the scan prompt if detection quality disappoints (`src/clearframe/integrations/gemini_client.py::SCAN_PROMPT`).
4. **Shoot the salted demo scene** — shot list in `video-script.md` (~1 hour).
5. **Deploy** — `docs/deploy.md` Cloud Run section (verify the Dockerfile builds first: `docker build .` — written but unverified, Docker daemon was off).
6. **Record the 3-min video** — script in `video-script.md`; upload to YouTube (public or unlisted).
7. **Devpost form** — paste from `devpost-draft.md`, select **Parallel** track, add the three URLs.

## Hard requirements audit (from the rules)

- [x] Functional agent using Gemini + Google Cloud Agent Builder (ADK SequentialAgent, Vertex Gemini)
- [x] Partner service imported and called in code (`integrations/parallel_client.py`, called by ResearchStage)
- [x] Public repo w/ complete OSS license file, all source + run instructions
- [ ] License visible in GitHub About section (verify after push)
- [ ] Hosted project URL (Cloud Run)
- [ ] 3-minute demo video, public, English
- [ ] Devpost form + track selection

## Nice-to-have before submission

- Import `markers.edl` into DaVinci Resolve once and screenshot it for the video.
- Add the Cloud Run URL + video URL to README.
- Fresh-clone test: `git clone … && pip install -e ".[dev]" && pytest && python -m clearframe run --demo --out out --auto-approve`.
