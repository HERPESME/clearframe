"""Deterministic risk scoring: every score is reproducible from stored inputs."""

from clearframe.models import (
    ClearanceCategory,
    DepictionTone,
    UseContext,
    LicensingPosture,
    ResearchResult,
    RiskAssessment,
    RiskBand,
    TriagedElement,
    research_is_incomplete,
)

CATEGORY_WEIGHT: dict[ClearanceCategory, float] = {
    ClearanceCategory.MUSIC_SYNC: 1.0,
    ClearanceCategory.COPYRIGHT_ART: 0.9,
    ClearanceCategory.RIGHT_OF_PUBLICITY: 0.9,
    ClearanceCategory.TRADEMARK: 0.8,
    ClearanceCategory.TEXT_ON_SCREEN: 0.6,
    ClearanceCategory.LOCATION: 0.5,
}

# What kind of work this is. Rogers v. Grimaldi protects expressive works and
# not advertising, and the litigation record splits cleanly along that line —
# every brand-owner win is an advert, every loss is an expressive work.
#
# EXPRESSIVE is 1.0 by construction: it is the baseline the rest of the model
# was calibrated against, so a production that declares nothing scores exactly
# as it did before this factor existed.
USE_CONTEXT_FACTOR: dict[UseContext, float] = {
    UseContext.NEWS: 0.75,          # newsworthiness is the strongest defence
    UseContext.EDUCATIONAL: 0.85,   # commentary, criticism, teaching
    UseContext.EXPRESSIVE: 1.0,     # baseline — film, TV, skit
    UseContext.SPONSORED: 1.25,     # paid placement inside otherwise-expressive work
    UseContext.ADVERTISING: 1.4,    # commercial speech; no expressive shield
}

# Music is exempt. A synchronisation licence and a master-use licence are
# required for a news report, a feature and an advert alike — there is no
# expressive-use defence to run, so the context changes nothing.
_CONTEXT_EXEMPT = {ClearanceCategory.MUSIC_SYNC}


def use_context_factor(
    element: TriagedElement, use_context: UseContext = UseContext.EXPRESSIVE
) -> float:
    if element.category in _CONTEXT_EXEMPT:
        return 1.0
    return USE_CONTEXT_FACTOR[use_context]


# How the element is portrayed. Brand owners sue over depiction, not presence:
# Wham-O over a Slip 'N Slide gag, In-Sink-Erator over a mangled hand. A
# favourable depiction reads as free advertising and is the one case where a
# rights holder is pleased to be there.
DEPICTION_FACTOR: dict[DepictionTone, float] = {
    DepictionTone.FAVOURABLE: 0.85,
    DepictionTone.NEUTRAL: 1.0,
    DepictionTone.UNFLATTERING: 1.3,
    DepictionTone.DISPARAGING: 1.6,
}

# Copyright is not offended by context: a sync licence is required whether the
# song plays over a wedding or a murder, and the same is true of artwork. Only
# the categories whose claims turn on association are affected.
_DEPICTION_SENSITIVE = {
    ClearanceCategory.TRADEMARK,
    ClearanceCategory.TEXT_ON_SCREEN,
    ClearanceCategory.RIGHT_OF_PUBLICITY,
    ClearanceCategory.LOCATION,
}


def depiction_factor(element: TriagedElement) -> float:
    """1.0 when the scan reported nothing — every prior run is unchanged."""
    if element.depiction is None or element.category not in _DEPICTION_SENSITIVE:
        return 1.0
    return DEPICTION_FACTOR[element.depiction]


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


def prominence_score(element: TriagedElement) -> float:
    p = element.prominence
    return (
        0.4 * min(p.screen_time_s / 10.0, 1.0)
        + 0.3 * p.frame_coverage
        + 0.2 * p.centrality
        + (0.1 if p.plot_integral else 0.0)
    )


def provisional_score(
    element: TriagedElement, use_context: UseContext = UseContext.EXPRESSIVE
) -> int:
    """Risk before anything is known about the rights holder.

    Identical arithmetic to `score_element` with the posture factor pinned at
    its worst case, so it is an upper bound rather than an optimistic guess.
    Two uses: the router escalates materially exposed findings to deep
    research, and the two-phase report can band every finding before a single
    network call returns.
    """
    return min(
        100,
        round(
            100
            * prominence_score(element)
            * CATEGORY_WEIGHT[element.category]
            * use_context_factor(element, use_context)
            * depiction_factor(element)
        ),
    )


def score_element(
    element: TriagedElement,
    research: ResearchResult | None,
    use_context: UseContext = UseContext.EXPRESSIVE,
) -> RiskAssessment:
    p = element.prominence
    screen_time_norm = min(p.screen_time_s / 10.0, 1.0)
    prominence_score_value = prominence_score(element)
    weight = CATEGORY_WEIGHT[element.category]

    # Failing to look is not evidence that there is nothing to find. An
    # incomplete lookup used to map to UNKNOWN and take UNKNOWN's 0.7 factor,
    # so a finding whose research came back empty scored 30% BELOW its own
    # provisional band — and below an identified litigious holder.
    #
    # `provisional_score` deliberately pins posture at its worst case so a band
    # can only fall once research lands. It must fall because something was
    # learned, never because the lookup failed. A successful lookup that
    # identifies a holder without determining posture is a different state and
    # keeps its discount: it found the counterparty.
    if research_is_incomplete(research):
        posture = LicensingPosture.LITIGIOUS
    else:
        posture = research.licensing_posture
    posture_factor = POSTURE_FACTOR[posture]

    context_factor = use_context_factor(element, use_context)
    # Clamped: the factors are multiplicative and a commercial context can push
    # a maximally prominent, litigious finding past the top of the band scale.
    tone_factor = depiction_factor(element)
    score = min(
        100,
        round(
            100 * prominence_score_value * weight * posture_factor * context_factor * tone_factor
        ),
    )

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
            "prominence_score": round(prominence_score_value, 3),
            "category_weight": round(weight, 3),
            "posture_factor": round(posture_factor, 3),
            "use_context_factor": round(context_factor, 3),
            "depiction_factor": round(tone_factor, 3),
        },
        de_minimis=de_minimis,
    )
