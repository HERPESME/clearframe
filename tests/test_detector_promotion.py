"""A catalogued logo nobody reported is a finding, not a discarded hit.

Cloud Video Intelligence reads a closed vocabulary of ~100k brands. That makes
it the one detector in this system that structurally CANNOT hallucinate: it can
only name something in its catalogue, where the video model can name anything
it likes. It was wired as corroboration only — `assess` iterates ELEMENTS and
looks for hits that match them — so a hit matching no element was dropped
without a trace. No finding, no event, no line in the dossier.

But a high-confidence hit that matches nothing is exactly the interesting case:
a mark every Gemini pass missed, from a source that cannot invent one, already
fetched and already paid for. With recall measured at ~60% per pass, that is
free recall being thrown away.

The line to hold is which hits are LEFTOVER. A hit that took part in an
element's verdict is spoken for — including when it CONFLICTED, which is the
demo's Kappa reading of the Adidas duffel. Promoting a conflicting hit would
mint a second finding for one object and then let it corroborate itself.
"""

from clearframe.corroboration import (
    PROMOTE_MIN_CONFIDENCE,
    leftover_hits,
    promote_hits,
)
from clearframe.models import (
    BBox, ClearanceCategory, DetectedElement, DetectorHit, ElementType, Prominence,
    TimeRange,
)


def hit(label, confidence=0.9, start=5.0, end=9.0, boxed=True):
    return DetectorHit(
        label=label, confidence=confidence, start_s=start, end_s=end,
        bbox=BBox(ymin=0.4, xmin=0.4, ymax=0.5, xmax=0.5) if boxed else None,
    )


def det(label, element_type=ElementType.LOGO, start=5.0, end=9.0, where=0.1):
    """A finding. `where` places its box, so "same object" can be tested."""
    return DetectedElement(
        id="1", label=label, element_type=element_type, description="",
        time_ranges=[TimeRange(
            start_s=start, end_s=end,
            bbox=None if where is None else BBox(
                ymin=where, xmin=where, ymax=where + 0.1, xmax=where + 0.1),
        )],
        prominence=Prominence(screen_time_s=end - start, frame_coverage=0.1,
                              centrality=0.5, plot_integral=False),
    )


# --- which hits are actually leftover ----------------------------------------


def test_a_hit_nobody_reported_is_leftover():
    """A second brand elsewhere in the frame, which is an ordinary shot.

    Time cannot separate these — two brands share a shot constantly — so if an
    overlapping window were enough to call a hit "spoken for", the catalogue
    could never contribute anything in a shot where the scan already found
    something. Which is most shots.
    """
    nike = det("Nike", where=0.1)
    coke = hit("Coca-Cola")  # sits at 0.4, a different part of the frame
    assert [h.label for h in leftover_hits([nike], [coke])] == ["Coca-Cola"]


def test_a_hit_that_agrees_with_a_finding_is_not_leftover():
    assert leftover_hits([det("Nike hoodie swoosh")], [hit("Nike")]) == []


def test_a_hit_that_CONFLICTS_with_a_finding_is_not_leftover():
    """The demo's Kappa-vs-Adidas case, and the one that matters most.

    That hit is already doing work: it makes the duffel's identity CONFLICTED
    and blocks research on it. Promoting it as well would put a second finding
    on screen for one bag, and then let it corroborate itself from the very
    hit that disputed the first.
    """
    duffel = det("Adidas duffel bag", start=26.0, end=30.0, where=0.4)
    kappa = hit("Kappa", confidence=0.71, start=26.0, end=30.0)  # the same bag
    assert leftover_hits([duffel], [kappa]) == []


def test_a_hit_in_a_different_shot_is_leftover_even_with_the_same_label():
    """Consumed means "spoke to this finding", which is a claim about a window."""
    out = leftover_hits(
        [det("Nike", start=2.0, end=4.0)], [hit("Nike", start=30.0, end=34.0)]
    )
    assert [h.label for h in out] == ["Nike"]


def test_an_unplaceable_disagreement_is_treated_as_one_object():
    """Conservative on purpose, and the opposite bias to triage's.

    A wrongly promoted hit is not merely a duplicate: `corroborate` would then
    mark it CORROBORATED from the very hit that created it, so it would read as
    independently confirmed. Without boxes there is no evidence of a second
    object, and inventing one is the more expensive mistake.
    """
    unplaced = det("Adidas duffel bag", where=None)
    assert leftover_hits([unplaced], [hit("Kappa", confidence=0.71)]) == []


def test_only_LOGO_and_TEXT_findings_can_consume_a_hit():
    """Mirrors CORROBORATABLE: a mural or a tattoo is outside any catalogue."""
    mural = det("Nike", element_type=ElementType.ARTWORK, where=0.4)
    assert [h.label for h in leftover_hits([mural], [hit("Nike")])] == ["Nike"]


# --- what promotion produces --------------------------------------------------


