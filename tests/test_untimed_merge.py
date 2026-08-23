"""When one pass's clock is broken, it must not outvote the pass whose is not.

Measured on a live re-run of the Hangover Part II clip. The second Gemini pass
returned every timecode as seconds divided by 100:

    pass 1  "Stu's Face Tattoo"        4.961  10.927  15.932  20.887  25.859
    pass 2  "Mike Tyson face tattoo"   .04971 .11244  .15915  .20920  .26126

Multiply by 100 and they are the same sightings of the same tattoo, agreeing
to within a few hundred milliseconds. `timeline.py` correctly disowned the
second set — a 9ms appearance was never photographed at 30fps — and then two
things went wrong downstream, both of which are about treating a broken clock
as if it carried information.

1. Three findings that HAD good timecodes lost them. "Dog T-shirt", "Calvin
   Klein" and "National" merged with their pass-2 twins on label alone, and
   the merge rule made disowned timing sticky, so the group inherited the
   broken clock and stopped drawing a box. That rule was written for a
   different case — one pass proving the timecodes impossible while the other
   is SILENT. A measurement that survives the physical test is not silence,
   and it beats one that failed it.

2. The tattoo pair could not merge at all. Colocation requires the two
   sightings to share an instant, and these two are in different units, so
   they look disjoint. Absence of temporal overlap is only evidence of
   difference if the timecodes mean anything — and we have already decided
   these do not.
"""

from clearframe.models import BBox, DetectedElement, ElementType, Prominence, TimeRange
from clearframe.triage import triage


