"""Sponsor conflicts: the risk that has nothing to do with infringement.

Everything else here asks "may we show this?". This asks a different question:
"is showing this going to cost us the brand deal?" Category exclusivity is
standard in sponsorship contracts, so a rival logo in shot can void a fee even
though the depiction is entirely lawful — and no clearance tool would flag it,
because nothing is being infringed.

Deliberately conservative. A false conflict costs the user a real and awkward
conversation with a sponsor, so a mark that is not in the local catalogue is
left alone rather than guessed at. Under-reporting here is cheaper than
crying wolf, which is the opposite of the trade-off everywhere else in this
codebase — and the reason is that the consequence is commercial, not legal.

Pure code, no I/O.
"""

from clearframe.knowledge import KnowledgeBase
from clearframe.models import ClearanceCategory, SponsorConflict, TriagedElement

# Only categories that actually name a brand can conflict with a sponsor.
_BRAND_CATEGORIES = {
    ClearanceCategory.TRADEMARK,
    ClearanceCategory.TEXT_ON_SCREEN,
}


def find_sponsor_conflicts(
    elements: list[TriagedElement],
    sponsors: list[str],
    knowledge: KnowledgeBase,
) -> list[SponsorConflict]:
    """Marks on screen that compete with a paying sponsor, same sector."""
    if not sponsors:
        return []

    resolved = []
    for name in sponsors:
        mark = knowledge.find_mark(name)
        if mark is not None and mark.sector:
            resolved.append((name, mark))
    if not resolved:
        return []

    conflicts: list[SponsorConflict] = []
    for el in elements:
        if el.category not in _BRAND_CATEGORIES:
            continue
        found = knowledge.find_mark(el.label)
        if found is None or not found.sector:
            continue
        for sponsor_name, sponsor_mark in resolved:
            if found.sector != sponsor_mark.sector:
                continue
            # A sibling brand of the same parent is the sponsor's own house.
            if found.parent == sponsor_mark.parent or found.owner == sponsor_mark.owner:
                continue
            conflicts.append(
                SponsorConflict(
                    element_id=el.id,
                    label=el.label,
                    detected_owner=found.owner,
                    conflicts_with=sponsor_name,
                    sector=found.sector,
                    note=(
                        f"'{el.label}' ({found.owner}) is a {found.sector} competitor of "
                        f"sponsor {sponsor_name} ({sponsor_mark.owner}). Category "
                        f"exclusivity is standard in sponsorship contracts, so this may "
                        f"breach the deal even though the depiction itself is lawful. "
                        f"Check the exclusivity clause before delivery."
                    ),
                )
            )
            break  # one conflict per element is enough to act on
    return conflicts
