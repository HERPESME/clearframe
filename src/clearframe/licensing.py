"""Rights ledger: match findings against clearances the production already holds.

Everything else in ClearFrame answers "who owns this and what would it cost".
A director's first question is the opposite one: *am I already covered?* Without
a ledger, a clearance report re-prices rights the production bought years ago
and stays silent about the gaps in the ones it did buy.

Three gaps sink real productions, and all three are checked here:

  territory  a US-only sync licence on a film releasing in France
  term       a licence that expired before delivery
  media      the WKRP in Cincinnati problem — music cleared for broadcast and
             never for home video, so the show shipped with its soundtrack gutted

Deterministic and reproducible, like scoring and territory banding. `as_of`
comes from the caller; this module never reads the clock.
"""

from clearframe.matching import labels_match
from clearframe.models import (
    Coverage,
    CoverageStatus,
    LicenceGrant,
    ResearchResult,
    TriagedElement,
    research_is_incomplete,
)

WORLDWIDE = "WORLDWIDE"
ALL_MEDIA = "ALL"


def _covers_territories(licence: LicenceGrant, needed: list[str]) -> list[str]:
    granted = {t.upper() for t in licence.territories}
    if WORLDWIDE in granted:
        return []
    return [t for t in needed if t.upper() not in granted]


def _covers_media(licence: LicenceGrant, needed: list[str]) -> list[str]:
    granted = {m.upper() for m in licence.media}
    if ALL_MEDIA in granted:
        return []
    return [m for m in needed if m.upper() not in granted]


def _expired(licence: LicenceGrant, as_of: str) -> bool:
    """Date-only ISO comparison; both sides are ISO-8601 so string order works."""
    if not licence.expires:
        return False
    return licence.expires[:10] < as_of[:10]


def find_licences(owner: str, licences: list[LicenceGrant]) -> list[LicenceGrant]:
    """Every ledger entry whose rights holder matches the researched owner.

    Researched owners are verbose ("The Weeknd XO, Inc. / Universal Music Group
    (master); Universal Music Publishing Group (composition)"), so matching is
    the same token-overlap rule used for script drift and corroboration.
    """
    return [lic for lic in licences if labels_match(owner, lic.rights_holder)]


def assess(
    element: TriagedElement,
    research: ResearchResult | None,
    licences: list[LicenceGrant],
    territories: list[str],
    distribution: list[str],
    as_of: str,
) -> Coverage:
    if research_is_incomplete(research) or not research.owner:
        return Coverage(
            element_id=element.id,
            status=CoverageStatus.UNKNOWN,
            note=(
                "Rights holder is not established, so the ledger cannot be checked. "
                "Coverage is unknowable until identity and ownership are resolved."
            ),
        )

    matches = find_licences(research.owner, licences)
    if not matches:
        return Coverage(
            element_id=element.id,
            status=CoverageStatus.NOT_COVERED,
            rights_holder=research.owner,
            note=(
                f"No licence on file from {research.owner}. This use is unlicensed "
                "unless a defence applies."
            ),
        )

    best: Coverage | None = None
    for lic in matches:
        gaps: list[str] = []
        missing_terr = _covers_territories(lic, territories)
        if missing_terr:
            gaps.append(
                f"territory not granted: {', '.join(missing_terr)} "
                f"(licence covers {', '.join(lic.territories)})"
            )
        missing_media = _covers_media(lic, distribution)
        if missing_media:
            gaps.append(
                f"media not granted: {', '.join(missing_media)} "
                f"(licence covers {', '.join(lic.media)})"
            )
        if _expired(lic, as_of):
            gaps.append(f"licence expired {lic.expires}")

        candidate = Coverage(
            element_id=element.id,
            status=CoverageStatus.COVERED if not gaps else CoverageStatus.PARTIAL,
            licence_id=lic.id,
            rights_holder=lic.rights_holder,
            gaps=gaps,
            note=(
                f"Covered by {lic.id} ({lic.scope or 'licence'}) from {lic.rights_holder}."
                if not gaps
                else (
                    f"{lic.id} from {lic.rights_holder} does not reach this use. "
                    "Extend the grant or treat the finding as uncleared."
                )
            ),
        )
        # A clean licence wins outright; otherwise keep the one with fewest gaps.
        if candidate.status is CoverageStatus.COVERED:
            return candidate
        if best is None or len(candidate.gaps) < len(best.gaps):
            best = candidate
    return best  # type: ignore[return-value]


def assess_all(
    elements: list[TriagedElement],
    research: dict[str, ResearchResult],
    licences: list[LicenceGrant],
    territories: list[str],
    distribution: list[str],
    as_of: str,
) -> dict[str, Coverage]:
    return {
        el.id: assess(
            el, research.get(el.id), licences, territories, distribution, as_of
        )
        for el in elements
    }


def summarise(coverage: dict[str, Coverage]) -> dict[str, int]:
    counts = {s.value: 0 for s in CoverageStatus}
    for c in coverage.values():
        counts[c.status.value] += 1
    return counts
