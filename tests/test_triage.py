from clearframe.models import (
    BBox,
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Prominence,
    TimeRange,
)
from clearframe.triage import triage


def det(id, label, t, start, end, st=2.0, cov=0.1, cen=0.5, plot=False):
    return DetectedElement(
        id=id,
        label=label,
        element_type=t,
        description="d",
        time_ranges=[TimeRange(start_s=start, end_s=end)],
        prominence=Prominence(
            screen_time_s=st, frame_coverage=cov, centrality=cen, plot_integral=plot
        ),
    )


def test_tattoo_maps_to_copyright():
    out = triage([det("a", "tribal tattoo", ElementType.TATTOO, 0, 2)])
    assert out[0].category == ClearanceCategory.COPYRIGHT_ART


def test_duplicates_merge_across_shots():
    out = triage(
        [
            det("a", "Nike hoodie", ElementType.LOGO, 0, 5, st=5),
            det("b", "nike hoodie ", ElementType.LOGO, 20, 30, st=10, cov=0.2, plot=True),
        ]
    )
    assert len(out) == 1
    merged = out[0]
    assert merged.prominence.screen_time_s == 15
    assert merged.prominence.frame_coverage == 0.2
    assert merged.prominence.plot_integral is True
    assert [r.start_s for r in merged.time_ranges] == [0, 20]


# The two rectangles the deployed run actually stored for the sticker. The LOGO
# box sits entirely inside the ARTWORK one — containment 1.00 — while their IoU
# is 0.207, under SAME_REGION_IOU, because IoU punishes containment whenever the
# two extents differ in scale.
_STICKER_TIGHT = {"ymin": 0.332, "xmin": 0.518, "ymax": 0.381, "xmax": 0.579}
_STICKER_WIDE = {"ymin": 0.301, "xmin": 0.501, "ymax": 0.412, "xmax": 0.631}
_ELSEWHERE = {"ymin": 0.70, "xmin": 0.05, "ymax": 0.90, "xmax": 0.30}


def _sighting(eid, label, etype, start, end, box, reliable=True):
    return DetectedElement(
        id=eid,
        label=label,
        element_type=etype,
        description=f"{label} seen by a pass",
        time_ranges=[TimeRange(start_s=start, end_s=end, bbox=BBox(**box))],
        prominence=Prominence(screen_time_s=end - start, frame_coverage=0.01,
                              centrality=0.5, plot_integral=False),
        timing_reliable=reliable,
    )


def _the_live_sticker_pair():
    return [
        _sighting("5", "Sticker on water heater", ElementType.LOGO,
                  0.31, 0.33, _STICKER_TIGHT, reliable=False),
        _sighting("b3f0", "Sticker on water heater", ElementType.ARTWORK,
                  31.9, 33.7, _STICKER_WIDE),
    ]


def test_one_sticker_is_not_a_trademark_finding_and_a_copyright_finding():
    """The duplicate a deployed run shipped, with two bands and two routes.

    `Sticker on water heater` came back twice from the same run — id `5` typed
    LOGO/TRADEMARK with a broken clock, and another typed ARTWORK/COPYRIGHT_ART
    with a good one. Byte-identical labels. `triage` never even compared them,
    because grouping requires one element type and only TEXT yields.

    That rule is right for SIMILAR labels — `CLAUDE.md` records "LOGO vs ARTWORK
    still stays two findings" as deliberate, and a Nike swoosh and a Nike mural
    really are two things. It is wrong on an identical one backed by a second
    signal, and what it produced here is the most consequential failure this
    codebase knows: one object wearing two owners, two routes and two bands.
    """
    merged = triage(_the_live_sticker_pair())

    assert len(merged) == 1, (
        f"one sticker came out as {len(merged)} findings: "
        f"{[(e.label, e.element_type, e.category) for e in merged]}"
    )