def test_a_leftover_hit_becomes_a_finding_that_says_where_it_came_from():
    promoted = promote_hits([hit("Coca-Cola")], "Cloud Video Intelligence")

    assert len(promoted) == 1
    el = promoted[0]
    assert el.label == "Coca-Cola"
    assert el.element_type is ElementType.LOGO
    assert [(r.start_s, r.end_s) for r in el.time_ranges] == [(5.0, 9.0)]
    assert el.time_ranges[0].bbox is not None
    assert "Cloud Video Intelligence" in el.description
    assert "not reported by the" in el.description.lower()
    assert el.prominence.screen_time_s == 4.0


def test_several_sightings_of_one_mark_are_one_finding():
    promoted = promote_hits(
        [hit("Coca-Cola", start=5.0, end=9.0), hit("Coca-Cola", start=20.0, end=22.0)],
        "Cloud Video Intelligence",
    )
    assert len(promoted) == 1
    assert len(promoted[0].time_ranges) == 2
    assert promoted[0].prominence.screen_time_s == 6.0


def test_promotion_needs_more_confidence_than_corroboration_does():
    """Minting a finding from one detector is a stronger claim than seconding one.

    Every true hit observed so far clears 0.7 — the fixtures at 0.71/0.88/0.93
    and the live Bayer read at ~0.87 — while the one documented spurious class
    sat above corroboration's 0.5 floor. Re-check against new footage.
    """
    assert PROMOTE_MIN_CONFIDENCE > 0.5
    assert promote_hits([hit("Coca-Cola", confidence=0.6)], "VI") == []


def test_an_untimed_hit_is_never_promoted():
    """No window means no appearance to draw, and `_overlaps` treats it as
    in-scope against everything anyway — so it can never be leftover honestly."""
    assert promote_hits([hit("Coca-Cola", start=None, end=None)], "VI") == []


def test_a_point_segment_still_makes_a_usable_appearance():
    promoted = promote_hits([hit("Coca-Cola", start=5.0, end=5.0)], "VI")
    assert promoted[0].time_ranges[0].end_s > promoted[0].time_ranges[0].start_s


def test_promoted_ids_do_not_collide_with_the_scan_s():
    """They go through merge_passes, which renames only LATER collisions."""
    from clearframe.stages.scan import merge_passes

    scanned = [det("Nike")]
    promoted = promote_hits([hit("Coca-Cola")], "VI")
    merged = merge_passes(scanned, promoted)

    assert len({d.id for d in merged}) == len(merged) == 2


def test_the_demo_fixture_promotes_nothing():
    """Every fixture hit is consumed by the element it was recorded for.

    Stated as a test because a change here would silently alter the demo's
    finding count, which four other test modules pin.
    """
    import asyncio
    from pathlib import Path

    from clearframe.integrations.gemini_client import FixtureGeminiClient
    from clearframe.integrations.vision_client import FixtureVisionClient

    fixtures = Path("src/clearframe/integrations/fixtures")
    hits = asyncio.run(FixtureVisionClient(fixtures).detect("demo.mp4", 30.0))
    scan = asyncio.run(FixtureGeminiClient(fixtures).scan("demo.mp4", 30.0))

    assert hits, "the fixture should have detector hits to reason about"
    assert leftover_hits(scan.detections, hits) == []


# --- through the real stage ---------------------------------------------------


def test_a_missed_mark_becomes_a_routed_finding(tmp_path):
    """End to end: catalogue sees it, no scan pass does, it reaches the report.

    This is the whole point. Recall is measured at ~60% per pass, so a mark all
    three passes miss is the common case, not the exotic one — and here the
    second detector already had it.
    """
    import asyncio

    from clearframe.integrations.gemini_client import ScanResult
    from clearframe.pipeline import PipelineContext
    from clearframe.models import Production, ProductionState
    from clearframe.stages.scan import ScanStage

    class Gemini:
        async def scan(self, uri, duration_s, context=""):
            return ScanResult(detections=[det("Nike", where=0.1)], unscanned_ranges=[])

        async def audit_scan(self, uri, duration_s, found_labels, context=""):
            return ScanResult(detections=[], unscanned_ranges=[])

    class Catalogue:
        async def detect(self, uri, duration_s):
            return [hit("Coca-Cola", confidence=0.93)]

    production = Production(
        id="p1", title="t", footage_uri="clip.mp4", duration_s=41.5, fps=24.0
    )
    ctx = PipelineContext(
        state=ProductionState(production=production),
        gemini=Gemini(),
        parallel=None,
        store=None,
        corroborator=Catalogue(),
        audio=None,
    )
    asyncio.run(ScanStage().run(ctx))

    labels = [d.label for d in ctx.state.detections]
    assert "Coca-Cola" in labels, "the catalogue's mark never reached the findings"
    promoted = next(d for d in ctx.state.detections if d.label == "Coca-Cola")
    assert promoted.element_type is ElementType.LOGO
    assert "Cloud Video Intelligence" in promoted.description
    assert len({d.id for d in ctx.state.detections}) == len(ctx.state.detections)
