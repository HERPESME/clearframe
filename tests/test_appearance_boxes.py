"""A merge must not paint one shot's rectangle across the next one.

The scan is told to split a moving element into shorter appearances, each
carrying the box for THAT appearance (`gemini_client.SCAN_PROMPT`). `_merge`
then unioned the ranges with a rule that welded anything touching, kept the
earlier range's box while widening the span, and dropped the box of any range
that fell inside another. With two independent passes the merge fires on
nearly every element, so the deliberate per-shot boxes were being collapsed
into one long range wearing the first box — exactly the defect `overlay.py`
was written to prevent, arriving through the back door.

The live corpus has the case verbatim: one pass reported the Hangover tattoo
as `(34.9, 36.5)` and `(36.5, 38.5)` with a rectangle each, the other reported
one coarse `(34.8, 39.3)`. All three collapsed to a single range and a single
box covering four and a half seconds of a moving face.

Ranges are now merged by COVERAGE: the finest measurement of any second wins,
absorbed ranges donate a box to a survivor that has none, and only a boxless
pair may weld. Screen time is unaffected — the output still tiles the covered
set exactly, so overlapping sightings still count once.
"""

from clearframe.models import BBox, DetectedElement, ElementType, Prominence, TimeRange
from clearframe.overlay import box_at
from clearframe.triage import MIN_SPLIT_S, merge_appearances, triage, union_spans


def box(ymin: float) -> BBox:
    """A distinguishable rectangle — the ymin identifies which one survived."""
    return BBox(ymin=ymin, xmin=0.1, ymax=min(ymin + 0.05, 1.0), xmax=0.4)


def rng(a: float, b: float, ymin: float | None = None) -> TimeRange:
    return TimeRange(start_s=a, end_s=b, bbox=None if ymin is None else box(ymin))


