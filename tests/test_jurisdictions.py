"""Jurisdiction as "which legal system governs this finding", not panorama trivia.

Six countries at two dimensions told a creator in Delhi nothing different from
one in Berlin. The dimensions that actually change the advice are parody, the
open/closed shape of the exceptions regime, incidental inclusion, moral rights,
the personal-data regime, and the defamation standard.
"""

import pytest

from clearframe.models import (
    ClearanceCategory,
    ElementType,
    Prominence,
    TimeRange,
    TriagedElement,
)
from clearframe.territory import (
    TERRITORY_RULES,
    assess,
    defences_for,
    governing_regime,
    load_jurisdictions,
)
from clearframe.models import RiskBand


def el(category, label="x"):
    types = {
        ClearanceCategory.TRADEMARK: ElementType.LOGO,
        ClearanceCategory.COPYRIGHT_ART: ElementType.ARTWORK,
        ClearanceCategory.MUSIC_SYNC: ElementType.MUSIC,
        ClearanceCategory.RIGHT_OF_PUBLICITY: ElementType.FACE,
        ClearanceCategory.LOCATION: ElementType.LOCATION,
        ClearanceCategory.TEXT_ON_SCREEN: ElementType.TEXT,
    }
    return TriagedElement(
        id="e1", label=label, element_type=types[category], description="",
        time_ranges=[TimeRange(start_s=0.0, end_s=5.0)],
        prominence=Prominence(screen_time_s=5.0, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
        category=category,
    )


# --------------------------------------------------------------- the data
def test_coverage_widened_without_losing_the_originals():
    assert {"US", "GB", "DE", "FR", "JP", "IN"} <= set(TERRITORY_RULES)
    assert {"CA", "AU", "BR", "KR", "ES", "IT"} <= set(TERRITORY_RULES)
    assert len(TERRITORY_RULES) >= 12


def test_every_jurisdiction_carries_every_dimension_with_an_authority():
    required = {
        "name", "panorama", "authority", "publicity", "parody", "parody_authority",
        "exceptions_model", "incidental_inclusion", "moral_rights",
        "personal_data", "defamation",
    }
    for code, rule in TERRITORY_RULES.items():
        assert required <= set(rule), f"{code} missing {required - set(rule)}"
        assert rule["authority"], code


def test_the_original_two_dimensions_are_unchanged():
    """Existing banding must not move — territory.assess is calibrated on these."""
    assert TERRITORY_RULES["US"]["panorama"] == "buildings_only"
    assert TERRITORY_RULES["DE"]["panorama"] == "broad"
    assert TERRITORY_RULES["FR"]["panorama"] == "narrow"
    assert TERRITORY_RULES["US"]["publicity"] == "strong"


def test_existing_banding_is_untouched():
    mural = el(ClearanceCategory.COPYRIGHT_ART, "Street mural (unknown artist)")
    bands = {t: assess(mural, RiskBand.MEDIUM, t).band for t in ("US", "DE", "FR")}
    assert bands == {"US": RiskBand.MEDIUM, "DE": RiskBand.LOW, "FR": RiskBand.HIGH}


# ------------------------------------------------------------------ parody
def test_parody_is_available_where_it_is_and_not_where_it_is_not():
    """The single most useful dimension for a skit maker — and the answer
    differs by country in a way nobody expects."""
    have = {"US", "GB", "DE", "FR", "CA", "AU", "ES"}
    have_not = {"IN", "JP", "IT"}
    for code in have:
        d = _defence(el(ClearanceCategory.COPYRIGHT_ART), code, "parody")
        assert d.available is True, code
        assert d.authority, code
    for code in have_not:
        d = _defence(el(ClearanceCategory.COPYRIGHT_ART), code, "parody")
        assert d.available is False, code


def test_india_has_no_parody_exception_and_says_why():
    d = _defence(el(ClearanceCategory.COPYRIGHT_ART), "IN", "parody")
    assert d.available is False
    assert "criticism" in d.note.lower()


def _defence(element, territory, name_fragment):
    matches = [
        d for d in defences_for(element, territory)
        if name_fragment.lower() in d.name.lower()
    ]
    assert matches, f"{territory}: no defence matching {name_fragment!r}"
    return matches[0]


# ------------------------------------------------- open vs closed exceptions
def test_only_the_us_has_an_open_ended_exceptions_regime():
    assert TERRITORY_RULES["US"]["exceptions_model"] == "open"
    for code in ("GB", "IN", "CA", "AU", "DE", "FR"):
        assert TERRITORY_RULES[code]["exceptions_model"] != "open", code


def test_a_de_minimis_memo_does_not_travel():
    """The practical consequence: a fair-use position written for California is
    worthless in a closed-list country."""
    us = _defence(el(ClearanceCategory.COPYRIGHT_ART), "US", "fair use")
    india = defences_for(el(ClearanceCategory.COPYRIGHT_ART), "IN")
    assert us.available is True
    assert not any(d.name.lower().startswith("fair use") and d.available for d in india)


# ------------------------------------------------- incidental inclusion
def test_india_is_unusually_generous_about_background_artwork():
    d = _defence(el(ClearanceCategory.COPYRIGHT_ART), "IN", "incidental")
    assert d.available is True
    assert "52(1)(u)" in d.authority


def test_the_us_has_no_statutory_incidental_inclusion():
    d = _defence(el(ClearanceCategory.COPYRIGHT_ART), "US", "incidental")
    assert d.available is False
    assert "de minimis" in d.note.lower()


# ------------------------------------------------------------ personal data
@pytest.mark.parametrize(
    "territory,expected",
    [("US", "publicity"), ("DE", "GDPR"), ("GB", "GDPR"), ("IN", "DPDP"), ("BR", "LGPD")],
)
def test_the_same_face_is_governed_by_a_different_regime_per_country(territory, expected):
    """RIGHT_OF_PUBLICITY is a US commercial-appropriation concept. Elsewhere an
    identifiable face is personal data, with a different remedy."""
    regime = governing_regime(ClearanceCategory.RIGHT_OF_PUBLICITY, territory)
    assert expected.lower() in regime.lower()


def test_music_is_governed_by_copyright_everywhere():
    for code in TERRITORY_RULES:
        assert "copyright" in governing_regime(ClearanceCategory.MUSIC_SYNC, code).lower()


# ---------------------------------------------------------------- panorama
def test_italy_has_no_freedom_of_panorama_and_adds_a_permit():
    """The most restrictive in the table, and for two separate reasons."""
    assert TERRITORY_RULES["IT"]["panorama"] == "none"
    d = _defence(el(ClearanceCategory.COPYRIGHT_ART), "IT", "panorama")
    assert d.available is False
    assert "cultural" in d.note.lower()


def test_an_unknown_territory_degrades_rather_than_raising():
    assert defences_for(el(ClearanceCategory.COPYRIGHT_ART), "ZZ") == []
    assert governing_regime(ClearanceCategory.MUSIC_SYNC, "ZZ")


def test_the_dataset_records_when_it_was_verified():
    doc = load_jurisdictions()
    assert doc["verified_on"]


def test_no_defence_is_reported_available_that_its_own_authority_denies():
    """Caught by reading the rendered output: Italy and France were marked as
    having an incidental-inclusion exception while their authority text said
    plainly that they do not. A defence reported as available when it does not
    exist is the most dangerous output this module can produce."""
    denial = ("no general incidental", "no statutory", "no freedom-of-panorama",
              "no parody exception", "judge-made")
    for code in TERRITORY_RULES:
        for element_category in (ClearanceCategory.COPYRIGHT_ART,
                                 ClearanceCategory.RIGHT_OF_PUBLICITY):
            for d in defences_for(el(element_category), code):
                if not d.available:
                    continue
                text = d.authority.lower()
                assert not any(phrase in text for phrase in denial), (
                    f"{code}: '{d.name}' reported available, but its authority "
                    f"reads: {d.authority}"
                )
