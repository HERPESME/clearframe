"""The document furniture a clearance memo needs, computed once.

The report ships in two formats now — HTML to read and DOCX to file — and the
cover page, the reference number and the status have to be the same in both. Two
renderers computing them separately is exactly how they drift, so they are
computed here and each renderer only lays them out.

None of this is decoration. A clearance report is a document that gets attached
to an E&O application and read months later by somebody who was not in the room:
it has to say which cut was reviewed, who prepared it, when, against which
territories, and whether anyone has signed it off yet.
"""

from __future__ import annotations

CONFIDENTIALITY = (
    "CONFIDENTIAL — PREPARED FOR RIGHTS CLEARANCE PURPOSES. "
    "This report and its attachments are confidential to the production named "
    "below and its advisers. It is not for circulation."
)

PREPARED_BY = "ClearFrame — automated rights-clearance pipeline"


def reference(production) -> str:
    """A quotable identifier for this report.

    Derived from the production id rather than a counter, so the same production
    always yields the same reference and two reports on one film can be told
    apart by their version rather than by guessing from a date.
    """
    slug = "".join(c for c in production.id if c.isalnum()).upper()[:10] or "UNKNOWN"
    return f"CF-{slug}"


def status(dossier) -> str:
    """Draft until every finding carries a decision.

    A report where half the findings are still pending is a working document,
    and saying so on the cover is the difference between a draft somebody
    circulated and a clearance opinion somebody relied on. `DossierStage` will
    not build one at all with decisions outstanding, so in practice this reads
    FINAL — but the CLI and the MCP server can render a dossier object directly,
    and a draft must not present itself as finished.
    """
    if not dossier.entries:
        return "DRAFT — no findings assessed"
    undecided = sum(1 for e in dossier.entries if e.decision is None)
    if undecided:
        return f"DRAFT — {undecided} of {len(dossier.entries)} findings undecided"
    return "FINAL — every finding reviewed and signed off"


def signatories(dossier) -> list[str]:
    """Who actually recorded the decisions in this report.

    Read off the decisions rather than left as blank lines to sign, because the
    audit trail already knows: `Decision.reviewer` is a verified email since the
    role word ("legal") stopped standing in for a person. An unverified address
    carries its own marker, which is applied where the email is built, not here.
    """
    seen: list[str] = []
    for entry in dossier.entries:
        if entry.decision is None:
            continue
        who = f"{entry.decision.reviewer} ({entry.decision.role})"
        if who not in seen:
            seen.append(who)
    return seen


def control_rows(dossier) -> list[tuple[str, str]]:
    """The document-control block, in the order it should be read.

    `media_version` is in here deliberately. It is the only thing that says
    WHICH CUT was reviewed — a re-upload at the same production id is a
    different film, which is the failure the browser cache, the box cache and
    the ground store have each had to learn separately. A clearance report that
    cannot name the footage it looked at is not evidence of anything.
    """
    p = dossier.production
    return [
        ("Report reference", reference(p)),
        ("Status", status(dossier)),
        ("Production", p.title),
        ("Footage under review", p.footage_uri or "—"),
        ("Footage identifier", getattr(p, "media_version", None) or "—"),
        ("Running time", f"{p.duration_s:.2f}s at {p.fps:g} fps"),
        ("Territories assessed", ", ".join(dossier.territories) or "US"),
        ("Use context", dossier.use_context.value),
        ("Distribution platform", (p.platform or "none")),
        ("Prepared by", PREPARED_BY),
        ("Generated", dossier.generated_at),
        ("Findings", str(len(dossier.entries))),
    ]


def summary_rows(dossier) -> list[tuple[str, str]]:
    """The counts a reader needs before any individual finding.

    Only the keys that are present, so a report never shows a row of zeroes for
    a feature that did not run — an empty coverage column reads as "nothing is
    licensed" rather than "the ledger was not consulted".
    """
    s = dossier.summary
    labels = [
        ("CRITICAL", "Critical risk"),
        ("HIGH", "High risk"),
        ("MEDIUM", "Medium risk"),
        ("LOW", "Low risk"),
        ("incomplete_research", "Research incomplete"),
        ("pending_decisions", "Awaiting decision"),
        ("identity_corroborated", "Identity corroborated"),
        ("identity_conflicts", "Identity disputed"),
        ("material_freshness_signals", "Live enforcement signals"),
        ("coverage_covered", "Already licensed"),
        ("coverage_partial", "Partially licensed"),
        ("coverage_not_covered", "Not licensed"),
    ]
    return [(label, str(s[key])) for key, label in labels if key in s]