def test_the_sighting_with_a_working_clock_decides_the_type():
    """Which of the two categories survives is not a coin toss.

    The same rule `CLAUDE.md` records for timecodes — "a broken clock stopped
    outvoting a working one" — decides the type too: the sighting whose
    timecodes survive the physical test is the one there is reason to trust.
    """
    merged = triage(_the_live_sticker_pair())

    assert merged[0].element_type is ElementType.ARTWORK
    assert merged[0].category is ClearanceCategory.COPYRIGHT_ART
    assert merged[0].timing_reliable is True


def test_two_different_objects_sharing_a_name_stay_two_findings():
    """The rule must not swallow the case it was carved around.

    A Nike swoosh on a shoe and a Nike mural on a wall are genuinely two things
    and both may be labelled "Nike". They are in different parts of the frame,
    so nothing says they are one object — and over-merging DELETES a finding,
    which is the failure this module exists to prevent.
    """
    merged = triage([
        _sighting("1", "Nike", ElementType.LOGO, 2.0, 4.0, _STICKER_TIGHT),
        _sighting("2", "Nike", ElementType.ARTWORK, 2.0, 4.0, _ELSEWHERE),
    ])

    assert len(merged) == 2


def test_an_identical_label_alone_is_not_enough_to_cross_the_type_boundary():
    """Place has to agree too. Without a locating box on both sides there is no
    second signal, and a label is exactly what the type check was protecting
    against being trusted on its own."""
    merged = triage([
        _sighting("1", "Nike", ElementType.LOGO, 2.0, 4.0, _STICKER_TIGHT),
        _sighting("2", "Nike", ElementType.ARTWORK, 30.0, 34.0, _STICKER_WIDE),
    ])

    assert len(merged) == 2


def test_a_near_miss_label_across_types_still_stays_two_findings():
    """Only EXACT label equality opens the door at all. `labels_match` at any
    threshold is not enough — that is the whole reason the type check was there
    in the first place."""
    merged = triage([
        _sighting("1", "Sticker on water heater", ElementType.LOGO,
                  0.31, 0.33, _STICKER_TIGHT, reliable=False),
        _sighting("2", "Sticker on the wall", ElementType.ARTWORK,
                  31.9, 33.7, _STICKER_WIDE),
    ])

    assert len(merged) == 2


def test_a_third_sighting_joins_the_group_it_matches_not_just_its_first_member():
    """Grouping compared each candidate against a group's FIRST member only.

    A live run has three sightings of one sticker: a LOGO with a broken clock,
    an ARTWORK, and `"Drink Beer" Sticker` — the same ARTWORK described more
    fully, colocated with it. With first-member matching the LOGO joined the
    group and the third was then compared against the LOGO alone: different
    type, different words, so it split off. Adding a merge rule made the finding
    count go UP, which is the tell that group identity was being decided by
    arrival order rather than by evidence.
    """
    merged = triage([
        _sighting("5", "Sticker on water heater", ElementType.LOGO,
                  0.31, 0.33, _STICKER_TIGHT, reliable=False),
        _sighting("b3f0", "Sticker on water heater", ElementType.ARTWORK,
                  32.1, 33.4, _STICKER_WIDE),
        _sighting("6", '"Drink Beer" Sticker', ElementType.ARTWORK,
                  31.9, 33.7, _STICKER_WIDE),
    ])

    assert len(merged) == 1, (
        f"three sightings of one sticker came out as {len(merged)} findings: "
        f"{[e.label for e in merged]}"
    )


def test_grouping_does_not_depend_on_the_order_the_passes_arrived_in():
    """Three concurrent scans have no defined order between them."""
    a = _sighting("5", "Sticker on water heater", ElementType.LOGO,
                  0.31, 0.33, _STICKER_TIGHT, reliable=False)
    b = _sighting("b3f0", "Sticker on water heater", ElementType.ARTWORK,
                  32.1, 33.4, _STICKER_WIDE)
    c = _sighting("6", '"Drink Beer" Sticker', ElementType.ARTWORK,
                  31.9, 33.7, _STICKER_WIDE)

    assert len(triage([a, b, c])) == len(triage([c, b, a])) == len(triage([b, a, c]))
