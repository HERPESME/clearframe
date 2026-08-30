"""Commercial speech has no expressive-work shield — and risk must know it.

Every brand-owner WIN in the litigation record is an advertisement (Falkner v.
GM, Mercedes v. the Detroit muralists, Revok v. H&M). Every brand-owner LOSS is
an expressive work (Wham-O v. Paramount, Caterpillar v. Disney, Louis Vuitton v.
Warner Bros.). Rogers v. Grimaldi protects films; it does not protect ads.

Before this, a mural in a Cadillac campaign scored identically to the same mural
in a feature — the single largest legal difference in the whole analysis was
invisible to the risk engine.
"""

import pytest

from clearframe.knowledge import load_knowledge
from clearframe.models import (
    ClearanceCategory,
    ElementType,
    LicensingPosture,
    Prominence,
    Production,
    ResearchResult,
    TimeRange,
    TriagedElement,
    UseContext,
)
from clearframe.routing import ResearchTier, route
from clearframe.scoring import provisional_score, score_element

KB = load_knowledge()


def el(category=ClearanceCategory.TRADEMARK, label="Coca-Cola can", **kw):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    base = dict(
        id="e1",
        label=label,
        element_type=types[category],
        description="",
        time_ranges=[TimeRange(start_s=0.0, end_s=8.0)],
        prominence=Prominence(
            screen_time_s=8.0, frame_coverage=0.25, centrality=0.6, plot_integral=False
        ),
        category=category,
    )
    base.update(kw)
    return TriagedElement(**base)


def research(posture=LicensingPosture.STANDARD):
    return ResearchResult(
        element_id="e1", owner="The Coca-Cola Company", owner_confidence="high",
        licensing_contact=None, licensing_posture=posture, litigation_history=[],
        estimated_license_cost_band=None, basis=[], status="complete",
    )


# ------------------------------------------------------- backward compatibility
def test_the_default_is_expressive_so_nothing_existing_moves():
    """The guarantee: an existing production's score is byte-identical."""
    p = Production(id="p", title="T", footage_uri="x", duration_s=60.0)
    assert p.use_context is UseContext.EXPRESSIVE

    baseline = score_element(el(), research())
    explicit = score_element(el(), research(), use_context=UseContext.EXPRESSIVE)
    assert baseline.score == explicit.score
    assert baseline.factors == explicit.factors


def test_the_factor_is_recorded_so_old_scores_stay_derivable():
    """CLAUDE.md's rule: risk must be reproducible from stored inputs."""
    r = score_element(el(), research(), use_context=UseContext.ADVERTISING)
    assert r.factors["use_context_factor"] == pytest.approx(1.4)


# --------------------------------------------------------------- the ordering
@pytest.mark.parametrize(
    "context,direction",
    [
        (UseContext.NEWS, "lower"),
        (UseContext.EDUCATIONAL, "lower"),
        (UseContext.EXPRESSIVE, "same"),
        (UseContext.SPONSORED, "higher"),
        (UseContext.ADVERTISING, "higher"),
    ],
)
def test_commercial_use_scores_higher_and_news_scores_lower(context, direction):
    base = score_element(el(), research(), use_context=UseContext.EXPRESSIVE).score
    got = score_element(el(), research(), use_context=context).score
    if direction == "higher":
        assert got > base
    elif direction == "lower":
        assert got < base
    else:
        assert got == base


def test_music_is_exempt_because_the_use_context_changes_nothing():
    """A sync licence and a master licence are required for a news report, a
    feature and an advert alike. There is no expressive-use defence to run."""
    song = el(ClearanceCategory.MUSIC_SYNC, "Blinding Lights — The Weeknd")
    scores = {
        c: score_element(song, research(), use_context=c).score for c in UseContext
    }
    assert len(set(scores.values())) == 1, scores


def test_a_score_cannot_exceed_one_hundred():
    loud = el(
        prominence=Prominence(
            screen_time_s=60.0, frame_coverage=1.0, centrality=1.0, plot_integral=True
        )
    )
    r = score_element(loud, research(LicensingPosture.LITIGIOUS),
                      use_context=UseContext.ADVERTISING)
    assert r.score <= 100


def test_provisional_score_honours_the_context_too():
    """Otherwise the preliminary report would under-warn exactly the users who
    need warning most, and the band could RISE once research landed."""
    base = provisional_score(el())
    ad = provisional_score(el(), use_context=UseContext.ADVERTISING)
    assert ad > base
    assert ad >= score_element(el(), research(), use_context=UseContext.ADVERTISING).score


# ------------------------------------------------------------------- routing
def test_a_mark_in_an_advert_needs_permission_not_just_posture():
    """In an expressive work you need to know whether the holder is litigious.
    In an advert you need an actual licence — so you need the contact and the
    cost band, which only a deep run produces."""
    expressive = route(el(), KB, use_context=UseContext.EXPRESSIVE)
    advert = route(el(), KB, use_context=UseContext.ADVERTISING)

    assert expressive.tier is ResearchTier.SEARCH
    assert advert.tier is ResearchTier.DEEP
    assert advert.owner == "The Coca-Cola Company"  # local lookup still kept
    assert "advert" in advert.rationale.lower() or "commercial" in advert.rationale.lower()


def test_an_unnamed_person_in_an_advert_still_needs_a_release_not_research():
    """Research still cannot produce a release. But the disposition hardens:
    commercial appropriation of a likeness is the clearest right-of-publicity
    tort there is, so 'advisable' becomes 'mandatory'."""
    face = el(ClearanceCategory.RIGHT_OF_PUBLICITY, "Background passerby face")
    r = route(face, KB, use_context=UseContext.ADVERTISING)
    assert r.tier is ResearchTier.STATUTE
    assert "release" in r.disposition.lower()
    assert r.disposition != route(face, KB, use_context=UseContext.EXPRESSIVE).disposition


def test_news_context_does_not_escalate():
    assert route(el(), KB, use_context=UseContext.NEWS).tier is ResearchTier.SEARCH


def test_free_rungs_stay_free_in_every_context():
    """Commercial use does not turn a caption we wrote ourselves into a
    clearance item."""
    own = el(ClearanceCategory.TEXT_ON_SCREEN, "Narrative text overlay")
    for context in UseContext:
        assert route(own, KB, use_context=context).tier is ResearchTier.STATUTE
