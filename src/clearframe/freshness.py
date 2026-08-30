"""Freshness: is this rights holder acting *right now*?

Deep research (Parallel Task API) is a snapshot taken when the pipeline ran.
Clearance decisions get made days or weeks later, and the fact that matters
most to a producer — "did this company start suing people since we researched
them?" — is exactly the fact a snapshot cannot contain.

The Parallel Search API answers it in one round trip at cents per call, which
is cheap enough to run while a reviewer is looking at the card. Materiality is
decided in pure code so the flag is reproducible from the stored excerpt.
"""

from clearframe.models import FreshnessSignal, WebFinding

# Language that distinguishes an enforcement event from ordinary brand news.
_MATERIAL_TERMS = (
    "lawsuit",
    "sues",
    "sued",
    "suing",
    "infringement",
    "infringe",
    "cease and desist",
    "cease-and-desist",
    "injunction",
    "settlement",
    "settled",
    "damages",
    "litigation",
    "files suit",
    "filed suit",
    "takedown",
    "enforcement",
    "counterfeit",
    "trademark dispute",
    "copyright claim",
)


def is_material(finding: WebFinding) -> bool:
    """True when the result reads as an enforcement event, not general coverage."""
    haystack = f"{finding.title} {finding.excerpt}".casefold()
    return any(term in haystack for term in _MATERIAL_TERMS)


def to_signals(
    element_id: str, owner: str, findings: list[WebFinding]
) -> list[FreshnessSignal]:
    return [
        FreshnessSignal(
            element_id=element_id,
            owner=owner,
            title=f.title,
            url=f.url,
            excerpt=f.excerpt,
            material=is_material(f),
        )
        for f in findings
    ]


def material_count(signals: list[FreshnessSignal]) -> int:
    return sum(1 for s in signals if s.material)
