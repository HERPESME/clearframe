import pytest

from clearframe.licensing import (
    assess,
    assign_ids,
    parse_licence_csv,
    parse_licence_json,
    summarise,
)
from clearframe.models import (
    ClearanceCategory,
    CoverageStatus,
    ElementType,
    LicenceGrant,
    LicensingPosture,
    Prominence,
    ResearchResult,
    TimeRange,
    TriagedElement,
)
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context

AS_OF = "2026-08-22T00:00:00Z"
TERRITORIES = ["US", "DE", "FR"]
MEDIA = ["THEATRICAL", "STREAMING"]


def element(label="Coca-Cola can"):
    return TriagedElement(
        id="e2",
        label=label,
        element_type=ElementType.LOGO,
        description="",
        time_ranges=[TimeRange(start_s=5, end_s=11)],
        prominence=Prominence(
            screen_time_s=6, frame_coverage=0.08, centrality=0.6, plot_integral=False
        ),
        category=ClearanceCategory.TRADEMARK,
    )


def research(owner="The Coca-Cola Company", status="complete"):
    return ResearchResult(
        element_id="e2",
        owner=owner,
        owner_confidence="high",
        licensing_contact=None,
        licensing_posture=LicensingPosture.STANDARD,
        litigation_history=[],
        estimated_license_cost_band=None,
        basis=[],
        status=status,
    )


def licence(**kw):
    base = dict(
        id="LIC-001",
        rights_holder="The Coca-Cola Company",
        territories=["WORLDWIDE"],
        media=["ALL"],
        expires=None,
    )
    base.update(kw)
    return LicenceGrant(**base)


def test_worldwide_perpetual_grant_is_covered():
    cov = assess(element(), research(), [licence()], TERRITORIES, MEDIA, AS_OF)
    assert cov.status is CoverageStatus.COVERED
    assert cov.licence_id == "LIC-001" and cov.gaps == []


def test_territory_gap_is_partial_and_names_the_missing_countries():
    cov = assess(
        element(), research(), [licence(territories=["US"])], TERRITORIES, MEDIA, AS_OF
    )
    assert cov.status is CoverageStatus.PARTIAL
    assert "DE, FR" in cov.gaps[0]


def test_media_gap_is_partial():
    cov = assess(
        element(), research(), [licence(media=["THEATRICAL"])], TERRITORIES, MEDIA, AS_OF
    )
    assert cov.status is CoverageStatus.PARTIAL
    assert "STREAMING" in cov.gaps[0]


def test_expired_licence_is_partial():
    cov = assess(
        element(), research(), [licence(expires="2025-12-31")], TERRITORIES, MEDIA, AS_OF
    )
    assert cov.status is CoverageStatus.PARTIAL
    assert "expired" in cov.gaps[0]


def test_no_matching_licence_is_not_covered():
    cov = assess(
        element("Nike hoodie swoosh"),
        research("Nike, Inc."),
        [licence()],
        TERRITORIES,
        MEDIA,
        AS_OF,
    )
    assert cov.status is CoverageStatus.NOT_COVERED
    assert cov.licence_id is None


def test_unidentified_owner_is_unknown_not_uncovered():
    # Coverage is genuinely unknowable without an owner; saying NOT_COVERED
    # would assert something we have not established.
    cov = assess(element(), research(owner=None, status="incomplete"), [licence()],
                 TERRITORIES, MEDIA, AS_OF)
    assert cov.status is CoverageStatus.UNKNOWN


def test_verbose_researched_owner_matches_ledger_holder():
    owner = (
        "The Weeknd XO, Inc. / Universal Music Group (master); "
        "Universal Music Publishing Group (composition)"
    )
    cov = assess(
        element("Blinding Lights"),
        research(owner),
        [licence(id="LIC-002", rights_holder="Universal Music Publishing Group")],
        TERRITORIES,
        MEDIA,
        AS_OF,
    )
    assert cov.licence_id == "LIC-002"


def test_a_clean_licence_beats_a_gapped_one():
    grants = [
        licence(id="LIC-A", territories=["US"]),
        licence(id="LIC-B"),
    ]
    cov = assess(element(), research(), grants, TERRITORIES, MEDIA, AS_OF)
    assert cov.status is CoverageStatus.COVERED and cov.licence_id == "LIC-B"


def test_csv_upload_parses_pipe_separated_territories():
    csv = (
        "rights_holder,scope,territories,media,expires\n"
        "A24 Films,Footage licence,US|GB|DE,STREAMING|THEATRICAL,2030-01-01\n"
    )
    rows = parse_licence_csv(csv)
    assert len(rows) == 1
    assert rows[0].territories == ["US", "GB", "DE"]
    assert rows[0].media == ["STREAMING", "THEATRICAL"]
    assert rows[0].id == ""  # unnumbered until merged


def test_csv_without_rights_holder_column_is_rejected():
    with pytest.raises(ValueError, match="rights_holder"):
        parse_licence_csv("name,scope\nFoo,Bar\n")


def test_json_upload_accepts_both_shapes():
    body = '{"licences": [{"rights_holder": "Sony Music Entertainment"}]}'
    bare = '[{"rights_holder": "Sony Music Entertainment"}]'
    assert len(parse_licence_json(body)) == 1
    assert len(parse_licence_json(bare)) == 1
    with pytest.raises(ValueError):
        parse_licence_json("not json")


def test_assign_ids_never_overwrites_existing_entries():
    # An uploaded register usually has no id column; numbering by position
    # would silently clobber ledger rows on merge.
    parsed = [LicenceGrant(id="", rights_holder="A"), LicenceGrant(id="", rights_holder="B")]
    out = assign_ids(parsed, {"LIC-001", "LIC-002"})
    assert [lic.id for lic in out] == ["LIC-003", "LIC-004"]


def test_assign_ids_keeps_explicit_ids():
    parsed = [LicenceGrant(id="MY-1", rights_holder="A")]
    assert assign_ids(parsed, {"LIC-001"})[0].id == "MY-1"


async def test_demo_pipeline_reports_the_full_coverage_picture(tmp_path):
    state = await Pipeline(build_demo_pipeline()).run(demo_context(tmp_path))
    status = {eid: c.status for eid, c in state.coverage.items()}
    assert status["e2"] is CoverageStatus.COVERED  # Coca-Cola, worldwide/all media
    assert status["e4"] is CoverageStatus.COVERED  # Arctic Monkeys artwork
    assert status["e1"] is CoverageStatus.PARTIAL  # UMPG: US + theatrical only
    assert status["e7"] is CoverageStatus.PARTIAL  # KXBC-7 licence lapsed
    assert status["e3"] is CoverageStatus.NOT_COVERED  # Nike, nothing on file
    # LIC-005 grants Adidas worldwide, but the duffel's identity is disputed —
    # a licence cannot cover a finding we cannot name.
    assert status["e8"] is CoverageStatus.UNKNOWN
    counts = summarise(state.coverage)
    assert counts["COVERED"] == 2 and counts["PARTIAL"] == 2


async def test_covered_findings_auto_approve_on_the_licence(tmp_path):
    from clearframe.dossier import auto_decisions

    state = await Pipeline(build_demo_pipeline()).run(demo_context(tmp_path))
    decisions = auto_decisions(state)
    assert decisions["e2"].action == "approve_risk"
    assert "LIC-001" in decisions["e2"].note
    assert decisions["e1"].action == "license"
    assert "territory not granted" in decisions["e1"].note
