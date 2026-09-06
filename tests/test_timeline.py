"""Timecodes the scan cannot possibly have measured.

On a live clip of The Hangover Part II, Gemini reported Stu's face tattoo as
six appearances totalling 0.15 seconds — each one 20-30ms, shorter than a
single frame at 24fps — while reporting in the same breath that it was on
screen for 10 seconds. The other seven findings in that response reconciled
exactly, 1.0x. One element's timeline was in a different unit.

The consequence was invisible in the analysis and infuriating in the player:
the tattoo listed with timecodes, and no box at any moment a human hand can
pause on. A 20ms window cannot be hit with a mouse.

We do not guess the unit. Two candidate scales (minutes, fraction-of-clip)
both fit inside the clip, so repairing would be picking one — and this
codebase's rule is that a confidently wrong rectangle is worse than none.
What we can do is prove the numbers are impossible and say so.
"""

import pytest

from clearframe.models import DetectedElement, ElementType, Prominence, TimeRange
from clearframe.timeline import clamp_to_footage, timing_is_reliable


def element(ranges: list[tuple[float, float]], screen_time_s: float = 10.0):
    return DetectedElement(
        id="1",
        label="Stu's Face Tattoo",
        element_type=ElementType.TATTOO,
        description="",
        time_ranges=[TimeRange(start_s=a, end_s=b) for a, b in ranges],
        prominence=Prominence(
            screen_time_s=screen_time_s,
            frame_coverage=0.2,
            centrality=0.6,
            plot_integral=True,
        ),
    )


def test_an_appearance_shorter_than_a_frame_is_not_believable():
    """The Hangover fact pattern: six sightings totalling 0.15s."""
    tattoo = element(
        [(0.05, 0.07), (0.10, 0.13), (0.15, 0.18), (0.20, 0.22), (0.25, 0.27), (0.35, 0.38)]
    )
    ok, reason = timing_is_reliable(tattoo, duration_s=41.5, fps=24.0)
    assert ok is False
    assert "frame" in reason.lower()


def test_ordinary_appearances_are_believed():
    """The other seven findings in that same response."""
    watch = element([(2.8, 4.5), (8.2, 10.8), (22.8, 25.5), (28.0, 30.0)], 8.8)
    ok, reason = timing_is_reliable(watch, duration_s=41.5, fps=24.0)
    assert ok is True, reason
    assert reason == ""


def test_an_appearance_past_the_end_of_the_clip_is_not_believable():
    stray = element([(2.0, 4.0), (58.0, 61.0)])
    ok, reason = timing_is_reliable(stray, duration_s=41.5, fps=24.0)
    assert ok is False
    assert "clip" in reason.lower()


def test_a_finding_with_no_timecodes_at_all_is_not_believable():
    assert timing_is_reliable(element([]), duration_s=41.5, fps=24.0)[0] is False


def test_an_unknown_duration_does_not_condemn_a_finding():
    """duration_s is 0.0 on states written before media.probe_duration_s."""
    watch = element([(2.8, 4.5), (28.0, 30.0)], 8.8)
    assert timing_is_reliable(watch, duration_s=0.0, fps=24.0)[0] is True


def test_what_counts_as_possible_follows_the_frame_rate():
    """A 10ms sighting is under a frame at 60fps (16.7ms), over it at 120fps."""
    brief = element([(1.00, 1.01)], 0.01)
    assert timing_is_reliable(brief, duration_s=41.5, fps=60.0)[0] is False
    assert timing_is_reliable(brief, duration_s=41.5, fps=120.0)[0] is True


def test_the_reason_reports_the_contradiction_it_found():
    """A human reading the dossier needs the evidence, not just a verdict."""
    tattoo = element([(0.05, 0.07), (0.10, 0.13)], screen_time_s=10.0)
    _, reason = timing_is_reliable(tattoo, duration_s=41.5, fps=24.0)
    assert "10" in reason and "0.05" in reason


# --- the read path -----------------------------------------------------------
#
# Every analysis completed before this module existed carries the default of
# "believable", including the run that found the bug. Deriving on read means an
# old state gets the right answer without being rewritten on disk.


