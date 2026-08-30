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

Music adds a fourth: it needs TWO licences, from two different holders. The
synchronisation licence covers the composition and comes from the publisher;
the master-use licence covers the recording and comes from the label. Holding
one and shipping on it is the most common music clearance failure there is, so
a song is only COVERED when both halves are held, in territory, in term and in
media.

Deterministic and reproducible, like scoring and territory banding. `as_of`
comes from the caller; this module never reads the clock.
"""

from clearframe.matching import holders_match
from clearframe.models import (
    ClearanceCategory,
    Coverage,
    CoverageStatus,
    LicenceGrant,
    ResearchResult,
    RightsType,
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


def _gaps_for(
    licence: LicenceGrant, territories: list[str], distribution: list[str], as_of: str
) -> list[str]:
    """Territory / media / term gaps on one grant."""
    gaps: list[str] = []
    missing_terr = _covers_territories(licence, territories)
    if missing_terr:
        gaps.append(
            f"territory not granted: {', '.join(missing_terr)} "
            f"(licence covers {', '.join(licence.territories)})"
        )
    missing_media = _covers_media(licence, distribution)
    if missing_media:
        gaps.append(
            f"media not granted: {', '.join(missing_media)} "
            f"(licence covers {', '.join(licence.media)})"
        )
    if _expired(licence, as_of):
        gaps.append(f"licence expired {licence.expires}")
    return gaps


def _grants(licence: LicenceGrant, half: RightsType) -> bool:
    return licence.rights_type in (half, RightsType.BOTH, RightsType.ALL)


def _assess_music(
    element: TriagedElement,
    owner: str,
    matches: list[LicenceGrant],
    territories: list[str],
    distribution: list[str],
    as_of: str,
) -> Coverage:
    """A song is covered only when BOTH halves are held and clean.

    Unlike every other category this cannot be answered by picking the single
    best licence: the two halves routinely come from two different companies on
    two pieces of paper, so coverage is assembled rather than chosen.
    """
    halves = {
        RightsType.SYNC: "synchronisation (composition — publisher)",
        RightsType.MASTER: "master use (recording — label)",
    }
    gaps: list[str] = []
    used: list[str] = []

    for half, description in halves.items():
        candidates = [lic for lic in matches if _grants(lic, half)]
        if not candidates:
            gaps.append(
                f"{description} licence missing — the grants on file do not convey it"
            )
            continue
        scored = sorted(
            ((lic, _gaps_for(lic, territories, distribution, as_of)) for lic in candidates),
            key=lambda pair: len(pair[1]),
        )
        licence, licence_gaps = scored[0]
        used.append(licence.id)
        gaps.extend(f"{description}: {g}" for g in licence_gaps)

    if not gaps:
        return Coverage(
            element_id=element.id,
            status=CoverageStatus.COVERED,
            licence_id=" + ".join(used),
            rights_holder=owner,
            note=(
                "Both halves held: composition and recording are licensed for the "
                f"declared territories and media ({' + '.join(used)})."
            ),
        )
    return Coverage(
        element_id=element.id,
        status=CoverageStatus.PARTIAL,
        licence_id=" + ".join(used),
        rights_holder=owner,
        gaps=gaps,
        note=(
            "A song needs both a synchronisation licence for the composition and a "
            "master-use licence for the recording. One without the other means "
            "shipping an uncleared work."
        ),
    )


def find_licences(owner: str, licences: list[LicenceGrant]) -> list[LicenceGrant]:
    """Every ledger entry whose rights holder matches the researched owner.

    Researched owners are verbose ("The Weeknd XO, Inc. / Universal Music Group
    (master); Universal Music Publishing Group (composition)"), so matching is
    token-overlap — but over IDENTIFYING tokens only. Corporate furniture like
    "Music", "Group" or "Records" is shared by half the industry, and matching
    on it reported a festival-only Kobalt cue licence as covering a Universal
    master. Being wrong in the covered direction is the one failure this module
    must not have.
    """
    return [lic for lic in licences if holders_match(owner, lic.rights_holder)]


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

    if element.category is ClearanceCategory.MUSIC_SYNC:
        return _assess_music(
            element, research.owner, matches, territories, distribution, as_of
        )

    best: Coverage | None = None
    for lic in matches:
        gaps = _gaps_for(lic, territories, distribution, as_of)

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


def _split_multi(value: str) -> list[str]:
    """Ledger CSVs use pipes or semicolons inside a cell — commas are taken."""
    for sep in ("|", ";"):
        if sep in value:
            return [v.strip().upper() for v in value.split(sep) if v.strip()]
    return [value.strip().upper()] if value.strip() else []


def parse_licence_json(raw: str) -> list[LicenceGrant]:
    import json

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}")
    rows = payload.get("licences", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError('Expected a list of licences, or {"licences": [...]}.')
    out: list[LicenceGrant] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row.setdefault("id", "")
        try:
            out.append(LicenceGrant.model_validate(row))
        except Exception:
            continue
    return out


def parse_licence_csv(raw: str) -> list[LicenceGrant]:
    """Parse a clearance department's licence register exported as CSV."""
    import csv
    import io

    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    headers = {(h or "").strip().lower() for h in reader.fieldnames}
    if "rights_holder" not in headers:
        raise ValueError(
            "CSV must contain a 'rights_holder' column. Recognised columns: id, "
            "rights_holder, work, scope, rights_type, territories, media, starts, "
            "expires, reference, notes."
        )
    out: list[LicenceGrant] = []
    for row in reader:
        clean = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        holder = clean.get("rights_holder", "")
        if not holder:
            continue
        expires = clean.get("expires") or None
        try:
            out.append(
                LicenceGrant(
                    id=clean.get("id", ""),
                    rights_holder=holder,
                    work=clean.get("work", ""),
                    scope=clean.get("scope", ""),
                    # A register that does not distinguish is read as granting
                    # everything it names — which is how it was read before.
                    rights_type=(clean.get("rights_type") or "ALL").upper(),
                    territories=_split_multi(clean.get("territories", "")) or ["WORLDWIDE"],
                    media=_split_multi(clean.get("media", "")) or ["ALL"],
                    starts=clean.get("starts", ""),
                    expires=expires,
                    reference=clean.get("reference", ""),
                    notes=clean.get("notes", ""),
                )
            )
        except Exception:
            continue
    return out


def assign_ids(
    parsed: list[LicenceGrant], taken: set[str], prefix: str = "LIC"
) -> list[LicenceGrant]:
    """Give every id-less upload row an id that collides with nothing.

    An uploaded register often has no id column. Numbering those rows by
    position would quietly overwrite existing ledger entries on merge — the
    kind of silent data loss that makes a rights ledger untrustworthy.
    """
    used = set(taken)
    out: list[LicenceGrant] = []
    counter = 1
    for lic in parsed:
        if lic.id:
            out.append(lic)
            used.add(lic.id)
            continue
        while f"{prefix}-{counter:03d}" in used:
            counter += 1
        new_id = f"{prefix}-{counter:03d}"
        used.add(new_id)
        out.append(lic.model_copy(update={"id": new_id}))
    return out
