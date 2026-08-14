"""Deterministic remediation drafting: license outreach, blur, reshoot, fair-use memo."""

from clearframe.models import (
    ClearanceCategory,
    Production,
    RemediationOption,
    ResearchResult,
    RiskAssessment,
    RiskBand,
    TriagedElement,
)
from clearframe.timecode import seconds_to_tc

_LICENSE_EMAIL = """To: {contact}
Subject: License request — "{label}" appearing in "{production}"

Dear rights holder,

We are producing "{production}", an independent film currently in post-production.
Your property "{label}" appears in our footage at timecode {tc_in}-{tc_out}
({usage}). We would like to license this use for worldwide distribution across
all media, in perpetuity.

Research indicates a typical license range of {cost_band}. Could you confirm
availability, terms, and your quote for this use?

We are happy to provide the relevant footage excerpt for review.

Kind regards,
"{production}" clearance team
"""

_FAIR_USE_MEMO = (
    "De-minimis use memo — {label}: the element appears for {screen_time:.1f}s, "
    "covers under 5% of frame, is not a focal point of the composition, and is not "
    "integral to the plot. Under the de-minimis doctrine (see e.g. Sandoval v. New "
    "Line Cinema, 147 F.3d 215 (2d Cir. 1998)), fleeting and incidental background "
    "appearances of this kind are generally non-actionable. Recommend counsel "
    "confirmation before relying on this position."
)


def draft_options(
    element: TriagedElement,
    research: ResearchResult,
    risk: RiskAssessment,
    production: Production,
) -> list[RemediationOption]:
    options: list[RemediationOption] = []
    first = element.time_ranges[0]
    tc_in = seconds_to_tc(first.start_s, fps=production.fps)
    tc_out = seconds_to_tc(first.end_s, fps=production.fps)

    contact = research.licensing_contact
    if contact or element.category == ClearanceCategory.MUSIC_SYNC:
        detail = _LICENSE_EMAIL.format(
            contact=contact or "[no contact found — escalate to music supervisor]",
            label=element.label,
            production=production.title,
            tc_in=tc_in,
            tc_out=tc_out,
            usage=element.description or "on-screen appearance",
            cost_band=research.estimated_license_cost_band or "unknown",
        )
        options.append(
            RemediationOption(
                kind="license",
                summary=f"License from {research.owner or 'rights holder (unidentified)'}",
                detail=detail,
                est_cost_band=research.estimated_license_cost_band,
            )
        )

    if element.category != ClearanceCategory.MUSIC_SYNC:
        cost = (
            "$300-$800/shot" if element.prominence.frame_coverage < 0.1 else "$800-$2500/shot"
        )
        options.append(
            RemediationOption(
                kind="blur",
                summary="VFX blur / digital replacement in post",
                detail=(
                    f"Blur or digitally replace '{element.label}' in "
                    f"{len(element.time_ranges)} shot(s), {tc_in}-{tc_out}. "
                    f"Estimated VFX cost {cost} at {element.prominence.frame_coverage:.0%} "
                    "frame coverage."
                ),
                est_cost_band=cost,
            )
        )

    if risk.band == RiskBand.CRITICAL:
        options.append(
            RemediationOption(
                kind="reshoot",
                summary="Reshoot / reframe the affected scene",
                detail=(
                    f"Risk is CRITICAL (score {risk.score}). If licensing fails, plan a "
                    f"reshoot of the scene at {tc_in} without '{element.label}'."
                ),
                est_cost_band=None,
            )
        )

    if risk.de_minimis:
        options.append(
            RemediationOption(
                kind="fair_use_memo",
                summary="De-minimis / incidental use position",
                detail=_FAIR_USE_MEMO.format(
                    label=element.label, screen_time=element.prominence.screen_time_s
                ),
                est_cost_band=None,
            )
        )

    return options
