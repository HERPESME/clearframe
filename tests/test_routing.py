"""The escalation ladder: resolve at the cheapest level that can actually answer."""

import pytest

from clearframe.knowledge import KnowledgeBase, load_knowledge
from clearframe.models import (
    ClearanceCategory,
    Corroboration,
    ElementType,
    IdentityVerdict,
    LicensingPosture,
    Prominence,
    TimeRange,
    TriagedElement,
)
from clearframe.routing import ResearchTier, route, route_all, summarise_routes

KB: KnowledgeBase = load_knowledge()


def el(
    label,
    category,
    *,
    eid="e1",
    screen_time_s=6.0,
    frame_coverage=0.2,
    centrality=0.5,
    plot_integral=False,
    description="",
):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    return TriagedElement(
        id=eid,
        label=label,
        element_type=types[category],
        description=description,
        time_ranges=[TimeRange(start_s=0.0, end_s=max(1.0, screen_time_s))],
        prominence=Prominence(
            screen_time_s=screen_time_s,
            frame_coverage=frame_coverage,
            centrality=centrality,
            plot_integral=plot_integral,
        ),
        category=category,
    )


# ------------------------------------------------------------ the knowledge
def test_knowledge_base_loads_all_four_datasets():
    assert len(KB.marks) >= 100
    assert len(KB.cases) >= 12
    assert len(KB.holders) >= 12
    assert KB.public_domain_through("published_work") == 1930
    assert KB.public_domain_through("sound_recording") == 1925


def test_mark_lookup_matches_aliases_and_noisy_labels():
    assert KB.find_mark("Coca-Cola can").owner == "The Coca-Cola Company"
    assert KB.find_mark("coke bottle on table").owner == "The Coca-Cola Company"
    assert KB.find_mark("Nike hoodie swoosh").owner == "Nike, Inc."
    assert KB.find_mark("Adidas three-stripe duffel bag").owner == "adidas AG"
    assert KB.find_mark("Zorblax Industries") is None


def test_posture_is_only_asserted_where_evidence_exists():
    """Ownership is a lookup; posture is live information. Asserting posture
    without a citation is exactly how a clearance report becomes confidently
    wrong, so the table must leave it unknown."""
    coke = KB.find_mark("Coca-Cola")
    assert coke.posture is LicensingPosture.UNKNOWN
    assert coke.posture_evidence == ""

    rings = KB.find_mark("Olympic rings")
    assert rings.posture is LicensingPosture.LITIGIOUS
    assert "36 U.S.C." in rings.posture_evidence


# ------------------------------------------------------------------ L0 LOCAL
def test_known_mark_with_cited_posture_resolves_locally():
    r = route(el("Olympic rings banner", ClearanceCategory.TRADEMARK), KB)
    assert r.tier is ResearchTier.LOCAL
    assert r.owner == "International Olympic Committee"
    assert r.posture is LicensingPosture.LITIGIOUS
    assert r.est_cost_usd == 0.0
    assert r.est_latency_s == 0.0


# ------------------------------------------------------------------ L3 SEARCH
def test_known_mark_without_posture_takes_the_owner_locally_and_searches_posture():
    """The whole latency win: never spend a five-minute Task run learning that
    Coca-Cola is owned by The Coca-Cola Company."""
    r = route(el("Coca-Cola can", ClearanceCategory.TRADEMARK), KB)
    assert r.tier is ResearchTier.SEARCH
    assert r.owner == "The Coca-Cola Company"
    assert r.est_cost_usd == pytest.approx(0.005)
    assert "posture" in r.rationale.lower()


def test_unknown_mark_still_earns_a_deep_run():
    r = route(el("Zorblax Industries storefront sign", ClearanceCategory.TRADEMARK), KB)
    assert r.tier is ResearchTier.DEEP
    assert r.owner is None


# ---------------------------------------------------------------- L1 STATUTE
def test_unnamed_person_routes_to_a_release_form_not_research():
    """No amount of web research produces a release. This was seven of the
    sixteen deep-research runs on the footage that motivated the ladder."""
    r = route(el("Background passerby face", ClearanceCategory.RIGHT_OF_PUBLICITY), KB)
    assert r.tier is ResearchTier.STATUTE
    assert r.est_cost_usd == 0.0
    assert "release" in r.disposition.lower()


def test_named_person_searches_for_the_agent():
    r = route(el("Serena Williams", ClearanceCategory.RIGHT_OF_PUBLICITY), KB)
    assert r.tier is ResearchTier.SEARCH