def det(label, kind, appearances, reliable=True, description=""):
    return DetectedElement(
        id=label[:6], label=label, element_type=kind, description=description,
        timing_reliable=reliable,
        timing_note="" if reliable else "appearance shorter than one frame",
        time_ranges=[
            TimeRange(start_s=a, end_s=b, bbox=BBox(**box)) for a, b, box in appearances
        ],
        prominence=Prominence(screen_time_s=3.0, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
    )


# The real numbers, both units.
_GOOD = (4.961, 7.557, {"ymin": .425, "xmin": .511, "ymax": .646, "xmax": .810})
_BROKEN = (0.04971, 0.07974, {"ymin": .491, "xmin": .587, "ymax": .789, "xmax": .932})


def test_a_measured_clock_survives_a_merge_with_a_broken_one():
    """The regression that silently deleted three boxes."""
    out = triage([
        det("Dog T-shirt", ElementType.ARTWORK, [_GOOD]),
        det("Dog illustration on T-shirt", ElementType.ARTWORK, [_BROKEN], reliable=False),
    ])
    assert len(out) == 1
    assert out[0].timing_reliable is True
    assert out[0].time_ranges[0].start_s == 4.961


def test_the_broken_ranges_do_not_come_along():
    """A union with garbage in it is garbage. Only the measured ranges stand."""
    out = triage([
        det("Dog T-shirt", ElementType.ARTWORK, [_GOOD]),
        det("Dog illustration on T-shirt", ElementType.ARTWORK, [_BROKEN], reliable=False),
    ])
    assert [(r.start_s, r.end_s) for r in out[0].time_ranges] == [(4.961, 7.557)]


def test_a_group_with_no_usable_clock_stays_disowned():
    out = triage([
        det("Wristwatch", ElementType.LOGO, [_BROKEN], reliable=False),
        det("Wrist watch", ElementType.LOGO, [_BROKEN], reliable=False),
    ])
    assert len(out) == 1
    assert out[0].timing_reliable is False


# Both passes' full appearance lists for the tattoo, verbatim from the run.
# Best-matching pair scores IoU 0.56; the corner-clipping false pair scores
# 0.06. Single appearances are deliberately not enough — one box against one
# box tops out around 0.26 here, and under-merging is the safe direction.
_TATTOO_MEASURED = [
    (4.961, 7.557, {"ymin": .425, "xmin": .511, "ymax": .646, "xmax": .810}),
    (10.927, 13.513, {"ymin": .546, "xmin": .558, "ymax": .759, "xmax": .817}),
    (15.932, 18.068, {"ymin": .559, "xmin": .587, "ymax": .789, "xmax": .811}),
    (20.887, 22.840, {"ymin": .553, "xmin": .560, "ymax": .801, "xmax": .792}),
    (25.859, 27.694, {"ymin": .468, "xmin": .540, "ymax": .686, "xmax": .789}),
    (35.085, 38.655, {"ymin": .491, "xmin": .508, "ymax": .799, "xmax": .831}),
]
_TATTOO_BROKEN = [
    (0.04971, 0.07974, {"ymin": .491, "xmin": .587, "ymax": .789, "xmax": .932}),
    (0.11244, 0.13346, {"ymin": .495, "xmin": .593, "ymax": .794, "xmax": .932}),
    (0.15915, 0.18451, {"ymin": .490, "xmin": .582, "ymax": .811, "xmax": .927}),
    (0.20920, 0.22589, {"ymin": .495, "xmin": .567, "ymax": .820, "xmax": .920}),
    (0.26126, 0.27794, {"ymin": .492, "xmin": .565, "ymax": .813, "xmax": .917}),
    (0.31064, 0.31965, {"ymin": .427, "xmin": .521, "ymax": .579, "xmax": .761}),
    (0.35135, 0.39139, {"ymin": .260, "xmin": .588, "ymax": .465, "xmax": .841}),
]


def test_one_tattoo_whose_two_passes_disagree_about_the_unit():
    """The duplicate the user saw twice. Labels score 0.5; times never overlap."""
    out = triage([
        det("Stu's Face Tattoo", ElementType.TATTOO, _TATTOO_MEASURED,
            description="a tattoo on the left side of Stu's face"),
        det("Mike Tyson face tattoo", ElementType.TATTOO, _TATTOO_BROKEN,
            reliable=False,
            description="replicating Mike Tyson's tattoo, wrapping around his eye"),
    ])
    assert len(out) == 1
    assert out[0].timing_reliable is True
    # and it keeps the clock that works
    assert out[0].time_ranges[0].start_s == 4.961


def test_a_broken_clock_does_not_merge_things_in_different_places():
    """The wristwatch and the waistband are both untimed and both still findings."""
    out = triage([
        det("Wristwatch", ElementType.LOGO,
            [(0.02936, 0.04771, {"ymin": .509, "xmin": .583, "ymax": .574, "xmax": .634})],
            reliable=False),
        det("Calvin Klein", ElementType.LOGO,
            [(23.239, 25.408, {"ymin": .967, "xmin": .544, "ymax": .999, "xmax": .718})]),
    ])
    assert len(out) == 2


def test_a_broken_clock_does_not_merge_across_types():
    out = triage([
        det("Sticker", ElementType.ARTWORK, [_BROKEN], reliable=False),
        det("Sticker", ElementType.LOGO, [_GOOD]),
    ])
    assert len(out) == 2


def test_two_untimed_boxes_that_merely_touch_are_not_one_thing():
    """Aviator sunglasses vs a sticker on a water heater, from the same re-run.

    With no usable clock the only evidence left is the rectangle, so the
    rectangles have to describe the SAME REGION rather than merely overlap.
    These two clip a corner: intersection-over-union 0.06. The tattoo pair
    this rule exists to merge scores 0.56.

    The first draft of the relaxed rule merged them, and "Dr. Fixit Sticker"
    — a real finding, with a working clock — was deleted from the report,
    because the longer label wins a merge.
    """
    out = triage([
        det("Aviator sunglasses", ElementType.LOGO,
            [(0.338, 0.34901, {"ymin": .268, "xmin": .330, "ymax": .393, "xmax": .654})],
            reliable=False),
        det("Dr. Fixit Sticker", ElementType.LOGO,
            [(31.831, 33.083, {"ymin": .302, "xmin": .622, "ymax": .381, "xmax": .709})]),
    ])
    assert len(out) == 2