def det(label: str, ranges: list[TimeRange], screen_time_s: float = 1.0):
    return DetectedElement(
        id="1", label=label, element_type=ElementType.TATTOO, description="",
        time_ranges=ranges,
        prominence=Prominence(screen_time_s=screen_time_s, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
    )


def spans(el) -> list[tuple[float, float]]:
    return [(r.start_s, r.end_s) for r in el.time_ranges]


# --- the case that motivated all of this --------------------------------------


def test_per_shot_boxes_survive_a_merge_with_a_coarse_duplicate():
    """Two fine appearances and one coarse one describing the same seconds.

    The fine split is the scan doing what it was asked to do. The coarse range
    is the other pass's single union box over the same stretch — the thing
    grounding exists to correct. Keeping the split keeps two measurements;
    keeping the coarse range would keep the worst one and throw away both.
    """
    merged = triage([
        det("Face tattoo", [rng(0.0, 3.0, 0.1), rng(3.0, 6.0, 0.5)]),
        det("Face tattoo", [rng(0.0, 6.0, 0.9)]),
    ])[0]

    assert spans(merged) == [(0.0, 3.0), (3.0, 6.0)]
    assert [r.bbox.ymin for r in merged.time_ranges] == [0.1, 0.5]
    # Six seconds of screen time, not twelve: the ranges still tile the union.
    assert merged.prominence.screen_time_s == 6.0


def test_the_box_drawn_at_each_instant_is_the_one_measured_there():
    """The property the rectangles exist for, asserted through the overlay."""
    merged = triage([
        det("Face tattoo", [rng(0.0, 3.0, 0.1), rng(3.0, 6.0, 0.5)]),
        det("Face tattoo", [rng(0.0, 6.0, 0.9)]),
    ])[0]

    assert box_at(merged, 1.0).ymin == 0.1
    assert box_at(merged, 4.0).ymin == 0.5


def test_an_uncovered_tail_keeps_its_own_box():
    """The coarse range is not discarded — only the seconds already measured."""
    merged = triage([
        det("Face tattoo", [rng(0.0, 3.0, 0.1)]),
        det("Face tattoo", [rng(0.0, 6.0, 0.9)]),
    ])[0]

    assert spans(merged) == [(0.0, 3.0), (3.0, 6.0)]
    assert [r.bbox.ymin for r in merged.time_ranges] == [0.1, 0.9]
    assert merged.prominence.screen_time_s == 6.0


def test_a_survivor_without_a_box_adopts_one_from_the_range_it_absorbed():
    """A union box over a superset span is honest on the narrower span.

    It is also the only measurement there is. Preferring nothing would lose a
    rectangle the model actually returned.
    """
    merged = triage([
        det("Face tattoo", [rng(0.0, 6.0)]),
        det("Face tattoo", [rng(0.0, 6.0, 0.7)]),
    ])[0]

    assert spans(merged) == [(0.0, 6.0)]
    assert merged.time_ranges[0].bbox.ymin == 0.7


def test_the_tighter_measurement_wins_where_two_boxes_compete():
    """A box over a shorter span has less of the subject's travel folded in.

    The scan returns one rectangle per range, covering wherever the subject
    went during it. Between two rectangles for overlapping seconds, the one
    drawn for fewer seconds is the tighter claim — the same reasoning that
    makes a grounded still better than the video pass.
    """
    merged = triage([
        det("Face tattoo", [rng(2.0, 8.0, 0.9)]),
        det("Face tattoo", [rng(3.0, 5.0, 0.2)]),
    ])[0]

    at_four = box_at(merged, 4.0)
    assert at_four.ymin == 0.2


# --- measurement noise must not become a sub-frame range ----------------------


def test_a_sliver_of_disagreement_widens_a_range_instead_of_splitting_it():
    """Two passes disagreeing by a tenth of a second is noise, not a shot.

    Emitting the remainder would create a range shorter than a frame, which
    `timeline.timing_is_reliable` then disowns — and a disowned element draws
    no box at all. The neighbouring range simply covers it, keeping its own
    rectangle.
    """
    merged = triage([
        det("Face tattoo", [rng(4.8, 7.8, 0.3)]),
        det("Face tattoo", [rng(4.9, 7.9, 0.6)]),
    ])[0]

    assert spans(merged) == [(4.8, 7.9)]
    assert merged.time_ranges[0].bbox.ymin == 0.3
    assert merged.timing_reliable is True


def test_no_merged_range_is_shorter_than_the_sliver_floor():
    """The live tattoo pair, end to end: eight appearances against seven."""
    fine = [rng(4.8, 7.8, 0.1), rng(11.0, 13.2, 0.2), rng(15.8, 18.4, 0.3),
            rng(20.9, 22.5, 0.4), rng(25.8, 27.8, 0.5), rng(31.0, 32.0, 0.6),
            rng(34.9, 36.5, 0.7), rng(36.5, 38.5, 0.75)]
    coarse = [rng(4.9, 7.9, 0.15), rng(10.7, 13.4, 0.25), rng(15.6, 18.3, 0.35),
              rng(20.7, 22.7, 0.45), rng(25.6, 28.0, 0.55), rng(30.9, 33.2, 0.65),
              rng(34.8, 39.3, 0.8)]

    merged = triage([det("Stu's Face Tattoo", fine), det("Face Tattoo", coarse)])[0]

    assert all(r.duration_s >= MIN_SPLIT_S for r in merged.time_ranges)
    assert all(r.bbox is not None for r in merged.time_ranges)
    # The stretch that used to collapse into one rectangle keeps all three.
    late = [r for r in merged.time_ranges if r.start_s >= 34.0]
    assert len(late) == 3
    assert [r.bbox.ymin for r in late] == [0.7, 0.75, 0.8]


def test_merged_ranges_never_overlap_each_other():
    """The invariant screen time depends on: the output tiles the covered set."""
    merged = triage([
        det("Face tattoo", [rng(0.0, 10.0, 0.1), rng(4.0, 6.0, 0.2)]),
        det("Face tattoo", [rng(2.0, 12.0, 0.3), rng(11.0, 11.5, 0.4)]),
    ])[0]

    ordered = sorted(merged.time_ranges, key=lambda r: r.start_s)
    assert all(a.end_s <= b.start_s for a, b in zip(ordered, ordered[1:]))
    assert merged.prominence.screen_time_s == 12.0


# --- the boxless behaviour the old rule had, kept ----------------------------


def test_two_boxless_sightings_of_one_stretch_still_weld():
    """Nothing is lost by welding ranges that carry no rectangle.

    This is the shape `test_overlapping_sightings_merge_to_their_union` pins.
    Welding is only refused when it would put one range's box over another's
    seconds, and here there is no box to misplace.
    """
    merged = triage([
        det("Face tattoo", [rng(10.0, 20.0)]),
        det("Face tattoo", [rng(15.0, 25.0)]),
    ])[0]

    assert spans(merged) == [(10.0, 25.0)]


def test_separate_appearances_are_never_joined():
    merged = triage([
        det("Face tattoo", [rng(1.0, 3.0, 0.1)]),
        det("Face tattoo", [rng(30.0, 34.0, 0.2)]),
    ])[0]

    assert spans(merged) == [(1.0, 3.0), (30.0, 34.0)]
    assert merged.prominence.screen_time_s == 6.0


# --- union_spans: the boxless weld, kept as its own function -----------------


def test_union_spans_welds_touching_and_overlapping_intervals():
    """Used where boxes are irrelevant — unscanned ranges have none."""
    out = union_spans([rng(5.0, 8.0), rng(0.0, 3.0), rng(3.0, 6.0), rng(20.0, 21.0)])
    assert [(r.start_s, r.end_s) for r in out] == [(0.0, 8.0), (20.0, 21.0)]


def test_merge_appearances_is_stable_on_a_single_range():
    only = [rng(1.0, 2.0, 0.4)]
    assert [(r.start_s, r.end_s, r.bbox.ymin) for r in merge_appearances(only)] == [
        (1.0, 2.0, 0.4)
    ]
