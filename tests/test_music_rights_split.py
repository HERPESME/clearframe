"""The two-licence problem: a song needs the composition AND the recording.

The single most common music clearance failure in the industry, and the one
the ledger could not previously represent — `scope` was free text.
"""

import pytest

from clearframe.licensing import assess, parse_licence_csv, parse_licence_json
from clearframe.models import (
    ClearanceCategory,
    CoverageStatus,
    ElementType,
    LicenceGrant,
    LicensingPosture,
    Prominence,
    ResearchResult,
    RightsType,
    TimeRange,
    TriagedElement,
)

OWNER = (
    "The Weeknd XO, Inc. / Universal Music Group (master); "
    "Universal Music Publishing Group (composition)"
)


def _song():
    return TriagedElement(
        id="e1",
        label="Blinding Lights — The Weeknd",
        element_type=ElementType.MUSIC,
        description="",
        time_ranges=[TimeRange(start_s=0.0, end_s=12.0)],
        prominence=Prominence(
            screen_time_s=12.0, frame_coverage=0.0, centrality=0.0, plot_integral=True
        ),
        category=ClearanceCategory.MUSIC_SYNC,
    )


def _research(owner=OWNER):
    return ResearchResult(
        element_id="e1",
        owner=owner,
        owner_confidence="high",
        licensing_contact=None,
        licensing_posture=LicensingPosture.LITIGIOUS,
        litigation_history=[],
        estimated_license_cost_band=None,
        basis=[],
        status="complete",
    )


def _lic(lid, holder, rights_type, **kw):
    return LicenceGrant(id=lid, rights_holder=holder, rights_type=rights_type, **kw)


def _assess(licences):
    return assess(
        _song(), _research(), licences, ["US"], ["THEATRICAL"], as_of="2026-08-22"
    )


def test_sync_licence_alone_leaves_the_master_uncleared():
    """A sync licence from the publisher covers the composition only. Shipping
    on it means shipping an uncleared recording."""
    cov = _assess([_lic("LIC-1", "Universal Music Publishing Group", RightsType.SYNC)])
    assert cov.status is CoverageStatus.PARTIAL
    assert any("master" in g.lower() for g in cov.gaps)


def test_master_licence_alone_leaves_the_composition_uncleared():
    cov = _assess([_lic("LIC-2", "Universal Music Group", RightsType.MASTER)])
    assert cov.status is CoverageStatus.PARTIAL
    assert any("composition" in g.lower() or "sync" in g.lower() for g in cov.gaps)


def test_both_halves_from_two_holders_clears_the_song():
    cov = _assess(
        [
            _lic("LIC-1", "Universal Music Publishing Group", RightsType.SYNC),
            _lic("LIC-2", "Universal Music Group", RightsType.MASTER),
        ]
    )
    assert cov.status is CoverageStatus.COVERED
    assert cov.gaps == []


def test_a_single_grant_of_both_halves_clears_the_song():
    cov = _assess([_lic("LIC-3", "Universal Music Group", RightsType.BOTH)])
    assert cov.status is CoverageStatus.COVERED


def test_territory_gap_on_one_half_still_blocks_the_song():
    """Holding both halves is not enough if one of them stops at the border."""
    cov = assess(
        _song(),
        _research(),
        [
            _lic("LIC-1", "Universal Music Publishing Group", RightsType.SYNC,
                 territories=["US"]),
            _lic("LIC-2", "Universal Music Group", RightsType.MASTER),
        ],
        ["US", "FR"],
        ["THEATRICAL"],
        as_of="2026-08-22",
    )
    assert cov.status is CoverageStatus.PARTIAL
    assert any("FR" in g for g in cov.gaps)


def test_an_expired_half_blocks_the_song():
    cov = _assess(
        [
            _lic("LIC-1", "Universal Music Publishing Group", RightsType.SYNC,
                 expires="2025-12-31"),
            _lic("LIC-2", "Universal Music Group", RightsType.MASTER),
        ]
    )
    assert cov.status is CoverageStatus.PARTIAL
    assert any("expired" in g.lower() for g in cov.gaps)


def test_festival_only_media_is_a_gap_for_a_theatrical_release():
    """The classic indie trap: cleared for the festival run, then sold."""
    cov = _assess(
        [
            _lic("LIC-1", "Universal Music Publishing Group", RightsType.SYNC,
                 media=["FESTIVAL"]),
            _lic("LIC-2", "Universal Music Group", RightsType.MASTER,
                 media=["FESTIVAL"]),
        ]
    )
    assert cov.status is CoverageStatus.PARTIAL
    assert any("THEATRICAL" in g for g in cov.gaps)


def test_non_music_findings_are_unaffected_by_the_split():
    """Only music carries the two-licence requirement."""
    art = _song().model_copy(
        update={
            "category": ClearanceCategory.COPYRIGHT_ART,
            "element_type": ElementType.ARTWORK,
        }
    )
    cov = assess(
        art,
        _research("Domino Recording Co."),
        [_lic("LIC-9", "Domino Recording Co.", RightsType.ALL)],
        ["US"],
        ["THEATRICAL"],
        as_of="2026-08-22",
    )
    assert cov.status is CoverageStatus.COVERED


# ------------------------------------------------------------------ parsing
def test_csv_ledger_carries_rights_type():
    csv_text = (
        "id,rights_holder,work,rights_type,territories,media\n"
        "LIC-1,Universal Music Publishing Group,Blinding Lights,SYNC,US,THEATRICAL\n"
    )
    (lic,) = parse_licence_csv(csv_text)
    assert lic.rights_type is RightsType.SYNC


def test_ledgers_without_the_column_default_to_all_rights():
    """Existing ledgers keep working; a register that does not distinguish is
    read as granting everything it names, which is how it was read before."""
    csv_text = "id,rights_holder,territories\nLIC-1,Domino Recording Co.,WORLDWIDE\n"
    (lic,) = parse_licence_csv(csv_text)
    assert lic.rights_type is RightsType.ALL


def test_json_ledger_carries_rights_type():
    (lic,) = parse_licence_json(
        '{"licences": [{"rights_holder": "Sony Music Publishing", "rights_type": "SYNC"}]}'
    )
    assert lic.rights_type is RightsType.SYNC


def test_an_unrecognised_rights_type_is_rejected_not_guessed():
    assert parse_licence_json(
        '[{"rights_holder": "X", "rights_type": "PROBABLY_FINE"}]'
    ) == []


# ------------------------------------------------- holder matching precision
@pytest.mark.parametrize(
    "holder,expected",
    [
        ("Universal Music Publishing Group", True),   # the actual composition holder
        ("Universal Music Group", True),              # the actual master holder
        ("Kobalt Music Group", False),                # shares only {music, group}
        ("Warner Chappell Music", False),
        ("Sony Music Publishing", False),             # shares only {publishing}
        ("BMG Rights Management", False),
    ],
)
def test_licences_match_on_identifying_tokens_not_corporate_furniture(holder, expected):
    """A false licence match is the most dangerous error the ledger can make:
    it tells a producer they are covered when they are not."""
    from clearframe.licensing import find_licences

    found = find_licences(OWNER, [_lic("L", holder, RightsType.BOTH)])
    assert bool(found) is expected


def test_a_holder_made_entirely_of_corporate_words_still_matches_itself():
    from clearframe.matching import holders_match

    assert holders_match("The Music Company", "The Music Company") is True
