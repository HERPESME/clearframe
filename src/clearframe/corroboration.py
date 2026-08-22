"""Identity corroboration: does a second, independent detector agree WHAT this is?

The E&O auditor stage is Gemini reviewing Gemini. Two passes of the same model
share the same priors, so the auditor reliably catches *omissions* and
unreliably catches *misidentifications*. Misidentification is the more
dangerous failure: a wrong brand name routes rights research to the wrong
company and produces a dossier certifying a clearance that was never obtained.

So identity gets a second opinion from a detector of a different kind — a
closed-vocabulary logo/OCR detector that cannot invent a brand outside its
catalogue. The three verdicts drive real behaviour downstream:

  CORROBORATED   two independent detectors named the same thing -> research it
  SINGLE_SOURCE  only the generative pass saw it (murals, tattoos, artwork the
                 catalogue cannot know) -> research it, but say so in the dossier
  CONFLICTED     the detectors named DIFFERENT things -> never auto-research;
                 a human resolves identity first

Deterministic and reproducible, like the rest of the scoring path.
"""

from clearframe.matching import labels_match
from clearframe.models import (
    ClearanceCategory,
    Corroboration,
    DetectorHit,
    IdentityVerdict,
    TriagedElement,
)

# Categories a closed-vocabulary logo/text detector can legitimately speak to.
# A street mural or a tattoo is outside any brand catalogue, so silence there is
# not evidence of absence and must not read as a conflict.
CORROBORATABLE = {ClearanceCategory.TRADEMARK, ClearanceCategory.TEXT_ON_SCREEN}

MIN_CONFIDENCE = 0.5


def _overlaps(element: TriagedElement, hit: DetectorHit) -> bool:
    """Does the hit fall inside any window where the element appears?"""
    if hit.start_s is None or hit.end_s is None:
        return True  # untimed hit (still frame) — treat as in-scope
    return any(
        hit.start_s < r.end_s and hit.end_s > r.start_s for r in element.time_ranges
    )


def assess(
    element: TriagedElement, hits: list[DetectorHit], detector: str
) -> Corroboration:
    if element.category not in CORROBORATABLE:
        return Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.SINGLE_SOURCE,
            detector=detector,
            detected_label=None,
            confidence=0.0,
            note=(
                f"No closed-vocabulary detector covers {element.category.value}; "
                "identity rests on the video model alone."
            ),
        )

    in_scope = [
        h for h in hits if h.confidence >= MIN_CONFIDENCE and _overlaps(element, h)
    ]
    agreeing = [h for h in in_scope if labels_match(element.label, h.label)]

    if agreeing:
        best = max(agreeing, key=lambda h: h.confidence)
        return Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.CORROBORATED,
            detector=detector,
            detected_label=best.label,
            confidence=best.confidence,
            note=(
                f"{detector} independently identified '{best.label}' in the same window "
                f"at {best.confidence:.0%} confidence."
            ),
        )

    if in_scope:
        best = max(in_scope, key=lambda h: h.confidence)
        others = ", ".join(sorted({h.label for h in in_scope}))
        return Corroboration(
            element_id=element.id,
            verdict=IdentityVerdict.CONFLICTED,
            detector=detector,
            detected_label=best.label,
            confidence=best.confidence,
            note=(
                f"Identity dispute: the video model read '{element.label}' but {detector} "
                f"read '{others}' in the same window. Resolve before researching — "
                "researching the wrong rights holder produces a false clearance."
            ),
        )

    return Corroboration(
        element_id=element.id,
        verdict=IdentityVerdict.SINGLE_SOURCE,
        detector=detector,
        detected_label=None,
        confidence=0.0,
        note=(
            f"{detector} saw no catalogued mark in this window. Not a contradiction — "
            "the mark may simply be outside its vocabulary — but identity is unconfirmed."
        ),
    )


def blocks_research(corroboration: Corroboration | None) -> bool:
    """CONFLICTED identity must not be researched automatically."""
    return corroboration is not None and corroboration.verdict is IdentityVerdict.CONFLICTED
