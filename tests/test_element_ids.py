"""Two Gemini passes both number their findings from 1.

The auditor is a SECOND scan whose whole purpose is to catch what the first
pass missed, and it numbers its own detections from scratch. Every downstream
dict — routes, research, risk, coverage, remediation — is keyed by element id,
so the moment the auditor finds something new, two unrelated findings share a
key and one silently overwrites the other's analysis.

Found on a real clip of The Hangover Part II: eight findings collapsed to six
routes. "Stu's Face Tattoo" and a "National" car-rental logo were both id "1",
and the tattoo — the single most consequential finding in that footage, and a
real lawsuit — was displaying the car-rental company's route and ownership.

Silently is the operative word. Nothing raised, nothing logged, and the counts
in the UI still looked plausible.
"""

from clearframe.models import DetectedElement, ElementType, Prominence, TimeRange
from clearframe.stages.scan import merge_passes
from clearframe.triage import triage


def det(eid: str, label: str, kind: ElementType = ElementType.LOGO) -> DetectedElement:
    return DetectedElement(
        id=eid,
        label=label,
        element_type=kind,
        description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=4.0)],
        prominence=Prominence(
            screen_time_s=3.0, frame_coverage=0.2, centrality=0.5, plot_integral=False
        ),
    )


def test_the_auditor_reusing_an_id_does_not_erase_a_finding():
    """The Hangover fact pattern, exactly."""
    scan = [det("1", "Stu's Face Tattoo", ElementType.TATTOO), det("2", "Aviator Sunglasses")]
    audit = [det("1", "National"), det("2", "Phil's Ring")]

    merged = merge_passes(scan, audit)

    assert len(merged) == 4
    assert len({d.id for d in merged}) == 4, [d.id for d in merged]
    # The first pass keeps its ids; a stored state or a UI deep-link into an
    # existing run must not shift under it.
    by_label = {d.label: d.id for d in merged}
    assert by_label["Stu's Face Tattoo"] == "1"
    assert by_label["Aviator Sunglasses"] == "2"


def test_the_same_finding_seen_twice_still_merges():
    """Renaming must not defeat the dedupe it sits in front of."""
    scan = [det("1", "Pizza Hut")]
    audit = [det("1", "Pizza Hut")]

    elements = triage(merge_passes(scan, audit))

    assert len(elements) == 1
    assert elements[0].id == "1"
    # Merged, not dropped: both sightings are in the total.
    assert elements[0].prominence.screen_time_s == 6.0


def test_ids_are_unique_even_within_one_pass():
    """A single call can repeat an id too; the guarantee is unconditional."""
    scan = [det("1", "Alpha"), det("1", "Beta")]

    merged = merge_passes(scan, [])

    assert len({d.id for d in merged}) == 2


def test_untouched_when_nothing_collides():
    """The demo fixture numbers its audit pass e7, and must not shift."""
    scan = [det("e1", "Alpha"), det("e2", "Beta")]
    audit = [det("e7", "Gamma")]

    merged = merge_passes(scan, audit)

    assert [d.id for d in merged] == ["e1", "e2", "e7"]