def test_the_productions_own_captions_are_not_a_clearance_item():
    r = route(el("Narrative text overlay", ClearanceCategory.TEXT_ON_SCREEN), KB)
    assert r.tier is ResearchTier.STATUTE
    assert "own" in r.rationale.lower()


def test_generic_ui_text_is_not_a_clearance_item():
    r = route(el("Battery indicator on phone UI", ClearanceCategory.TEXT_ON_SCREEN), KB)
    assert r.tier is ResearchTier.STATUTE


def test_brand_text_is_rerouted_as_a_trademark():
    r = route(el("Starbucks", ClearanceCategory.TEXT_ON_SCREEN), KB)
    assert r.tier is ResearchTier.SEARCH
    assert r.owner == "Starbucks Corporation"


def test_de_minimis_artwork_gets_a_cited_memo_not_a_task_run():
    r = route(
        el(
            "Framed photo on far wall",
            ClearanceCategory.COPYRIGHT_ART,
            screen_time_s=1.2,
            frame_coverage=0.01,
            centrality=0.1,
        ),
        KB,
    )
    assert r.tier is ResearchTier.STATUTE
    assert "Sandoval" in r.basis


def test_generic_location_needs_no_research():
    r = route(el("Generic city sidewalk", ClearanceCategory.LOCATION), KB)
    assert r.tier is ResearchTier.STATUTE


# ------------------------------------------------------------------- L4 DEEP
def test_unattributed_material_artwork_is_exactly_what_deep_research_is_for():
    r = route(el("Street mural (unknown artist)", ClearanceCategory.COPYRIGHT_ART), KB)
    assert r.tier is ResearchTier.DEEP
    assert r.enumerate_candidates is True
    assert "Falkner" in r.basis


def test_unfingerprinted_music_earns_a_deep_run():
    r = route(el("Upbeat electronic music", ClearanceCategory.MUSIC_SYNC), KB)
    assert r.tier is ResearchTier.DEEP


def test_fingerprinted_music_only_needs_posture_and_contact():
    corr = Corroboration(
        element_id="e1",
        verdict=IdentityVerdict.FINGERPRINTED,
        detector="audd-fingerprint",
        detected_label="Blinding Lights",
        confidence=1.0,
        note="",
    )
    r = route(
        el("Blinding Lights — The Weeknd", ClearanceCategory.MUSIC_SYNC),
        KB,
        corroboration=corr,
    )
    assert r.tier is ResearchTier.SEARCH
    assert r.est_latency_s < 10


# ------------------------------------------------------------------ blocking
def test_conflicted_identity_is_never_routed_anywhere():
    corr = Corroboration(
        element_id="e1",
        verdict=IdentityVerdict.CONFLICTED,
        detector="cloud-video-intelligence",
        detected_label="Kappa",
        confidence=0.8,
        note="",
    )
    r = route(el("Adidas duffel", ClearanceCategory.TRADEMARK), KB, corroboration=corr)
    assert r.tier is ResearchTier.BLOCKED
    assert r.est_cost_usd == 0.0


# ----------------------------------------------------------------- reporting
def test_routes_are_summarised_for_the_dossier():
    """The honesty guardrail: what the ladder resolved cheaply must appear as a
    counted, reasoned class — never as a silent skip."""
    elements = [
        el("Coca-Cola can", ClearanceCategory.TRADEMARK, eid="a"),
        el("Background passerby face", ClearanceCategory.RIGHT_OF_PUBLICITY, eid="b"),
        el("Audience member", ClearanceCategory.RIGHT_OF_PUBLICITY, eid="c"),
        el("Street mural (unknown artist)", ClearanceCategory.COPYRIGHT_ART, eid="d"),
    ]
    routes = route_all(elements, KB)
    summary = summarise_routes(routes)

    assert summary["counts"]["STATUTE"] == 2
    assert summary["counts"]["SEARCH"] == 1
    assert summary["counts"]["DEEP"] == 1
    assert summary["deep_runs"] == 1
    assert summary["est_cost_usd"] > 0
    assert len(summary["resolved_without_research"]) == 2


