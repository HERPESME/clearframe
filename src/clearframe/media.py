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
