"""Probing uploaded footage. The only module that reads a video file directly.

Kept separate from `integrations/` because it calls no third-party service —
just the ffmpeg binary that ships with the package via `imageio-ffmpeg`.

It exists because the upload form never asked for a duration and nothing
measured one, so every upload arrived declaring `duration_s = 0.0`. That is
not cosmetic: `audio.sample_offsets(0.0)` returns a single offset, so a
49-second clip got one fingerprint sample at the head instead of four spread
across it — which is exactly how a track that only becomes audible late gets
missed, the failure that motivated fingerprinting in the first place.
"""

import logging
import re
import subprocess
from pathlib import Path

log = logging.getLogger("clearframe.media")

_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
# "... 1280x720 [SAR 1:1 DAR 16:9], 499 kb/s, 30 fps, 30 tbr, ..."
_FPS = re.compile(r"(\d+(?:\.\d+)?)\s*fps")


def probe_duration_s(path: str | Path) -> float:
    """Seconds of footage, or 0.0 if the file cannot be probed.

    Returning 0.0 rather than raising is deliberate: an unprobeable upload
    degrades to the behaviour every upload had until now, instead of failing a
    run over a number the pipeline can survive without.
    """
    path = Path(path)
    if not path.exists():
        return 0.0
    try:
        import imageio_ffmpeg

        # ffmpeg with no output writes the stream summary to stderr and exits
        # non-zero; that is the expected path, not an error.
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError, ImportError) as exc:
        log.warning("could not probe %s (%s)", path.name, exc)
        return 0.0

    match = _DURATION.search(result.stderr or "")
    if match is None:
        log.warning("no duration in ffmpeg output for %s", path.name)
        return 0.0
    hours, minutes, seconds = match.groups()
    return round(int(hours) * 3600 + int(minutes) * 60 + float(seconds), 2)


def probe_fps(path: str | Path) -> float:
    """Frames per second, or 0.0 if the file cannot be probed.

    The upload form defaults fps to 24 and nothing corrected it, which is not
    cosmetic either. `timeline.timing_is_reliable` decides whether an
    appearance was ever photographed by comparing it against ONE FRAME, and a
    frame is 1/fps. A 30fps clip judged at 24fps uses 42ms where the truth is
    33ms, so the module whose whole claim is "physical tests only, no
    threshold to defend" was defending a guessed one.

    Same degradation contract as `probe_duration_s`: 0.0 lets the caller keep
    whatever it had rather than failing a run over it.
    """
    path = Path(path)
    if not path.exists():
        return 0.0
    try:
        import imageio_ffmpeg

        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-i", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError, ImportError) as exc:
        log.warning("could not probe fps of %s (%s)", path.name, exc)
        return 0.0

    match = _FPS.search(result.stderr or "")
    if match is None:
        log.warning("no frame rate in ffmpeg output for %s", path.name)
        return 0.0
    fps = float(match.group(1))
    # A rate outside this range is a parse accident, not a camera.
    return fps if 1.0 <= fps <= 240.0 else 0.0


def extract_frame(path: str | Path, at_s: float, width: int = 1280) -> bytes | None:
    """One JPEG frame at `at_s`, or None if it cannot be produced.

    Grounding a still is a different problem from grounding a video. Gemini
    samples video at roughly 1fps and returns ONE box per time range, so a box
    for a moving subject is a union of where it travelled rather than where it
    is in any frame — which is why boxes are drawn only while paused, and why
    three separate box defects all traced back to the same place.

    Returning None rather than raising is deliberate and matches
    `probe_duration_s`: a frame that cannot be produced means no refined box,
    which is exactly what the player already renders when a position is
    unknown. A failed extraction must never take a run down.

    Seeking before -i is the fast path — ffmpeg jumps to the nearest keyframe
    instead of decoding from the start, which is what makes this viable
    per-pause rather than per-run.
    """
    path = Path(path)
    if not path.exists() or at_s < 0:
        return None
    try:
        import imageio_ffmpeg

        result = subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-nostdin",
                "-ss", f"{at_s:.3f}",
                "-i", str(path),
                "-frames:v", "1",
                "-vf", f"scale={width}:-2",
                "-f", "image2",
                "-c:v", "mjpeg",
                "-q:v", "3",
                "-",
            ],
            capture_output=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError, ImportError) as exc:
        log.warning("could not extract frame at %.2fs from %s (%s)", at_s, path.name, exc)
        return None

    data = result.stdout or b""
    # A seek past the end exits cleanly with no output, so emptiness is the
    # signal rather than the return code.
    if not data.startswith(b"\xff\xd8"):
        return None
    return data
