"""Two passes seeing the same thing is not the thing appearing twice.

`triage._merge` summed `screen_time_s` across a group, which was right when the
only merge was scan + auditor finding DIFFERENT appearances of one element. It
is wrong the moment two independent passes both report the whole element: a
10-second tattoo seen by both passes became a 20-second tattoo, and prominence
drives the risk score.

Screen time is now derived from the UNION of the merged time ranges, so
overlapping sightings count once and genuinely separate ones still add up.
That is also more honest than the sum ever was — an element cannot be on
screen longer than the ranges saying where it is.
"""

from clearframe.models import DetectedElement, ElementType, Prominence, TimeRange
from clearframe.triage import triage


def det(label, ranges, screen_time_s, coverage=0.2, central=0.5, plot=False):
    return DetectedElement(
        id="1", label=label, element_type=ElementType.ARTWORK, description="",
        time_ranges=[TimeRange(start_s=a, end_s=b) for a, b in ranges],
        prominence=Prominence(screen_time_s=screen_time_s, frame_coverage=coverage,
                              centrality=central, plot_integral=plot),
    )


def test_the_same_sighting_from_two_passes_counts_once():
    both = [
        det("Street mural", [(10.0, 20.0)], 10.0),
        det("Street mural", [(10.0, 20.0)], 10.0),
    ]
    out = triage(both)
    assert len(out) == 1
    assert out[0].prominence.screen_time_s == 10.0


def test_overlapping_sightings_merge_to_their_union():
    out = triage([
        det("Street mural", [(10.0, 20.0)], 10.0),
        det("Street mural", [(15.0, 25.0)], 10.0),
    ])
    assert out[0].prominence.screen_time_s == 15.0
    assert [(r.start_s, r.end_s) for r in out[0].time_ranges] == [(10.0, 25.0)]


def test_separate_appearances_still_add_up():
    out = triage([
        det("Street mural", [(1.0, 3.0)], 2.0),
        det("Street mural", [(30.0, 34.0)], 4.0),
    ])
    assert out[0].prominence.screen_time_s == 6.0
    assert len(out[0].time_ranges) == 2


def test_the_strongest_reading_of_the_other_signals_wins():
    out = triage([
        det("Street mural", [(1.0, 3.0)], 2.0, coverage=0.1, central=0.2, plot=False),
        det("Street mural", [(1.0, 3.0)], 2.0, coverage=0.6, central=0.8, plot=True),
    ])
    p = out[0].prominence
    assert (p.frame_coverage, p.centrality, p.plot_integral) == (0.6, 0.8, True)


def test_a_single_detection_is_untouched():
    out = triage([det("Street mural", [(1.0, 3.0)], 9.9)])
    assert out[0].prominence.screen_time_s == 9.9


# --- merging must not lose what the scan reported -----------------------------
#
# `_merge` built a new DetectedElement field by field, so every field it did not
# name was silently dropped: siting, depiction, timing_reliable, bbox, at_s.
# It stayed invisible while merges were rare — an element had to be seen by both
# the scan and the auditor — and became routine the moment a second independent
# pass was added.
#
# The demo mural lost `siting="public_permanent"`, so freedom of panorama
# stopped applying to the one element in the fixture it was written for, and
# Germany stopped stepping the band down.


def test_merging_preserves_every_field_the_scan_reported():
    from clearframe.models import BBox, DepictionTone

    rich = det("Street mural", [(10.0, 20.0)], 10.0).model_copy(
        update={
            "siting": "public_permanent",
            "depiction": DepictionTone.UNFLATTERING,
            "at_s": 12.0,
            "bbox": BBox(ymin=0.1, xmin=0.1, ymax=0.5, xmax=0.5),
        }
    )
    plain = det("Street mural", [(15.0, 25.0)], 10.0)

    merged = triage([rich, plain])[0]

    assert merged.siting == "public_permanent"
    assert merged.depiction is DepictionTone.UNFLATTERING
    assert merged.at_s == 12.0
    assert merged.bbox is not None


def test_a_disowned_timeline_never_comes_back_through_a_merge():
    """The invariant this used to protect, stated where it actually lives.

    It used to assert that unreliable timing SURVIVES a merge, because
    `_merge` unioned every member's ranges — so a disowned member's garbage
    timecodes leaked into the group, and disowning the whole finding was the
    only safe answer.

    A disowned member now contributes no ranges at all, which removes the
    thing that had to be defended against. The stronger property is asserted
    directly: the bad ranges are gone.

    Inverting it mattered on a live re-run where the second Gemini pass
    returned every timecode as seconds divided by 100. Three findings that had
    been measured correctly by the first pass merged with their broken twins
    and stopped drawing a box — the disowned clock outvoting the working one.
    """
    bad = det("Street mural", [(60.0, 61.0)], 1.0).model_copy(
        update={"timing_reliable": False, "timing_note": "sub-frame appearances"}
    )
    merged = triage([bad, det("Street mural", [(10.0, 20.0)], 10.0)])[0]
    assert [(r.start_s, r.end_s) for r in merged.time_ranges] == [(10.0, 20.0)]
    assert merged.timing_reliable is True
    assert merged.timing_note == ""


def test_a_group_with_nothing_measurable_stays_disowned():
    """Sticky against silence, which is what the original rule was for."""
    bad = det("Street mural", [(10.0, 20.0)], 10.0).model_copy(
        update={"timing_reliable": False, "timing_note": "sub-frame appearances"}
    )
    merged = triage([bad, bad.model_copy(update={"label": "Street Mural"})])[0]
    assert merged.timing_reliable is False
    assert merged.timing_note
