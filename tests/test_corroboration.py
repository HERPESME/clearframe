from clearframe.corroboration import assess, blocks_research
from clearframe.integrations.vision_client import parse_logo_annotations
from clearframe.models import (
    ClearanceCategory,
    DetectorHit,
    ElementType,
    IdentityVerdict,
    Prominence,
    TimeRange,
    TriagedElement,
)
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context

DETECTOR = "cloud-video-intelligence"


def make_element(label="Nike hoodie swoosh", category=ClearanceCategory.TRADEMARK):
    return TriagedElement(
        id="e1",
        label=label,
        element_type=ElementType.LOGO,
        description="",
        time_ranges=[TimeRange(start_s=8, end_s=18)],
        prominence=Prominence(
            screen_time_s=10, frame_coverage=0.1, centrality=0.5, plot_integral=False
        ),
        category=category,
    )


def test_agreeing_detector_corroborates():
    hits = [DetectorHit(label="Nike", confidence=0.93, start_s=8, end_s=18)]
    result = assess(make_element(), hits, DETECTOR)
    assert result.verdict is IdentityVerdict.CORROBORATED
    assert result.detected_label == "Nike"
    assert result.confidence == 0.93


def test_disagreeing_detector_conflicts_and_blocks_research():
    hits = [DetectorHit(label="Kappa", confidence=0.71, start_s=8, end_s=18)]
    result = assess(make_element(), hits, DETECTOR)
    assert result.verdict is IdentityVerdict.CONFLICTED
    assert blocks_research(result) is True
    assert "Kappa" in result.note


def test_silent_detector_is_single_source_not_a_conflict():
    result = assess(make_element(), [], DETECTOR)
    assert result.verdict is IdentityVerdict.SINGLE_SOURCE
    assert blocks_research(result) is False


def test_low_confidence_hits_are_ignored():
    hits = [DetectorHit(label="Kappa", confidence=0.2, start_s=8, end_s=18)]
    assert assess(make_element(), hits, DETECTOR).verdict is IdentityVerdict.SINGLE_SOURCE


def test_non_overlapping_hit_does_not_conflict():
    hits = [DetectorHit(label="Kappa", confidence=0.9, start_s=40, end_s=45)]
    assert assess(make_element(), hits, DETECTOR).verdict is IdentityVerdict.SINGLE_SOURCE


def test_uncatalogued_categories_are_always_single_source():
    # A mural or a song is outside any brand catalogue; silence there must not
    # read as a contradiction.
    mural = make_element(label="Street mural", category=ClearanceCategory.COPYRIGHT_ART)
    hits = [DetectorHit(label="Nike", confidence=0.99, start_s=8, end_s=18)]
    result = assess(mural, hits, DETECTOR)
    assert result.verdict is IdentityVerdict.SINGLE_SOURCE


def test_parses_real_video_intelligence_shape():
    payload = {
        "annotation_results": [
            {
                "logo_recognition_annotations": [
                    {
                        "entity": {"description": "Coca-Cola"},
                        "tracks": [
                            {
                                "segment": {
                                    "start_time_offset": {"seconds": 5},
                                    "end_time_offset": {"seconds": 11, "nanos": 500000000},
                                },
                                "confidence": 0.88,
                                "timestamped_objects": [
                                    {
                                        "normalized_bounding_box": {
                                            "left": 0.4, "top": 0.5,
                                            "right": 0.55, "bottom": 0.79,
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    }
    hits = parse_logo_annotations(payload)
    assert len(hits) == 1
    assert hits[0].label == "Coca-Cola" and hits[0].start_s == 5.0
    assert hits[0].end_s == 11.5
    assert hits[0].bbox.xmin == 0.4


async def test_pipeline_corroborates_and_blocks_the_disputed_element(tmp_path):
    state = await Pipeline(build_demo_pipeline()).run(demo_context(tmp_path))
    verdicts = {k: v.verdict for k, v in state.corroboration.items()}
    assert verdicts["e2"] is IdentityVerdict.CORROBORATED  # Coca-Cola
    assert verdicts["e3"] is IdentityVerdict.CORROBORATED  # Nike
    assert verdicts["e8"] is IdentityVerdict.CONFLICTED  # Adidas vs Kappa
    # the disputed identity is never researched, and never enumerated either
    assert state.research["e8"].status == "incomplete"
    assert "e8" not in state.candidates


# ------------------------------------------ regression: the false conflict
def _bayer_element():
    return TriagedElement(
        id="e1",
        label="Bayer Aspirin",
        element_type=ElementType.LOGO,
        description="Bayer cross on the tin",
        time_ranges=[TimeRange(start_s=0.0, end_s=30.0)],
        prominence=Prominence(
            screen_time_s=9.0, frame_coverage=0.2, centrality=0.7, plot_integral=True
        ),
        category=ClearanceCategory.TRADEMARK,
    )


def test_a_legal_suffix_must_not_defeat_agreement():
    """From a live run on a 1950s Bayer spot. Video Intelligence returned
    'Bayer Corporation' three times at ~0.87, but {bayer, aspirin} against
    {bayer, corporation} scores 0.5 — under threshold — so correct agreement was
    rejected and one spurious hit made the identity CONFLICTED. Research was
    then blocked on the only confidently identified brand in the clip."""
    hits = [
        DetectorHit(label="Bayer Corporation", confidence=0.88),
        DetectorHit(label="Bayer Corporation", confidence=0.85),
        DetectorHit(label="Bayer Corporation", confidence=0.89),
        DetectorHit(label="Wake Forest Demon Deacons", confidence=0.94),
    ]
    result = assess(_bayer_element(), hits, "cloud-video-intelligence")

    assert result.verdict is IdentityVerdict.CORROBORATED
    assert result.detected_label == "Bayer Corporation"
    assert blocks_research(result) is False


def test_one_confident_false_positive_does_not_outvote_agreement():
    """A busy frame makes a closed-vocabulary detector emit several labels.
    Some of them disagreeing is normal; it is only a conflict when NONE agree."""
    hits = [
        DetectorHit(label="Bayer", confidence=0.6),
        DetectorHit(label="Something Else Entirely", confidence=0.99),
    ]
    assert (
        assess(_bayer_element(), hits, "d").verdict is IdentityVerdict.CORROBORATED
    )


def test_a_genuine_disagreement_is_still_a_conflict():
    """The guardrail this fix must not weaken."""
    hits = [DetectorHit(label="Kappa", confidence=0.8)]
    result = assess(_bayer_element(), hits, "d")
    assert result.verdict is IdentityVerdict.CONFLICTED
    assert blocks_research(result) is True
