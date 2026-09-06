"""Everything the extra passes found, not just the first one's share.

`gather_detections` merged the DETECTIONS of every pass and then returned
`results[0]` as "the result", and the stage read the document-level fields off
that one object. So a second pass — added specifically because one pass sees
about 60% of what is there — contributed its findings and had everything else
it saw thrown away:

  exposures        the minors, addresses, documents and screens. This is the
                   one finding class with no second detector anywhere in the
                   system: no catalogue, no fingerprint, no corroborator. Half
                   the passes were being discarded on the category the product
                   markets as the one nobody else looks for.
  source_work      if only the second pass recognised the footage, the medium
                   never reached `corrected_types`, so drawn characters kept
                   being routed as real people needing releases.
  unscanned_ranges the honesty column saying what could not be analysed.

Folding them needs dedupe, because two passes describing the same child are
one child. It is deliberately conservative in the same direction as triage,
for the opposite reason: over-merging two exposures could collapse two
different children into one warning.
"""

from clearframe.integrations.gemini_client import ScanResult
from clearframe.models import (
    ExposureFinding,
    ExposureKind,
    SourceWork,
    TimeRange,
)
from clearframe.stages.scan import best_source_work, dedupe_exposures, fold_unscanned


def exposure(eid, kind, description, ranges):
    return ExposureFinding(
        id=eid, kind=kind, description=description,
        time_ranges=[TimeRange(start_s=a, end_s=b) for a, b in ranges],
    )


def work(title, confidence, medium="drawn"):
    return SourceWork(title=title, confidence=confidence, medium=medium)


# --- exposures ---------------------------------------------------------------


def test_the_same_child_seen_by_both_passes_is_one_finding():
    out = dedupe_exposures([
        exposure("1", ExposureKind.MINOR, "A child in the background", [(2.0, 6.0)]),
        exposure("1", ExposureKind.MINOR, "A child in the background", [(2.5, 7.0)]),
    ])
    assert len(out) == 1
    assert [(r.start_s, r.end_s) for r in out[0].time_ranges] == [(2.0, 7.0)]


def test_a_second_child_in_another_shot_stays_a_second_finding():
    """The failure that matters here is under-reporting, not duplication."""
    out = dedupe_exposures([
        exposure("1", ExposureKind.MINOR, "A child in the background", [(2.0, 6.0)]),
        exposure("2", ExposureKind.MINOR, "A child in the background", [(30.0, 34.0)]),
    ])
    assert len(out) == 2


def test_two_kinds_of_exposure_are_never_merged():
    """Same moment, same words, different obligation."""
    out = dedupe_exposures([
        exposure("1", ExposureKind.MINOR, "Visible on the table", [(2.0, 6.0)]),
        exposure("2", ExposureKind.DOCUMENT, "Visible on the table", [(2.0, 6.0)]),
    ])
    assert len(out) == 2


def test_the_fuller_description_survives_a_merge():
    out = dedupe_exposures([
        exposure("1", ExposureKind.PERSONAL_DATA, "An address", [(2.0, 6.0)]),
        exposure("2", ExposureKind.PERSONAL_DATA,
                 "An address label, readable, on the parcel", [(2.0, 6.0)]),
    ])
    assert len(out) == 1
    assert out[0].description.startswith("An address label")


def test_exposures_from_different_passes_never_share_an_id():
    """Both passes number their exposures from 1, exactly like detections."""
    out = dedupe_exposures([
        exposure("1", ExposureKind.MINOR, "A child", [(2.0, 6.0)]),
        exposure("1", ExposureKind.VEHICLE_PLATE, "A plate", [(30.0, 34.0)]),
    ])
    assert len({e.id for e in out}) == 2


# --- unscanned ranges --------------------------------------------------------


def test_the_same_unscanned_window_is_reported_once():
    out = fold_unscanned(
        [ScanResult(detections=[], unscanned_ranges=[TimeRange(start_s=0.0, end_s=5.0)]),
         ScanResult(detections=[], unscanned_ranges=[TimeRange(start_s=0.0, end_s=5.0)])],
        ScanResult(detections=[], unscanned_ranges=[TimeRange(start_s=4.0, end_s=9.0)]),
    )
    assert [(r.start_s, r.end_s) for r in out] == [(0.0, 9.0)]


# --- source work -------------------------------------------------------------


def test_the_most_confident_identification_wins():
    """Not the first pass's. Confidence is what gates subsumption.

    `sourcework` only subsumes on high or medium, so a low-confidence guess
    from pass one shadowing a high-confidence identification from pass two
    would silently disable the whole mechanism.
    """
    best = best_source_work([work("Maybe This", "low"), work("Code Geass", "high")])
    assert best.title == "Code Geass"


def test_an_earlier_pass_wins_a_tie():
    best = best_source_work([work("First", "high"), work("Second", "high")])
    assert best.title == "First"


def test_nothing_identified_is_still_nothing():
    assert best_source_work([None, None]) is None


# --- the auditor must be told what the scan is told ---------------------------


def test_the_audit_prompt_still_asks_only_for_misses():
    """The property that makes it a recall pass rather than a third scan."""
    from clearframe.integrations.gemini_client import AUDIT_PROMPT_TEMPLATE

    assert "MISSED" in AUDIT_PROMPT_TEMPLATE
    assert "Do not repeat elements already found" in AUDIT_PROMPT_TEMPLATE


def test_the_audit_prompt_names_the_fields_the_stage_reads_from_it():
    """"Use the same JSON format" was carrying all of this on its own.

    The schema makes every one of these optional, and the stage consumes them
    from the audit result — so the findings unique to this pass arrived with
    no siting and no depiction, disabling freedom of panorama and the
    adverse-depiction escalation for exactly the findings it exists to catch.
    """
    from clearframe.integrations.gemini_client import AUDIT_PROMPT_TEMPLATE

    for field in ("bbox", "siting", "depiction", "exposures",
                  "unscanned_ranges", "source_work"):
        assert field in AUDIT_PROMPT_TEMPLATE, field