def test_the_measured_case_collapses_sixteen_deep_runs():
    """The observed failure: 16 Parallel Task runs on a 21.8s clip, 6 of which
    returned no owner. Same 16 elements, through the ladder."""
    observed = [
        *[el(f"Audience member {i}", ClearanceCategory.RIGHT_OF_PUBLICITY, eid=f"p{i}") for i in range(5)],
        *[el(f"Inset photo face {i}", ClearanceCategory.RIGHT_OF_PUBLICITY, eid=f"f{i}") for i in range(2)],
        el("Narrative text overlays", ClearanceCategory.TEXT_ON_SCREEN, eid="t1"),
        el("'Thank You' text block", ClearanceCategory.TEXT_ON_SCREEN, eid="t2"),
        el("Timestamp overlay", ClearanceCategory.TEXT_ON_SCREEN, eid="t3"),
        el("ALCOR signature", ClearanceCategory.TEXT_ON_SCREEN, eid="t4"),
        el("Presenter's jewelry", ClearanceCategory.COPYRIGHT_ART, eid="j1",
           screen_time_s=1.0, frame_coverage=0.01, centrality=0.1),
        el("Framed artwork behind desk", ClearanceCategory.COPYRIGHT_ART, eid="a1"),
        el("Coca-Cola can", ClearanceCategory.TRADEMARK, eid="m1"),
        el("Upbeat electronic music", ClearanceCategory.MUSIC_SYNC, eid="s1"),
        el("Generic office interior", ClearanceCategory.LOCATION, eid="l1"),
    ]
    assert len(observed) == 16
    summary = summarise_routes(route_all(observed, KB))
    assert summary["deep_runs"] <= 2, summary["counts"]
    assert summary["counts"]["STATUTE"] >= 9


# ------------------------------------------------------ materiality override
def test_a_materially_exposed_finding_still_earns_the_full_treatment():
    """Cheapest-that-can-answer is the right default, not the right rule for
    the two or three findings that will actually sink the delivery."""
    prominent = el(
        "Nike hoodie swoosh",
        ClearanceCategory.TRADEMARK,
        screen_time_s=9.0,
        frame_coverage=0.35,
        centrality=0.8,
        plot_integral=True,
    )
    r = route(prominent, KB)
    assert r.tier is ResearchTier.DEEP
    assert r.owner == "Nike, Inc."  # local lookup is still kept
    assert "provisional exposure" in r.rationale


def test_the_same_mark_glimpsed_briefly_stays_cheap():
    glimpsed = el(
        "Nike hoodie swoosh",
        ClearanceCategory.TRADEMARK,
        screen_time_s=2.5,
        frame_coverage=0.03,
        centrality=0.2,
    )
    assert route(glimpsed, KB).tier is ResearchTier.SEARCH


def test_escalation_can_be_switched_off_for_a_speed_run():
    prominent = el(
        "Nike hoodie swoosh",
        ClearanceCategory.TRADEMARK,
        screen_time_s=9.0,
        frame_coverage=0.35,
        centrality=0.8,
        plot_integral=True,
    )
    assert route(prominent, KB, escalate_material=False).tier is ResearchTier.SEARCH


def test_attributable_artwork_still_needs_a_deep_run():
    """A rung must be able to answer the question its category poses. For
    trademark, ownership is a local lookup and only posture is live. For
    artwork, ownership IS the question and no search resolves it."""
    r = route(el("Arctic Monkeys tour poster", ClearanceCategory.COPYRIGHT_ART), KB)
    assert r.tier is ResearchTier.DEEP
    assert r.enumerate_candidates is False  # attributable — no enumeration needed
    assert "Ringgold" in r.basis


# ------------------------------------------------------------ useful articles
@pytest.mark.parametrize(
    "label", ["Flower Vase", "Second Flower Vase", "Plain wooden chair", "Table lamp"]
)
def test_useful_articles_are_not_works_of_authorship(label):
    """Found on a live run: a 1950s Bayer spot produced 'Flower Vase' and
    'Second Flower Vase' as ARTWORK and both went to deep rights research."""
    r = route(el(label, ClearanceCategory.COPYRIGHT_ART), KB)
    assert r.tier is ResearchTier.STATUTE
    assert "17 U.S.C. §101" in r.basis


@pytest.mark.parametrize(
    "label",
    [
        "Landscape Painting",
        "Framed photograph on the wall",
        "Concert poster",
        "Bronze sculpture in the lobby",
        "Painted mural",
    ],
)
def test_authored_images_are_never_downgraded_as_useful_articles(label):
    """Ringgold v. BET turned on a poster hanging on a wall. Quietly
    downgrading authored images is the failure this product exists to prevent."""
    r = route(el(label, ClearanceCategory.COPYRIGHT_ART), KB)
    assert r.tier is ResearchTier.DEEP


def test_a_designer_piece_is_not_swept_up_by_the_utilitarian_rule():
    """'Eames lounge chair' names a design; only wholly generic labels qualify."""
    r = route(el("Eames lounge chair", ClearanceCategory.COPYRIGHT_ART), KB)
    assert r.tier is ResearchTier.DEEP
