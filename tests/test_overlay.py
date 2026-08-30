"""Which box to draw at time T — one per appearance, not one per element.

A finding that appears four times had a single rectangle, so the box measured
in the opening shot was painted onto a drawing-room wall three shots later.
Storing the box inside the appearance fixes that at the source: pause at 1s and
you get the scooter shot's box, pause at 27s and you get the table's, pause at
4s when nothing is on screen and you get nothing.
"""

import pytest

from clearframe.models import BBox, DetectedElement, ElementType, Prominence, TimeRange
from clearframe.overlay import box_at, visible_at


def box(y=0.3, x=0.4):
    return BBox(ymin=y, xmin=x, ymax=y + 0.1, xmax=x + 0.1)


def element(ranges, bbox=None, at_s=None):
    return DetectedElement(
        id="e1", label="Pizza Hut", element_type=ElementType.LOGO, description="",
        time_ranges=ranges, bbox=bbox, at_s=at_s,
        prominence=Prominence(screen_time_s=8.0, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
    )


# ------------------------------------------------- the per-appearance rule
def test_each_appearance_shows_its_own_box():
    el = element([
        TimeRange(start_s=0, end_s=5, bbox=box(0.30, 0.40)),
        TimeRange(start_s=23, end_s=28, bbox=box(0.70, 0.10)),
    ])
    assert box_at(el, 1.0).ymin == pytest.approx(0.30)
    assert box_at(el, 27.0).ymin == pytest.approx(0.70)


def test_nothing_is_drawn_between_appearances():
    el = element([
        TimeRange(start_s=0, end_s=5, bbox=box()),
        TimeRange(start_s=23, end_s=28, bbox=box()),
    ])
    assert box_at(el, 12.0) is None


def test_the_boundaries_are_inclusive():
    el = element([TimeRange(start_s=2, end_s=6, bbox=box())])
    assert box_at(el, 2.0) is not None
    assert box_at(el, 6.0) is not None
    assert box_at(el, 6.01) is None


def test_an_appearance_with_no_box_draws_nothing_but_still_counts_as_visible():
    """The element IS on screen; we just do not know where. Inventing a
    position would be worse than drawing none."""
    el = element([TimeRange(start_s=0, end_s=5)])
    assert box_at(el, 2.0) is None
    assert visible_at(el, 2.0) is True


# ------------------------------------------------------------ legacy states
def test_a_legacy_element_box_is_honoured_near_its_at_s():
    """States written before boxes moved into appearances carry one
    element-level box and an at_s. They must keep working."""
    el = element([TimeRange(start_s=0, end_s=30)], bbox=box(0.5, 0.5), at_s=12.0)
    assert box_at(el, 12.0) is not None
    assert box_at(el, 13.5) is not None


def test_a_legacy_box_is_not_smeared_across_the_whole_range():
    el = element([TimeRange(start_s=0, end_s=30)], bbox=box(), at_s=12.0)
    assert box_at(el, 25.0) is None


def test_a_legacy_box_with_no_at_s_falls_back_to_the_range():
    """Oldest states have neither per-range boxes nor a timestamp. Showing the
    box across the range is what they always did; keep it rather than losing
    every box on upgrade."""
    el = element([TimeRange(start_s=0, end_s=5)], bbox=box())
    assert box_at(el, 3.0) is not None
    assert box_at(el, 9.0) is None


def test_per_appearance_boxes_win_over_a_legacy_element_box():
    el = element(
        [TimeRange(start_s=0, end_s=5, bbox=box(0.10, 0.10))],
        bbox=box(0.90, 0.90), at_s=2.0,
    )
    assert box_at(el, 2.0).ymin == pytest.approx(0.10)


# ---------------------------------------------------------------- visibility
def test_visible_at_ignores_boxes_entirely():
    el = element([TimeRange(start_s=4, end_s=9)])
    assert visible_at(el, 6.0) is True
    assert visible_at(el, 2.0) is False


def test_an_element_with_no_ranges_is_never_visible():
    el = element([TimeRange(start_s=0, end_s=1)])
    el = el.model_copy(update={"time_ranges": []})
    assert visible_at(el, 0.5) is False
    assert box_at(el, 0.5) is None


# ------------------------------------------- a box that locates nothing
#
# Asked to place a person on a frame, the model answers with the frame:
# {0, 0, 1, 1} for "Stu Price (Ed Helms)" at 6s and again at 9s on a live run,
# while the IWC watch in the same shot came back pixel-accurate. A rectangle
# around the entire picture restates what the finding already says — that this
# is in the shot — and painted over every real box beneath it.

FULL_FRAME = BBox(ymin=0.0, xmin=0.0, ymax=1.0, xmax=1.0)


def test_a_box_around_the_whole_frame_is_not_drawn():
    el = element([TimeRange(start_s=0, end_s=5, bbox=FULL_FRAME)])
    assert box_at(el, 2.0) is None


def test_the_finding_is_still_on_screen():
    """Suppressing the rectangle must not suppress the finding.

    The player already has the honest phrasing for this — "on screen without a
    known position" — and it is the correct one here.
    """
    el = element([TimeRange(start_s=0, end_s=5, bbox=FULL_FRAME)])
    assert visible_at(el, 2.0) is True


def test_a_large_box_that_still_points_somewhere_is_drawn():
    """A close-up genuinely fills most of the frame. Only the whole of it goes."""
    big = BBox(ymin=0.05, xmin=0.05, ymax=0.95, xmax=0.95)  # 81% of frame
    el = element([TimeRange(start_s=0, end_s=5, bbox=big)])
    assert box_at(el, 2.0) is not None


def test_a_legacy_full_frame_box_is_suppressed_too():
    el = element([TimeRange(start_s=0, end_s=5)], bbox=FULL_FRAME, at_s=2.0)
    assert box_at(el, 2.0) is None
