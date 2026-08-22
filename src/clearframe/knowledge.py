"""Local rights knowledge: ownership, precedent, counterparties, term rules.

Four datasets under `data/rights/`, loaded once and queried in microseconds.
They exist to answer the questions that do NOT need the open web:

  known_marks.json    who owns a mark. A corporate fact that does not change
                      between pipeline runs, so paying for it every run was
                      pure waste.
  litigation.json     what actually happened when productions showed someone
                      else's IP. Makes licensing posture a cited fact.
  rightsholders.json  publishers, labels, stock agencies, collecting societies.
  public_domain.json  US term rules as data, with the authority for each.

The deliberate omission is posture. Ownership is a lookup; posture is live
information — whether a holder is suing people this quarter is exactly what a
static table cannot know. So posture is asserted only where a documented,
citable action exists, and is otherwise left UNKNOWN so the router escalates
to a live Parallel Search. A table that guessed at posture would be the same
failure mode as a model guessing at a song title.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from clearframe.matching import labels_match, tokens
from clearframe.models import LicensingPosture

DATA_DIR = Path(__file__).parent / "data" / "rights"


@dataclass(frozen=True)
class Mark:
    label: str
    owner: str
    parent: str
    aliases: tuple[str, ...]
    sector: str
    posture: LicensingPosture
    posture_evidence: str

    @property
    def has_cited_posture(self) -> bool:
        return self.posture is not LicensingPosture.UNKNOWN and bool(self.posture_evidence)


@dataclass(frozen=True)
class Case:
    name: str
    citation: str
    year: int
    category: str
    prevailing: str
    fact_pattern: str
    holding: str
    lesson: str
    url: str


@dataclass(frozen=True)
class Holder:
    name: str
    kind: str
    posture: LicensingPosture
    note: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeBase:
    marks: tuple[Mark, ...]
    cases: tuple[Case, ...]
    holders: tuple[Holder, ...]
    term_rules: dict[str, int | None]
    term_authority: dict[str, str]
    verified_on: str = ""
    _index: dict[str, Mark] = field(default_factory=dict, compare=False)

    # ------------------------------------------------------------------ marks
    def find_mark(self, label: str) -> Mark | None:
        """Match a noisy on-screen label ("Coca-Cola can") to a catalogued mark.

        Exact token hit first — a label that CONTAINS a known mark name is the
        common case. Falls back to the same token-overlap rule that governs
        drift and corroboration, so one matching policy covers the codebase.
        """
        label_tokens = set(tokens(label))
        if not label_tokens:
            return None
        for key, mark in self._index.items():
            key_tokens = set(tokens(key))
            if key_tokens and key_tokens <= label_tokens:
                return mark
        for mark in self.marks:
            if labels_match(label, mark.label):
                return mark
            if any(labels_match(label, alias) for alias in mark.aliases):
                return mark
        return None

    # ---------------------------------------------------------------- holders
    def find_holder(self, name: str) -> Holder | None:
        if not name:
            return None
        for holder in self.holders:
            if labels_match(name, holder.name):
                return holder
            if any(labels_match(name, alias) for alias in holder.aliases):
                return holder
        return None

    # ------------------------------------------------------------------ cases
    def cases_for(self, category: str) -> tuple[Case, ...]:
        return tuple(c for c in self.cases if c.category == category)

    # ------------------------------------------------------------------- term
    def public_domain_through(self, kind: str) -> int | None:
        return self.term_rules.get(kind)

    def term_authority_for(self, kind: str) -> str:
        return self.term_authority.get(kind, "")


def _posture(raw: str) -> LicensingPosture:
    try:
        return LicensingPosture(raw)
    except ValueError:
        return LicensingPosture.UNKNOWN


@lru_cache(maxsize=1)
def load_knowledge(data_dir: str | None = None) -> KnowledgeBase:
    base = Path(data_dir) if data_dir else DATA_DIR

    marks_doc = json.loads((base / "known_marks.json").read_text())
    marks = tuple(
        Mark(
            label=m["label"],
            owner=m["owner"],
            parent=m.get("parent") or m["owner"],
            aliases=tuple(m.get("aliases") or ()),
            sector=m.get("sector", ""),
            posture=_posture(m.get("posture", "unknown")),
            posture_evidence=m.get("posture_evidence", ""),
        )
        for m in marks_doc["marks"]
    )

    cases_doc = json.loads((base / "litigation.json").read_text())
    cases = tuple(Case(**c) for c in cases_doc["cases"])

    holders_doc = json.loads((base / "rightsholders.json").read_text())
    holders = tuple(
        Holder(
            name=h["name"],
            kind=h["kind"],
            posture=_posture(h["posture"]),
            note=h["note"],
            aliases=tuple(h.get("aliases") or ()),
        )
        for h in holders_doc["holders"]
    )

    pd_doc = json.loads((base / "public_domain.json").read_text())
    term_rules = {r["kind"]: r["public_domain_through_year"] for r in pd_doc["rules"]}
    term_authority = {r["kind"]: r["authority"] for r in pd_doc["rules"]}

    # Longest names first so "Louis Vuitton" wins over a bare "vuitton" alias.
    index: dict[str, Mark] = {}
    for mark in marks:
        for key in (mark.label, *mark.aliases):
            index.setdefault(key, mark)
    ordered = dict(sorted(index.items(), key=lambda kv: -len(tokens(kv[0]))))

    return KnowledgeBase(
        marks=marks,
        cases=cases,
        holders=holders,
        term_rules=term_rules,
        term_authority=term_authority,
        verified_on=marks_doc.get("verified_on", ""),
        _index=ordered,
    )
