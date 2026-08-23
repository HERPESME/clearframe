"""What it costs to ignore a finding — not what it costs to clear it.

Everything else here prices doing the right thing: a licence fee, a blur. This
prices the other branch, and the case law says that branch is not mostly about
damages.

Woods did not win a damages award against 12 Monkeys. He won a preliminary
INJUNCTION against a film already in theatres, and let distribution continue
for a high six-figure settlement. Whitmill was DENIED an injunction over the
Hangover II tattoo and Warner Bros. settled anyway, weeks before opening,
because a release date is not negotiable and a trial is. Hart settled and
Warner paid to digitally alter the sculpture for home video.

None of those costs are a judgment. They are delay, leverage and rework — and
they are why "you would probably win" is worthless advice to a producer.

Three deliberate refusals:

* No single "expected liability" figure. That is pseudo-precision an
  underwriter would see through in a sentence.
* No statutory damages quoted outside copyright. §504(c) is a COPYRIGHT
  remedy; attaching $150,000 to a logo would be a scary number that is simply
  false.
* No injunction risk asserted without a case behind it. It reads from
  `litigation.json`, and says "no precedent on file" when there is none.

Pure code, no I/O beyond the knowledge base.
"""

from clearframe.knowledge import KnowledgeBase
from clearframe.models import (
    ClearanceCategory,
    LiabilityEstimate,
    RemediationOption,
    ResearchResult,
    TriagedElement,
)

# 17 U.S.C. §504(c). A statutory range, not an estimate — the court picks
# within it, and the plaintiff does not have to prove a loss to get it.
STATUTORY_MIN = 750
STATUTORY_MAX = 30_000
STATUTORY_WILLFUL = 150_000

_STATUTORY_CATEGORIES = {
    ClearanceCategory.COPYRIGHT_ART,
    ClearanceCategory.MUSIC_SYNC,
}

# What the remedy actually is where §504(c) does not reach.
_OTHER_REMEDY: dict[ClearanceCategory, str] = {
    ClearanceCategory.TRADEMARK: (
        "No statutory damages for depiction — 15 U.S.C. §1117 gives the holder "
        "your profits, their damages and, in exceptional cases, their legal "
        "fees. The realistic exposure is the cost of defending, not a fixed sum."
    ),
    ClearanceCategory.TEXT_ON_SCREEN: (
        "No statutory damages for depiction — 15 U.S.C. §1117 gives profits, "
        "damages and possibly fees."
    ),
    ClearanceCategory.RIGHT_OF_PUBLICITY: (
        "State law, and it varies widely. Some states set statutory minimums "
        "(California Civil Code §3344 sets $750); most award actual damages "
        "plus profits. There is no federal figure to quote."
    ),
    ClearanceCategory.LOCATION: (
        "Contract, not statute. The exposure is breach of the location "
        "agreement or a trespass claim, measured by the agreement itself."
    ),
}


def _injunction(category: ClearanceCategory, knowledge: KnowledgeBase) -> tuple[str, str]:
    """Can a claim in this category stop a release? Answered from the record."""
    cases = knowledge.cases_for(category.value)
    granted = [c for c in cases if c.injunction in ("granted", "sought")]
    if granted:
        worst = granted[0]
        return (
            "documented",
            f"{worst.name} ({worst.citation}) — {worst.holding} "
            "An injunction stops distribution regardless of what damages would "
            "eventually be awarded, which is why these settle.",
        )
    denied = [c for c in cases if c.injunction == "sought_denied"]
    if denied:
        return (
            "sought and denied",
            f"Injunctions have been sought and refused in this category "
            f"({', '.join(c.name for c in denied[:2])}). The claim still had to "
            "be defended, which is its own cost.",
        )
    return (
        "no precedent on file",
        "No injunction precedent recorded for this category. That is an absence "
        "of evidence, not a safe harbour.",
    )


def _fix_line(element: TriagedElement, fix: str | None) -> str:
    """You do not VFX paint-out a song. The fix depends on what it is."""
    if element.category is ClearanceCategory.MUSIC_SYNC:
        return (
            f"Replace or mute the cue at picture lock — {fix}."
            if fix
            else "Replace or mute the cue at picture lock, and re-conform the mix."
        )
    if fix:
        return f"Fix it at picture lock — {fix}, per shot, after the cut is conformed."
    return "Fix it at picture lock — a VFX paint-out, priced per shot."


def estimate(
    element: TriagedElement,
    research: ResearchResult | None,
    remediation: list[RemediationOption],
    knowledge: KnowledgeBase,
) -> LiabilityEstimate:
    """Price the three moments: clear it now, fix it at lock, find it at delivery."""
    clear_now = research.estimated_license_cost_band if research else None
    fix = next(
        (o.est_cost_band for o in remediation if o.kind in ("blur", "reshoot") and o.est_cost_band),
        None,
    )

    statutory = element.category in _STATUTORY_CATEGORIES
    basis = (
        f"17 U.S.C. §504(c) — the copyright owner may elect statutory damages of "
        f"${STATUTORY_MIN:,} to ${STATUTORY_MAX:,} per work, rising to "
        f"${STATUTORY_WILLFUL:,} if the infringement is found wilful. No proof of "
        "actual loss is required."
        if statutory
        else _OTHER_REMEDY.get(element.category, "Remedy depends on the claim.")
    )

    risk, risk_basis = _injunction(element.category, knowledge)

    escalation = [
        f"Clear it now — {clear_now}." if clear_now
        else "Clear it now — cost not established; the rights holder has not been priced.",
        _fix_line(element, fix),
        (
            "Find it at delivery — you negotiate with zero leverage against a fixed "
            "release date, which is the position every settlement in the record was "
            "made from."
        ),
    ]

    if statutory:
        headline = (
            f"Shipping this uncleared exposes you to ${STATUTORY_MIN:,}–"
            f"${STATUTORY_WILLFUL:,} per work in statutory damages, and a claim in "
            f"this category has stopped a release before."
            if risk == "documented"
            else f"Shipping this uncleared exposes you to ${STATUTORY_MIN:,}–"
            f"${STATUTORY_WILLFUL:,} per work in statutory damages."
        )
    else:
        headline = (
            "Holders in this category usually lose on the merits, but the claim "
            "still has to be defended — and defence costs more than clearance."
        )

    return LiabilityEstimate(
        element_id=element.id,
        headline=headline,
        clear_now=clear_now,
        fix_in_post=fix,
        statutory_min_usd=STATUTORY_MIN if statutory else None,
        statutory_max_usd=STATUTORY_MAX if statutory else None,
        statutory_willful_usd=STATUTORY_WILLFUL if statutory else None,
        statutory_basis=basis,
        injunction_risk=risk,
        injunction_basis=risk_basis,
        escalation=escalation,
    )
