"""What the PLATFORM does — which is not what a court would do.

2.5 billion Content ID claims in 2025, 99%+ automated, 90%+ resolved by
diverting revenue rather than removing the video. The system does not consider
fair use. So a creator's exposure is governed by *detectability*, not by legal
merit, and those two diverge sharply: a background mural has real legal weight
against you and almost no chance of being caught, while a twelve-second music
bed has an excellent fair-use argument and is caught essentially every time.
"""

import pytest

from clearframe.models import (
    AudioMatch,
    AudioProvenance,
    ClearanceCategory,
    DetectionMethod,
    ElementType,
    PlatformAction,
    Prominence,
    TimeRange,
    TriagedElement,
)
from clearframe.platform import (
    detectability,
    load_platforms,
    project_outcome,
    project_all,
)

PLATFORMS = load_platforms()


def el(category, label="x", eid="e1", start=12.0, end=24.0):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    return TriagedElement(
        id=eid, label=label, element_type=types[category], description="",
        time_ranges=[TimeRange(start_s=start, end_s=end)],
        prominence=Prominence(screen_time_s=end - start, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
        category=category,
    )


def match(verified=True):
    return AudioMatch(
        title="Blinding Lights", artist="The Weeknd", label="Republic Records",
        at_s=12.0, confidence=1.0,
        provenance=AudioProvenance.VERIFIED if verified else AudioProvenance.UNVERIFIED,
        catalogues=["spotify", "apple_music"] if verified else [],
    )


# ----------------------------------------------------------------- the data
def test_platform_policies_load():
    assert {"youtube", "tiktok", "instagram"} <= set(PLATFORMS)
    yt = PLATFORMS["youtube"]
    assert yt.strikes_to_termination == 3
    assert yt.audio_matching is True
    assert yt.considers_fair_use is False


# ------------------------------------------------------- music: the real risk
def test_a_fingerprinted_track_is_a_near_certain_claim():
    o = project_outcome(el(ClearanceCategory.MUSIC_SYNC, "Blinding Lights — The Weeknd"),
                        PLATFORMS["youtube"], audio=match())
    assert o.action is PlatformAction.CLAIM_LIKELY
    assert o.confidence == "near-certain"
    assert o.detected_by is DetectionMethod.AUDIO_FINGERPRINT


def test_the_remedy_carries_the_timecode_a_creator_can_act_on():
    o = project_outcome(el(ClearanceCategory.MUSIC_SYNC), PLATFORMS["youtube"],
                        audio=match())
    assert "00:12" in o.remedy and "00:24" in o.remedy


def test_the_revenue_consequence_names_who_gets_paid():
    o = project_outcome(el(ClearanceCategory.MUSIC_SYNC), PLATFORMS["youtube"],
                        audio=match())
    assert "Republic Records" in o.revenue_impact


def test_an_unidentified_track_is_only_possible_not_certain():
    o = project_outcome(el(ClearanceCategory.MUSIC_SYNC, "Instrumental score"),
                        PLATFORMS["youtube"], audio=None)
    assert o.action is PlatformAction.CLAIM_POSSIBLE
    assert o.confidence != "near-certain"


def test_a_platform_without_audio_matching_does_not_claim():
    quiet = PLATFORMS["youtube"].model_copy(update={"audio_matching": False,
                                                    "name": "SomeSite"})
    o = project_outcome(el(ClearanceCategory.MUSIC_SYNC), quiet, audio=match())
    assert o.action is not PlatformAction.CLAIM_LIKELY


# ----------------------------------------------- everything else is manual
@pytest.mark.parametrize(
    "category",
    [ClearanceCategory.TRADEMARK, ClearanceCategory.COPYRIGHT_ART,
     ClearanceCategory.LOCATION],
)
def test_visual_findings_need_a_human_to_notice_them(category):
    """No platform runs automated logo or artwork matching over uploads. These
    only bite when a person files a complaint — which is why they are far less
    likely and far more severe when they land."""
    o = project_outcome(el(category), PLATFORMS["youtube"])
    assert o.action is PlatformAction.MANUAL_COMPLAINT
    assert o.detected_by is DetectionMethod.HUMAN_REPORT


def test_a_person_routes_to_the_privacy_process_not_copyright():
    o = project_outcome(el(ClearanceCategory.RIGHT_OF_PUBLICITY, "Background face"),
                        PLATFORMS["youtube"])
    assert o.action is PlatformAction.PRIVACY_COMPLAINT
    assert "privacy" in o.remedy.lower() or "blur" in o.remedy.lower()


# ---------------------------------------------------------- detectability
def test_detectability_inverts_legal_merit():
    """The insight the whole module exists for."""
    music = project_outcome(el(ClearanceCategory.MUSIC_SYNC), PLATFORMS["youtube"],
                            audio=match())
    mural = project_outcome(el(ClearanceCategory.COPYRIGHT_ART, "Street mural"),
                            PLATFORMS["youtube"])
    assert detectability(music) > detectability(mural)


def test_detectability_is_bounded():
    for category in ClearanceCategory:
        o = project_outcome(el(category), PLATFORMS["youtube"], audio=match())
        assert 0 <= detectability(o) <= 100


def test_fair_use_is_reported_as_no_defence_against_automation():
    """The honesty the product exists for: a perfect legal argument does not
    stop an automated claim."""
    o = project_outcome(el(ClearanceCategory.MUSIC_SYNC), PLATFORMS["youtube"],
                        audio=match())
    assert "fair use" in o.consequence.lower()


# ------------------------------------------------------------------- batch
def test_project_all_covers_every_element_and_sorts_by_detectability():
    elements = [
        el(ClearanceCategory.COPYRIGHT_ART, "Street mural", "a"),
        el(ClearanceCategory.MUSIC_SYNC, "Blinding Lights", "b"),
        el(ClearanceCategory.TEXT_ON_SCREEN, "Narrative overlay", "c"),
    ]
    outcomes = project_all(elements, PLATFORMS["youtube"], [match()])
    assert len(outcomes) == 3
    scores = [detectability(o) for o in outcomes]
    assert scores == sorted(scores, reverse=True)
    assert outcomes[0].element_id == "b"


def test_an_unknown_platform_name_falls_back_rather_than_raising():
    from clearframe.platform import platform_for

    assert platform_for("nosuchplatform", PLATFORMS).name == PLATFORMS["youtube"].name
