"""Pull one frame out of the footage so it can be grounded on its own.

Boxes currently come from the video pass, and the video pass is where three
separate defects lived: transposed axes, one rectangle painted across four
shots, and appearances of twenty milliseconds. Each was patched individually
and none of the patches stops the next, because Gemini samples video at about
1fps and returns ONE box per time range — a union of where the subject
travelled, not where it is in any frame.

A still image is a different and much stronger grounding problem: full
resolution, no sampling, no temporal union. The control experiment on a Code
Geass frame put a box exactly on a framed painting the video path missed
entirely, and tight on a helmet the video path drew around a sofa.

This is the extraction half. It has to fail quietly — a missing frame means no
refined box, which is the behaviour the player already handles.
"""

import pathlib
import subprocess

import pytest

from clearframe.media import extract_frame

CLIP = pathlib.Path(
    "/Users/aryansinghpokharia/Desktop/clearframe_google/out-live-ui/media/upload/footage.mp4"
)


def _has_ffmpeg() -> bool:
    try:
        import imageio_ffmpeg

        imageio_ffmpeg.get_ffmpeg_exe()
        return True
    except Exception:
        return False


needs_clip = pytest.mark.skipif(
    not CLIP.exists() or not _has_ffmpeg(), reason="needs local footage + ffmpeg"
)


def test_a_missing_file_yields_no_frame_rather_than_raising(tmp_path):
    assert extract_frame(tmp_path / "nope.mp4", 1.0) is None


def test_a_negative_timestamp_is_refused(tmp_path):
    assert extract_frame(tmp_path / "nope.mp4", -1.0) is None


@needs_clip
def test_a_real_frame_comes_back_as_jpeg_bytes():
    data = extract_frame(CLIP, 12.0)
    assert data is not None
    # JPEG SOI marker — proof it is an image and not an ffmpeg error string.
    assert data[:2] == b"\xff\xd8"
    assert len(data) > 2000


@needs_clip
def test_different_timestamps_give_different_frames():
    a, b = extract_frame(CLIP, 2.0), extract_frame(CLIP, 30.0)
    assert a and b and a != b


@needs_clip
def test_a_timestamp_past_the_end_yields_nothing():
    assert extract_frame(CLIP, 9_999.0) is None
