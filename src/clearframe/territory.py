"""Territory-aware clearance risk: the same frame is not equally risky everywhere.

Clearance is jurisdictional. A mural filmed on a public street is an
infringement exposure in the United States — 17 U.S.C. §120(a) grants freedom
of panorama for *buildings only*, not for pictorial or sculptural works — while
the identical shot is generally permitted in Germany (UrhG §59) or the UK
(CDPA s.62). Distributors buy territories separately, so a per-territory band
is what a sales agent actually needs.

Deterministic like `scoring.py`: a lookup table plus band arithmetic, fully
reproducible from stored inputs, never an LLM. Output is decision support and
carries the same "confirm with counsel" caveat as the rest of the dossier.
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from clearframe.models import (
    ClearanceCategory,
    ElementType,
    RiskBand,
    TerritoryRisk,
    TriagedElement,
)

_BAND_ORDER = (RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL)

# Jurisdiction rules now live in data/jurisdictions.json so the table can grow
# without touching the banding arithmetic. TERRITORY_RULES keeps its original
# shape and values — `assess` below is calibrated on them and must not move.
#
# Freedom of panorama for works permanently sited in a public place:
#   "broad"           - covers artworks/sculpture as well as buildings
#   "buildings_only"  - architecture only; artwork remains exposed
#   "narrow"          - exception exists but excludes commercial exploitation
#   "none"            - no exception at all (Italy, which additionally requires
#                       Ministry authorisation for images of cultural property)
DATA_PATH = Path(__file__).parent / "data" / "jurisdictions.json"


@lru_cache(maxsize=1)
def load_jurisdictions(data_path: str | None = None) -> dict:
    return json.loads(Path(data_path or DATA_PATH).read_text())


def _rules() -> dict[str, dict[str, str]]:
    doc = load_jurisdictions()
    return {j["code"]: {k: v for k, v in j.items() if k != "code"} for j in doc["jurisdictions"]}


TERRITORY_RULES: dict[str, dict[str, str]] = _rules()


class Defence(BaseModel):
    """A defence that may or may not exist in this jurisdiction.

    `available: False` is the useful half. A skit maker who knows parody is a
    statutory defence in the UK and simply absent in India has learned
    something no single global answer could tell them.
    """

    territory: str
    name: str
    available: bool
    authority: str
    note: str = ""


# Which body of law actually governs each category, per jurisdiction. The one
# that surprises people: RIGHT_OF_PUBLICITY is a US commercial-appropriation
# concept. Elsewhere an identifiable face is personal data, with a different
# remedy — blur or a lawful basis, not a licence.
_COPYRIGHT = "Copyright"
_REGIME_BY_CATEGORY = {
    ClearanceCategory.MUSIC_SYNC: _COPYRIGHT,
    ClearanceCategory.COPYRIGHT_ART: _COPYRIGHT,
    ClearanceCategory.TRADEMARK: "Trade marks and unfair competition",
    ClearanceCategory.TEXT_ON_SCREEN: "Trade marks and unfair competition",
    ClearanceCategory.LOCATION: "Property, trade dress and location agreements",
}


def governing_regime(category: ClearanceCategory, territory: str) -> str:
    """Which body of law decides this finding here."""
    if category is not ClearanceCategory.RIGHT_OF_PUBLICITY:
        return _REGIME_BY_CATEGORY.get(category, _COPYRIGHT)
    rule = TERRITORY_RULES.get(territory)
    if rule is None:
        return "Personal data or personality rights (jurisdiction not on file)"
    return rule["personal_data"]


_PARODY_AVAILABLE = {"fair_use", "fair_dealing", "statutory"}
_INCIDENTAL_AVAILABLE = {"broad", "narrow"}


def defences_for(element: TriagedElement, territory: str) -> list[Defence]:
    """Every defence this jurisdiction does — and does not — offer this finding.

    Returns an empty list for an unknown territory rather than guessing: an
    invented defence is the most dangerous output this module could produce.
    """
    rule = TERRITORY_RULES.get(territory)
    if rule is None:
        return []

    out: list[Defence] = [
        Defence(
            territory=territory,
            name="Parody / caricature",
            available=rule["parody"] in _PARODY_AVAILABLE,
            authority=rule["parody_authority"],
            note=(
                ""
                if rule["parody"] in _PARODY_AVAILABLE
                else "No statutory parody exception here. Any parody argument runs "
                "through criticism, review or free expression instead — an argument "
                "to be made, not a safe harbour to rely on."
            ),
        ),
        Defence(
            territory=territory,
            name="Fair use (open-ended)",
            available=rule["exceptions_model"] == "open",
            authority=rule["exceptions_authority"],
            note=(
                ""
                if rule["exceptions_model"] == "open"
                else "Closed list: a use that is not on the statutory list is "
                "infringing however reasonable it looks. A fair-use memo written "
                "for the US does not travel here."
            ),
        ),
        Defence(
            territory=territory,
            name="Incidental inclusion",
            available=rule["incidental_inclusion"] in _INCIDENTAL_AVAILABLE,
            authority=rule["incidental_authority"],
            note=(
                "No statutory incidental-inclusion exception; de minimis is "
                "judge-made and fact-specific."
                if rule["incidental_inclusion"] == "case_law"
                else ""
            ),
        ),
    ]

    if element.category in (ClearanceCategory.COPYRIGHT_ART, ClearanceCategory.LOCATION):
        out.append(
            Defence(
                territory=territory,
                name="Freedom of panorama",
                available=rule["panorama"] in ("broad", "narrow"),
                authority=rule["authority"],
                note=(
                    "No panorama exception at all, and commercial use of images of "
                    "cultural property needs separate Ministry authorisation."
                    if rule["panorama"] == "none"
                    else "Covers architecture only — artwork on a building is not "
                    "exempt (this is what Falkner v. GM turned on)."
                    if rule["panorama"] == "buildings_only"
                    else ""
                ),
            )
        )
        out.append(
            Defence(
                territory=territory,
                name="Moral rights (a risk, not a defence)",
                available=False,
                authority=rule["moral_authority"],
                note=(
                    "Perpetual and inalienable here: the author can object to "
                    "treatment of the work even after selling the copyright, and "
                    "heirs can assert it without time limit."
                    if rule["moral_rights"] == "perpetual"
                    else "Attribution and integrity rights persist alongside the "
                    "economic rights."
                ),
            )
        )

    if element.category is ClearanceCategory.RIGHT_OF_PUBLICITY:
        out.append(
            Defence(
                territory=territory,
                name="Personal data / personality regime",
                available=False,
                authority=rule["personal_data"],
                note=(
                    "The remedy here is consent or a blur, not a licence — a "
                    "different instrument from the US right of publicity."
                ),
            )
        )

    return out


_PANORAMA_CATEGORIES = {ClearanceCategory.COPYRIGHT_ART, ClearanceCategory.LOCATION}


# Freedom of panorama turns on one fact and one fact only: is the work
# permanently installed somewhere the public can reach? The whole COPYRIGHT_ART
# category used to be run through the panorama branch, so a face tattoo, a
# t-shirt print and a sticker on an indoor water heater were all banded under
# the exception for public sculpture — and it moved the band, down in DE/IN and
# up in FR.
#
# Only these two element types can be permanently sited at all. A tattoo is on
# a person; a drawn character is on a cel; a logo is on a product.
_SITEABLE_TYPES = {ElementType.ARTWORK, ElementType.LOCATION}

_PUBLIC_PERMANENT = "public_permanent"


def _panorama_applies(element: TriagedElement) -> bool:
    return (
        element.category in _PANORAMA_CATEGORIES
        and element.element_type in _SITEABLE_TYPES
        and element.siting == _PUBLIC_PERMANENT
    )


def _panorama_undetermined(element: TriagedElement) -> bool:
    """Could have been a panorama case; the scan could not tell."""
    return (
        element.category in _PANORAMA_CATEGORIES
        and element.element_type in _SITEABLE_TYPES
        and element.siting not in (_PUBLIC_PERMANENT, "portable_or_interior")
    )


def _shift(band: RiskBand, steps: int) -> RiskBand:
    idx = _BAND_ORDER.index(band)
    return _BAND_ORDER[max(0, min(len(_BAND_ORDER) - 1, idx + steps))]


# Copyright works that are NOT permanently sited — a tattoo, a t-shirt print, a
# sticker, a poster on an interior wall — plus readable on-screen text. For
# these the jurisdictional question is not panorama but whether background
# inclusion is excused at all, which is exactly where the table differs most:
# statutory and generous in GB/IN/CA, narrow in DE/JP/AU/BR/KR/ES, judge-made
# in US/FR, and entirely absent in Italy.
_INCIDENTAL_GOVERNED = {
    ClearanceCategory.COPYRIGHT_ART,
    ClearanceCategory.TEXT_ON_SCREEN,
}

# Moral rights survive the economic ones and cannot be waived in these
# jurisdictions, so an heir can object to a treatment a licence permitted.
_PERPETUAL_MORAL = "perpetual"


def _is_incidental(element: TriagedElement) -> bool:
    """Genuinely in the background — the only thing the exception ever covers.

    Deliberately the same shape as `scoring.de_minimis`: an exception for
    incidental inclusion is worth nothing to a work the camera dwells on.
    """
    p = element.prominence
    return (
        not p.plot_integral
        and p.screen_time_s < 5.0
        and p.frame_coverage < 0.15
        and p.centrality < 0.5
    )


def _incidental_risk(
    element: TriagedElement, base_band: RiskBand, territory: str, rule: dict
) -> TerritoryRisk:
    incidental = rule["incidental_inclusion"]
    moral = (
        " Moral rights are perpetual here and cannot be waived, so the author's "
        "heirs can object to how the work is treated even under a licence."
        if rule["moral_rights"] == _PERPETUAL_MORAL
        else ""
    )

    if incidental == "none":
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=_shift(base_band, 1),
            rationale=(
                f"{rule['name']} has no incidental-inclusion exception at all, so "
                "background presence is not excused however fleeting. Risk steps up."
                + moral
            ),
            authority=rule["incidental_authority"],
        )

    if incidental in _INCIDENTAL_AVAILABLE and _is_incidental(element):
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=_shift(base_band, -1) if incidental == "broad" else base_band,
            rationale=(
                f"{rule['name']} excuses incidental inclusion by statute, and this "
                "finding is genuinely in the background rather than featured."
                + (
                    " Risk steps down."
                    if incidental == "broad"
                    else " The exception is narrow, so the band is unchanged."
                )
                + moral
            ),
            authority=rule["incidental_authority"],
        )

    if incidental in _INCIDENTAL_AVAILABLE:
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=base_band,
            rationale=(
                f"{rule['name']} excuses incidental inclusion, but only where the "
                "work really is incidental. This one is featured or sustained "
                "enough that the exception cannot be relied on." + moral
            ),
            authority=rule["incidental_authority"],
        )

    return TerritoryRisk(
        element_id=element.id,
        territory=territory,
        band=base_band,
        rationale=(
            f"{rule['name']} has no statutory incidental-inclusion exception; "
            "de minimis is judge-made and decided on the facts, so it is an "
            "argument to run rather than a safe harbour." + moral
        ),
        authority=rule["incidental_authority"],
    )


def assess(
    element: TriagedElement, base_band: RiskBand, territory: str
) -> TerritoryRisk:
    """Band this element for one release territory, with the governing authority."""
    rule = TERRITORY_RULES.get(territory)
    if rule is None:
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=base_band,
            rationale="No territory rule on file; falls back to the jurisdiction-neutral band.",
            authority="",
        )

    if _panorama_applies(element):
        panorama = rule["panorama"]
        if panorama == "broad":
            return TerritoryRisk(
                element_id=element.id,
                territory=territory,
                band=_shift(base_band, -1),
                rationale=(
                    f"{rule['name']} recognises freedom of panorama for works permanently "
                    "sited in public. Risk steps down IF this work is permanently installed "
                    "and filmed from a place accessible to the public — confirm both before relying on it."
                ),
                authority=rule["authority"],
            )
        if panorama == "none":
            return TerritoryRisk(
                element_id=element.id,
                territory=territory,
                band=_shift(base_band, 1),
                rationale=(
                    f"{rule['name']} grants no freedom-of-panorama exception at all, "
                    "so filming a work permanently sited in public is not excused by "
                    "its being in public. Publishing images of cultural property "
                    "additionally requires Ministry authorisation, which is an "
                    "administrative permission and not a copyright licence — holding "
                    "one does not give you the other. Risk steps up."
                ),
                authority=rule["authority"],
            )
        if panorama == "narrow":
            return TerritoryRisk(
                element_id=element.id,
                territory=territory,
                band=_shift(base_band, 1),
                rationale=(
                    f"{rule['name']} limits its panorama exception to non-commercial use, so "
                    "commercial distribution is not covered. Risk steps up."
                ),
                authority=rule["authority"],
            )
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=base_band,
            rationale=(
                f"{rule['name']} extends panorama freedom to architecture only; a pictorial or "
                "sculptural work in frame stays exposed at the baseline band."
            ),
            authority=rule["authority"],
        )

    if _panorama_undetermined(element):
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=base_band,
            rationale=(
                f"{rule['name']}'s panorama exception covers works permanently "
                "installed in a place the public can reach, and the scan could not "
                "establish whether this one is. The band is unchanged in either "
                "direction: establish the siting to claim the exception, because a "
                "discount for not knowing is worth nothing to an E&O carrier."
            ),
            authority=rule["authority"],
        )

    if (
        element.category == ClearanceCategory.RIGHT_OF_PUBLICITY
        and rule["publicity"] == "strong"
    ):
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=_shift(base_band, 1),
            rationale=(
                f"{rule['name']} enforces strong personality/image rights, so an identifiable "
                "person in frame carries elevated exposure without a signed release."
            ),
            authority=rule["authority"],
        )

    # Everything that is not a siting or a publicity question. Panorama is one
    # of eight dimensions in the table and governs almost nothing in a typical
    # clip; framing every other finding as "does not vary by panorama rule"
    # told a producer which rule was IRRELEVANT and never which one applied.
    if element.category in _INCIDENTAL_GOVERNED:
        return _incidental_risk(element, base_band, territory, rule)

    if element.category == ClearanceCategory.TRADEMARK:
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=base_band,
            rationale=(
                f"A mark in an expressive work is judged by {rule['name']}'s own "
                "test, not by panorama or incidental-inclusion rules. "
                + (
                    "An open-ended fair-use standard is available here."
                    if rule["exceptions_model"] == "open"
                    else "The exceptions here are a closed statutory list, so a "
                    "US Rogers v. Grimaldi memo does not travel — the argument "
                    "has to be rebuilt on local grounds."
                )
            ),
            authority=rule["exceptions_authority"],
        )

    if element.category == ClearanceCategory.MUSIC_SYNC:
        return TerritoryRisk(
            element_id=element.id,
            territory=territory,
            band=base_band,
            rationale=(
                "Music does not vary by jurisdiction in the way visual works do: "
                "a synchronisation licence and a master licence are required in "
                f"every territory including {rule['name']}, and no incidental or "
                "panorama exception substitutes for either."
            ),
            authority="",
        )

    return TerritoryRisk(
        element_id=element.id,
        territory=territory,
        band=base_band,
        rationale=(
            f"{element.category.value} exposure tracks the baseline band in "
            f"{rule['name']}; no jurisdiction-specific exception applies to it."
        ),
        authority="",
    )


def assess_all(
    elements: list[TriagedElement],
    risk: dict[str, "object"],
    territories: list[str],
) -> dict[str, list[TerritoryRisk]]:
    """Per-element, per-territory bands. `risk` maps element id -> RiskAssessment."""
    out: dict[str, list[TerritoryRisk]] = {}
    for el in elements:
        base = risk[el.id].band
        out[el.id] = [assess(el, base, t) for t in territories]
    return out


def worst_band(rows: list[TerritoryRisk]) -> RiskBand:
    """The band a worldwide release must underwrite."""
    return max((r.band for r in rows), key=_BAND_ORDER.index, default=RiskBand.LOW)
