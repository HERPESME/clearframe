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


def _shift(band: RiskBand, steps: int) -> RiskBand:
    idx = _BAND_ORDER.index(band)
    return _BAND_ORDER[max(0, min(len(_BAND_ORDER) - 1, idx + steps))]


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

    if element.category in _PANORAMA_CATEGORIES:
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

    return TerritoryRisk(
        element_id=element.id,
        territory=territory,
        band=base_band,
        rationale=(
            f"{element.category.value} exposure does not vary by panorama rule; "
            f"{rule['name']} tracks the baseline band."
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