def test_an_old_state_is_corrected_when_it_is_read(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from clearframe.webapp.server import create_app

    state = {
        "production": {
            "id": "old", "title": "Pre-timeline run",
            "footage_uri": "clip.mp4", "duration_s": 41.5, "fps": 24.0,
        },
        "elements": [
            {
                "id": "1", "label": "Stu's Face Tattoo", "element_type": "TATTOO",
                "description": "", "category": "COPYRIGHT_ART",
                "time_ranges": [
                    {"start_s": 0.05, "end_s": 0.07},
                    {"start_s": 0.10, "end_s": 0.13},
                ],
                "prominence": {
                    "screen_time_s": 10.0, "frame_coverage": 0.2,
                    "centrality": 0.6, "plot_integral": True,
                },
            },
            {
                "id": "2", "label": "Wristwatch", "element_type": "LOGO",
                "description": "", "category": "TRADEMARK",
                "time_ranges": [{"start_s": 2.8, "end_s": 4.5}],
                "prominence": {
                    "screen_time_s": 1.7, "frame_coverage": 0.2,
                    "centrality": 0.5, "plot_integral": False,
                },
            },
        ],
    }
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "old.json").write_text(json.dumps(state))

    client = TestClient(create_app(out_root=tmp_path))
    body = client.get("/api/productions/old").json()
    by_label = {e["label"]: e for e in body["elements"]}

    tattoo = by_label["Stu's Face Tattoo"]
    assert tattoo["timing_reliable"] is False
    assert "frame" in tattoo["timing_note"].lower()

    # The believable finding beside it is untouched.
    assert by_label["Wristwatch"]["timing_reliable"] is True
    assert by_label["Wristwatch"]["timing_note"] == ""

    # And the finding itself survives — only its timing was disowned.
    assert len(body["elements"]) == 2


def _spanning(end_s: float, start_s: float = 0.0, screen_time: float = 41.5):
    """One appearance that runs to (or past) the end of a 41.5s clip."""
    return DetectedElement(
        id="1",
        label="Bangkok Hotel Room",
        element_type=ElementType.LOCATION,
        description="the room the scene is set in",
        time_ranges=[TimeRange(start_s=start_s, end_s=end_s)],
        prominence=Prominence(
            screen_time_s=screen_time, frame_coverage=0.9,
            centrality=0.5, plot_integral=True,
        ),
    )


def test_a_rounding_overshoot_past_the_last_frame_is_clamped_not_disowned():
    """The finding a live run lost to a tenth of a second.

    `Bangkok Hotel Room` was reported ending at **41.60s in a 41.50s clip** and
    was disowned for it — losing its place on the timeline and every rectangle
    it had. But the sub-frame test did not fire and its ranges reconcile against
    its own screen time, so this is not a unit error: it is the model rounding
    past the last frame.

    Clamping is not the unit-guessing this module rightly refuses. Choosing
    between minutes and fraction-of-clip would be picking one of two answers
    that both land inside the clip; saying that an appearance running past the
    end of the footage ends at the end of the footage is a physical fact. The
    last frame is the last frame.
    """
    el = clamp_to_footage(_spanning(41.60), duration_s=41.5)

    assert el.time_ranges[0].end_s == pytest.approx(41.5)
    ok, _ = timing_is_reliable(el, 41.5, 30.0)
    assert ok, "the finding still lost its timeline"


def test_an_overshoot_too_large_to_be_rounding_is_left_to_be_disowned():
    """A whole minute past the end of a 41.5s clip is a different number, not a
    rounded one. Clamping it would invent an appearance nobody photographed —
    and `overlay.py`'s rule is that a confidently wrong answer is worse than
    none."""
    el = clamp_to_footage(_spanning(101.5), duration_s=41.5)

    assert el.time_ranges[0].end_s == 101.5, "a wild timecode was quietly repaired"
    ok, _ = timing_is_reliable(el, 41.5, 30.0)
    assert not ok


def test_a_range_starting_past_the_end_is_never_clamped():
    """Clamping the end of a range that begins after the last frame would
    produce `end_s <= start_s`, which is not an appearance at all."""
    el = clamp_to_footage(_spanning(41.7, start_s=41.6), duration_s=41.5)

    assert el.time_ranges[0].start_s == 41.6 and el.time_ranges[0].end_s == 41.7
    ok, _ = timing_is_reliable(el, 41.5, 30.0)
    assert not ok


def test_an_unknown_duration_clamps_nothing():
    """`probe_duration_s` returns 0.0 rather than raising, and states written
    before it existed carry 0.0 too. An unknown duration must never be evidence
    against a finding."""
    el = clamp_to_footage(_spanning(41.60), duration_s=0.0)

    assert el.time_ranges[0].end_s == 41.60


def test_timecodes_inside_the_clip_are_returned_untouched():
    """The overwhelmingly common case must not allocate a new model or move a
    single number."""
    original = _spanning(41.0)

    assert clamp_to_footage(original, duration_s=41.5) is original
