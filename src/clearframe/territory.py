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

from clearframe.models import (
    ClearanceCategory,
    RiskBand,
    TerritoryRisk,
    TriagedElement,
)

_BAND_ORDER = (RiskBand.LOW, RiskBand.MEDIUM, RiskBand.HIGH, RiskBand.CRITICAL)

# Freedom of panorama for works permanently sited in a public place.
#   "broad"  - covers artworks/sculpture as well as buildings
#   "buildings_only" - architecture only; artwork remains exposed
#   "narrow" - exception exists but excludes commercial exploitation
TERRITORY_RULES: dict[str, dict[str, str]] = {
    "US": {
        "name": "United States",
        "panorama": "buildings_only",
        "authority": "17 U.S.C. §120(a) — pictorial representation exemption covers architectural works only",
        "publicity": "strong",
    },
    "GB": {
        "name": "United Kingdom",
        "panorama": "broad",
        "authority": "CDPA 1988 s.62 — buildings, sculptures and works of artistic craftsmanship on public display",
        "publicity": "moderate",
    },
    "DE": {
        "name": "Germany",
        "panorama": "broad",
        "authority": "UrhG §59 (Panoramafreiheit) — works permanently in public ways or open places",
        "publicity": "strong",
    },
    "FR": {
        "name": "France",
        "panorama": "narrow",
        "authority": "CPI art. L.122-5 11° — panorama exception limited to non-commercial use by natural persons",
        "publicity": "strong",
    },
    "JP": {
        "name": "Japan",
        "panorama": "broad",
        "authority": "Copyright Act art. 46 — artistic works permanently installed in open places",
        "publicity": "moderate",
    },
    "IN": {
        "name": "India",
        "panorama": "broad",
        "authority": "Copyright Act s.52(1)(s)-(t) — sculpture/architecture permanently situated in a public place",
        "publicity": "moderate",
    },
}

DEFAULT_TERRITORIES = ("US",)

# Panorama analysis only bears on works fixed in the physical environment.
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
