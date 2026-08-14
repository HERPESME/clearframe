"""Deterministic risk scoring: every score is reproducible from stored inputs."""

from clearframe.models import (
    ClearanceCategory,
    LicensingPosture,
    ResearchResult,
    RiskAssessment,
    RiskBand,
    TriagedElement,
)

CATEGORY_WEIGHT: dict[ClearanceCategory, float] = {
    ClearanceCategory.MUSIC_SYNC: 1.0,
    ClearanceCategory.COPYRIGHT_ART: 0.9,
    ClearanceCategory.RIGHT_OF_PUBLICITY: 0.9,
    ClearanceCategory.TRADEMARK: 0.8,
    ClearanceCategory.TEXT_ON_SCREEN: 0.6,
    ClearanceCategory.LOCATION: 0.5,
}

POSTURE_FACTOR: dict[LicensingPosture, float] = {
    LicensingPosture.LITIGIOUS: 1.0,
    LicensingPosture.STANDARD: 0.7,
    LicensingPosture.UNKNOWN: 0.7,
    LicensingPosture.PERMISSIVE: 0.4,
}

_BANDS = ((20, RiskBand.LOW), (45, RiskBand.MEDIUM), (70, RiskBand.HIGH))


def band_for(score: int) -> RiskBand:
    for threshold, band in _BANDS:
        if score < threshold:
            return band
    return RiskBand.CRITICAL


def score_element(element: TriagedElement, research: ResearchResult | None) -> RiskAssessment:
    p = element.prominence
    screen_time_norm = min(p.screen_time_s / 10.0, 1.0)
    prominence_score = (
        0.4 * screen_time_norm
        + 0.3 * p.frame_coverage
        + 0.2 * p.centrality
        + (0.1 if p.plot_integral else 0.0)
    )
    weight = CATEGORY_WEIGHT[element.category]

    if research is None or research.status == "incomplete":
        posture = LicensingPosture.UNKNOWN
    else:
        posture = research.licensing_posture
    posture_factor = POSTURE_FACTOR[posture]

    score = round(100 * prominence_score * weight * posture_factor)

    de_minimis = (
        p.screen_time_s < 2.0
        and p.frame_coverage < 0.05
        and p.centrality < 0.3
        and not p.plot_integral
    )
    band = band_for(score)
    if de_minimis:
        band = RiskBand.LOW

    return RiskAssessment(
        element_id=element.id,
        score=score,
        band=band,
        factors={
            "screen_time_norm": round(screen_time_norm, 3),
            "prominence_score": round(prominence_score, 3),
            "category_weight": round(weight, 3),
            "posture_factor": round(posture_factor, 3),
        },
        de_minimis=de_minimis,
    )
