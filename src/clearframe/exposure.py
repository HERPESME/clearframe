"""On-screen exposure: the threat class that has nothing to do with rights.

Everything else in this codebase asks "who owns this?". Nothing owns a delivery
label with your address on it, a bank statement left on the desk, or a laptop
screen showing someone's messages — which is exactly why no clearance tool
looks for them, and exactly why a creator filming at home is exposed.

Two properties make this worth a module rather than a footnote:

1. **Minors are the top severity everywhere.** Data-protection authorities have
   issued explicit guidance that publishing children's images without parental
   consent breaches the GDPR. That does not scale down because the release
   territory is permissive, so it is not multiplied by the regime factor.

2. **The regime is jurisdictional and the US is the outlier.** An address on
   screen is embarrassing in the United States and is processing of personal
   data in the EU. Our `RIGHT_OF_PUBLICITY` category encodes the US answer;
   this module asks `territory.py` which regime actually governs.

The remedy is always a timecode, because that is the only form a fix can take
in an edit: blur from here to here. Pure code, no I/O.
"""

from clearframe.models import (
    AssessedExposure,
    ClearanceCategory,
    ExposureFinding,
    ExposureKind,
    RiskBand,
)
from clearframe.territory import TERRITORY_RULES, governing_regime

# Base severity before the jurisdiction is considered.
_BASE_SCORE: dict[ExposureKind, int] = {
    ExposureKind.MINOR: 100,
    ExposureKind.PERSONAL_DATA: 70,
    ExposureKind.DOCUMENT: 65,
    ExposureKind.LOCATION_IDENTIFIER: 55,
    ExposureKind.VEHICLE_PLATE: 45,
    ExposureKind.SCREEN_CONTENT: 40,
}

# How seriously the jurisdiction treats publishing identifiable personal data.
# The US is the low end not because exposure is lower but because there is no
# general federal regime covering a face or an address in a video.
_REGIME_FACTOR: dict[str, float] = {
    "gdpr": 1.25,
    "strict": 1.25,
    "consent": 1.15,
    "none": 1.0,
}

_STRICT_REGIME_TERRITORIES = {"GB", "DE", "FR", "ES", "IT", "KR"}
_CONSENT_REGIME_TERRITORIES = {"IN", "BR", "JP", "CA", "AU"}

_WHAT_IT_IS: dict[ExposureKind, str] = {
    ExposureKind.MINOR: (
        "An identifiable child. Data-protection authorities have issued explicit "
        "guidance that publishing children's images without parental consent "
        "breaches the GDPR, and platforms apply stricter defaults again."
    ),
    ExposureKind.PERSONAL_DATA: (
        "Directly identifying information — an address, phone number, email or "
        "account number — readable on screen."
    ),
    ExposureKind.DOCUMENT: (
        "A document readable on screen. Letters, statements and identity papers "
        "carry more than they appear to at a glance."
    ),
    ExposureKind.SCREEN_CONTENT: (
        "A phone or monitor showing private content. What is legible in the "
        "master is often legible after upload."
    ),
    ExposureKind.VEHICLE_PLATE: (
        "A registration plate, which ties the footage to a person through a "
        "public register."
    ),
    ExposureKind.LOCATION_IDENTIFIER: (
        "A house number or street sign at a residence, which combined with other "
        "footage identifies where someone lives."
    ),
}

_BANDS = ((30, RiskBand.LOW), (55, RiskBand.MEDIUM), (80, RiskBand.HIGH))


def _band_for(score: int) -> RiskBand:
    for threshold, band in _BANDS:
        if score < threshold:
            return band
    return RiskBand.CRITICAL


def _timecode(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _window(finding: ExposureFinding) -> str:
    if not finding.time_ranges:
        return "the affected section"
    first, last = finding.time_ranges[0], finding.time_ranges[-1]
    return f"{_timecode(first.start_s)}–{_timecode(last.end_s)}"


def _regime_factor(territory: str) -> float:
    if territory in _STRICT_REGIME_TERRITORIES:
        return _REGIME_FACTOR["gdpr"]
    if territory in _CONSENT_REGIME_TERRITORIES:
        return _REGIME_FACTOR["consent"]
    return _REGIME_FACTOR["none"]


def assess_exposure(finding: ExposureFinding, territory: str) -> AssessedExposure:
    """Severity, governing regime and the fix, for one exposure in one territory."""
    base = _BASE_SCORE[finding.kind]
    # A minor is the ceiling everywhere. Scaling it by jurisdiction would imply
    # some territory where publishing a child's face is more acceptable.
    factor = 1.0 if finding.kind is ExposureKind.MINOR else _regime_factor(territory)
    score = min(100, round(base * factor))

    regime = (
        governing_regime(ClearanceCategory.RIGHT_OF_PUBLICITY, territory)
        if territory in TERRITORY_RULES
        else "Personal data or personality rights (jurisdiction not on file)"
    )

    window = _window(finding)
    mask = (
        f" The region is boxed, so it can be masked in place rather than "
        f"cutting the shot."
        if finding.bbox is not None
        else ""
    )
    consent = (
        " Obtain written parental consent, or blur — there is no de minimis "
        "argument for a child."
        if finding.kind is ExposureKind.MINOR
        else ""
    )

    return AssessedExposure(
        id=finding.id,
        kind=finding.kind,
        description=finding.description,
        time_ranges=finding.time_ranges,
        bbox=finding.bbox,
        territory=territory,
        regime=regime,
        score=score,
        band=_band_for(score),
        rationale=f"{_WHAT_IT_IS[finding.kind]} Governing regime: {regime}",
        remedy=f"Blur or crop at {window} before publishing.{mask}{consent}",
    )


def assess_all_exposures(
    findings: list[ExposureFinding], territories: list[str]
) -> list[AssessedExposure]:
    """Worst territory governs, worst finding first.

    A release into several territories has to be underwritten at the strictest
    standard among them — the same reason `territory.worst_band` exists.
    """
    if not findings:
        return []
    checked = territories or ["US"]
    # Tie-break on regime strictness, not on list order. MINOR is deliberately
    # not scaled by jurisdiction, so every territory scores 100 and a plain
    # `max` reports whichever came first — which on a live US/DE/IN release
    # named "State right of publicity" for a child. The severity was right and
    # the regime was misleading, which is worse than useless: it points the
    # producer at the wrong instrument.
    worst = [
        max(
            (assess_exposure(f, t) for t in checked),
            key=lambda a: (a.score, _regime_factor(a.territory)),
        )
        for f in findings
    ]
    return sorted(worst, key=lambda a: a.score, reverse=True)


def summarise_exposures(assessed: list[AssessedExposure]) -> dict:
    counts = {band.value: 0 for band in RiskBand}
    for a in assessed:
        counts[a.band.value] += 1
    return {
        **counts,
        "total": len(assessed),
        "worst_kind": assessed[0].kind.value if assessed else None,
    }
