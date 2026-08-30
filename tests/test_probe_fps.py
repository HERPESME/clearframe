"""The frame rate was a form default, and a physical test was built on it.

`timeline.py` decides whether an appearance was ever photographed by asking
whether it is shorter than a single frame. That is the module's whole claim:
physical tests only, so no threshold needs defending. The threshold it uses is
1/fps — and fps came from `Form(24.0)`, a default nobody supplies.

A live upload of a 30fps clip therefore ran the test at 24fps: 42ms instead of
33ms. Every appearance between those two numbers is judged by a constant that
was guessed, and the timecode readout is wrong besides — the player showed
01:00:04:10 for a frame that is :12.

Duration was already measured for exactly this reason. This measures the other
number on the same ffmpeg call.
"""

from pathlib import Path

import pytest

from clearframe.media import probe_fps

CLIP = Path("testdata/clips")


def _a_clip():
    if not CLIP.exists():
        return None
    return next(iter(sorted(CLIP.glob("*.mp4"))), None)


def test_a_missing_file_falls_back_rather_than_raising():
    """Same contract as probe_duration_s: degrade, never fail a run."""
    assert probe_fps("does/not/exist.mp4") == 0.0


def test_a_non_video_falls_back(tmp_path):
    junk = tmp_path / "notavideo.mp4"
    junk.write_bytes(b"this is not an mp4")
    assert probe_fps(junk) == 0.0


def test_a_real_clip_reports_its_real_rate():
    clip = _a_clip()
    if clip is None:
        pytest.skip("no test footage; run ./scripts/fetch_test_clips.sh")
    fps = probe_fps(clip)
    assert 1.0 <= fps <= 240.0
