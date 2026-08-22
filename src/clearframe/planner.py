"""Research Budget Planner: allocates Parallel processor tiers per element.

Deterministic policy with recorded rationale — the agentic behavior is
resource allocation with visible reasoning, not an LLM roll of the dice.
(A Gemini-backed planner for novel cases is a live-mode upgrade; the policy
below is the auditable floor.)

Cost figures are indicative, used for the spend summary shown to producers.
"""

from clearframe.models import ClearanceCategory, ResearchPlan, TriagedElement

# Parallel Task API list price per completed run (docs.parallel.ai/getting-started/pricing,
# checked 2026-08-22). Keep these in step with the published table: the
# producer-facing budget summary is only useful if it is true.
EST_COST: dict[str, float] = {"lite": 0.005, "base": 0.010, "pro": 0.100, "ultra": 0.300}

# Parallel Search API, priced per request rather than per run — this is what
# makes the real-time freshness pass affordable at review time.
SEARCH_COST_USD: float = 0.005

FAMOUS_MARKS = {
    "coca-cola",
    "coke",
    "nike",
    "adidas",
    "apple",
    "pepsi",
    "mcdonald",
    "starbucks",
    "disney",
    "samsung",
    "google",
    "toyota",
    "gucci",
}


def _plan_one(el: TriagedElement) -> ResearchPlan:
    label = el.label.casefold()
    if el.category == ClearanceCategory.MUSIC_SYNC:
        processor, rationale = (
            "pro",
            "Music rights split across composition and master with publisher chains; needs deep research.",
        )
    elif el.category == ClearanceCategory.COPYRIGHT_ART and "unknown" in label:
        processor, rationale = (
            "ultra",
            "Unidentified artist: exhaustive open-web dig (registries, street-art databases, local press) required.",
        )
    elif el.category == ClearanceCategory.TRADEMARK and any(
        mark in label for mark in FAMOUS_MARKS
    ):
        processor, rationale = (
            "lite",
            "Famous mark: ownership is trivial; only posture/contact needs confirming.",
        )
    else:
        processor, rationale = (
            "base",
            "Standard single-owner lookup expected; escalate tier manually if research returns incomplete.",
        )
    return ResearchPlan(
        element_id=el.id,
        processor=processor,
        rationale=rationale,
        est_cost_usd=EST_COST[processor],
    )


def plan_research(elements: list[TriagedElement]) -> dict[str, ResearchPlan]:
    return {el.id: _plan_one(el) for el in elements}
