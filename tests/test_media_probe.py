"""Uploaded footage must declare its real duration.

The upload form never asked for a duration and nothing probed the file, so
every upload arrived as `duration_s = 0.0`. A 49.5-second clip therefore got a
single audio sample at the head instead of four spread across it — which is
precisely how a track that only becomes audible late gets missed, the failure
that motivated fingerprinting in the first place.

ffmpeg ships with the package now. Nothing should be guessing.
"""

import pathlib

import pytest

from clearframe.media import probe_duration_s


CLIP = pathlib.Path("testdata/clips/ctvc_BAYER_512kb.mp4")


@pytest.mark.skipif(not CLIP.exists(), reason="run ./scripts/fetch_test_clips.sh")
def test_a_real_clip_reports_its_real_duration():
    assert probe_duration_s(CLIP) == pytest.approx(30.0, abs=0.5)


def test_a_missing_file_returns_zero_rather_than_raising():
    """An unprobeable upload must not fail the run — it degrades to the old
    behaviour, which is what every upload did until now anyway."""
    assert probe_duration_s(pathlib.Path("/nope/missing.mp4")) == 0.0


def test_a_file_that_is_not_video_returns_zero(tmp_path):
    junk = tmp_path / "notavideo.mp4"
    junk.write_bytes(b"this is not an mp4")
    assert probe_duration_s(junk) == 0.0


@pytest.mark.skipif(not CLIP.exists(), reason="run ./scripts/fetch_test_clips.sh")
def test_the_duration_drives_how_widely_audio_is_sampled():
    """The reason this matters at all."""
    from clearframe.audio import sample_offsets

    assert sample_offsets(0.0) == [0.0]
    spread = sample_offsets(probe_duration_s(CLIP))
    assert len(spread) > 1
    assert spread[-1] > 0
