"""Acoustic fingerprinting: identity for music, measured rather than inferred.

Same shape as every other integration here — one protocol, a live client and a
fixture client sharing a single parser — so demo mode exercises the identical
code path with zero credentials.

How fingerprinting actually works (it is NOT transcription): the sample is
converted to a spectrogram, local energy peaks are picked, pairs of peaks are
hashed into time-invariant landmarks, and those hashes are looked up in an
inverted index. Matching hashes then have to agree on a constant time offset.
That is why it recognises a song buried under dialogue, and why it returns a
recording identity rather than words.

ffmpeg comes from `imageio-ffmpeg`, a pip dependency shipping a static binary,
so audio extraction needs no system package.
"""

import asyncio
import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from clearframe.audio import AUDIO_DETECTOR, ranges_to_offsets, sample_offsets
from clearframe.models import AudioMatch, AudioProvenance

log = logging.getLogger("clearframe.audio")

AUDD_ENDPOINT = "https://api.audd.io/"

# Catalogues whose presence turns a crowd-fed row into an attributable one.
_CATALOGUES = ("spotify", "apple_music", "deezer", "musicbrainz", "napster")


def ffmpeg_exe() -> str:
    """Path to the bundled static ffmpeg (never the system one)."""
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def extract_segment(
    video_path: str, offset_s: float, segment_s: float, out_path: Path
) -> Path | None:
    """Cut one mono MP3 sample. Returns None if extraction produced nothing."""
    cmd = [
        ffmpeg_exe(),
        "-nostdin", "-loglevel", "error", "-y",
        "-ss", f"{offset_s:.3f}",
        "-t", f"{segment_s:.3f}",
        "-i", str(video_path),
        "-vn", "-ac", "1", "-ar", "44100", "-b:a", "128k",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        log.warning("audio extraction failed at %.1fs (%s)", offset_s, exc)
        return None
    return out_path if out_path.exists() and out_path.stat().st_size > 1024 else None


def parse_audd_response(payload: dict, at_s: float) -> list[AudioMatch]:
    """AudD /recognize -> AudioMatch. Shared by the live and fixture clients.

    A no-match is `{"status": "success", "result": null}`; an unusable key is
    `{"status": "error", ...}`. Neither is exceptional — both mean "no identity
    from this source", which downstream reads as SINGLE_SOURCE.
    """
    if not isinstance(payload, dict) or payload.get("status") != "success":
        return []
    result = payload.get("result")
    if not result:
        return []
    rows = result if isinstance(result, list) else [result]

    matches: list[AudioMatch] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = (row.get("title") or "").strip()
        if not title:
            continue
        catalogues = [c for c in _CATALOGUES if row.get(c)]
        isrc = ""
        apple = row.get("apple_music") or {}
        if isinstance(apple, dict):
            isrc = (apple.get("isrc") or "").strip()
        matches.append(
            AudioMatch(
                title=title,
                artist=(row.get("artist") or "").strip(),
                album=(row.get("album") or "").strip(),
                label=(row.get("label") or "").strip(),
                release_date=(row.get("release_date") or "").strip(),
                isrc=isrc,
                song_link=(row.get("song_link") or "").strip(),
                at_s=at_s,
                confidence=1.0 if catalogues else 0.75,
                provenance=(
                    AudioProvenance.VERIFIED if catalogues else AudioProvenance.UNVERIFIED
                ),
                catalogues=catalogues,
            )
        )
    return matches


class AudioIdClient(Protocol):
    name: str

    async def identify(
        self,
        footage_uri: str,
        duration_s: float,
        ranges: list[tuple[float, float]] | None = None,
    ) -> list[AudioMatch]: ...


class FixtureAudioClient:
    """Replays genuine AudD payloads through the live parser."""

    name = AUDIO_DETECTOR

    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = Path(fixtures_dir)

    async def identify(
        self,
        footage_uri: str,
        duration_s: float,
        ranges: list[tuple[float, float]] | None = None,
    ) -> list[AudioMatch]:
        path = self.fixtures_dir / "audio" / "demo_scene_audio.json"
        if not path.exists():
            return []
        samples = json.loads(path.read_text())
        matches: list[AudioMatch] = []
        for sample in samples:
            matches.extend(
                parse_audd_response(sample["payload"], at_s=float(sample["at_s"]))
            )
        return matches


class LiveAudDClient:
    """AudD /recognize over extracted samples.

    Best-effort by design, exactly like the logo corroborator: no token, no
    network, a rejected key or a failed extraction all degrade music identity
    to SINGLE_SOURCE rather than stopping the pipeline. An unavailable second
    opinion is not a contradiction.
    """

    name = AUDIO_DETECTOR

    def __init__(
        self,
        api_token: str,
        segment_s: float = 15.0,
        max_samples: int = 4,
        timeout_s: float = 30.0,
    ):
        self.api_token = api_token
        self.segment_s = segment_s
        self.max_samples = max_samples
        self.timeout_s = timeout_s

    def _recognise(self, sample: Path, at_s: float) -> list[AudioMatch]:
        import httpx

        with sample.open("rb") as fh:
            response = httpx.post(
                AUDD_ENDPOINT,
                data={"api_token": self.api_token, "return": "apple_music,spotify"},
                files={"file": (sample.name, fh, "audio/mpeg")},
                timeout=self.timeout_s,
            )
        response.raise_for_status()
        return parse_audd_response(response.json(), at_s=at_s)

    async def identify(
        self,
        footage_uri: str,
        duration_s: float,
        ranges: list[tuple[float, float]] | None = None,
    ) -> list[AudioMatch]:
        if footage_uri.startswith("gs://"):
            log.warning("audio fingerprinting needs a local file; got %s", footage_uri)
            return []
        if not Path(footage_uri).exists():
            log.warning("audio fingerprinting: footage not found at %s", footage_uri)
            return []

        offsets = (
            ranges_to_offsets(ranges, self.segment_s, self.max_samples)
            if ranges
            else sample_offsets(duration_s, self.segment_s, self.max_samples)
        )

        def _run() -> list[AudioMatch]:
            matches: list[AudioMatch] = []
            with tempfile.TemporaryDirectory(prefix="clearframe-audio-") as tmp:
                for i, offset in enumerate(offsets):
                    sample = extract_segment(
                        footage_uri, offset, self.segment_s, Path(tmp) / f"s{i}.mp3"
                    )
                    if sample is None:
                        continue
                    try:
                        matches.extend(self._recognise(sample, at_s=offset))
                    except Exception as exc:  # network, auth, quota
                        log.warning("fingerprint lookup failed at %.1fs (%s)", offset, exc)
            return _dedupe(matches)

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            log.warning(
                "audio fingerprinting unavailable (%s); music stays single-source", exc
            )
            return []


def _dedupe(matches: list[AudioMatch]) -> list[AudioMatch]:
    """One row per recording, keeping the best-attested and earliest sighting."""
    best: dict[tuple[str, str], AudioMatch] = {}
    for m in matches:
        key = (m.title.casefold(), m.artist.casefold())
        current = best.get(key)
        if current is None:
            best[key] = m
            continue
        better = (
            m.provenance is AudioProvenance.VERIFIED
            and current.provenance is not AudioProvenance.VERIFIED
        )
        best[key] = m.model_copy(update={"at_s": min(current.at_s, m.at_s)}) if better else (
            current.model_copy(update={"at_s": min(current.at_s, m.at_s)})
        )
    return sorted(best.values(), key=lambda m: m.at_s)
