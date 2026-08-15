"""Shared review service: decision recording and dossier generation.

Single owner of the review rules (role gating, review reopening, append-only
audit trail) so the web API, the MCP server, and any future transport behave
identically. Timestamps (`at`) come from the caller — this module never reads
the clock.
"""

import asyncio
from pathlib import Path

from clearframe.models import AuditEvent, Decision, ProductionState
from clearframe.pipeline import demo_context
from clearframe.stages.dossier import DossierStage
from clearframe.store import LocalJsonStore

DECIDER_ROLES = {"legal", "producer"}

VALID_ACTIONS = {"approve_risk", "license", "blur", "reshoot", "escalate"}


class RoleNotPermittedError(Exception):
    """The role cannot record decisions (requires legal or producer)."""


class UnknownElementError(Exception):
    """The element id does not exist in this production."""


def record_decision(
    store: LocalJsonStore,
    production_id: str,
    element_id: str,
    action: str,
    note: str,
    *,
    role: str,
    reviewer: str,
    at: str,
) -> ProductionState:
    role = role.lower()
    if role not in DECIDER_ROLES:
        raise RoleNotPermittedError(
            f"Role '{role}' cannot record decisions (requires legal or producer)."
        )
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown action '{action}' (one of {sorted(VALID_ACTIONS)}).")
    state = store.load(production_id)
    if not any(el.id == element_id for el in state.elements):
        raise UnknownElementError(f"Unknown element: {element_id}")

    state.decisions[element_id] = Decision(
        element_id=element_id, action=action, reviewer=reviewer, role=role, note=note
    )
    if state.stage_status.get("review") == "complete":
        # A revised decision invalidates the generated dossier.
        state.stage_status["review"] = "awaiting"
    state.audit_log.append(
        AuditEvent(
            at=at,
            actor=reviewer,
            role=role,
            event="decision",
            detail=f"{element_id}:{action}" + (f" — {note}" if note else ""),
        )
    )
    store.save(state)
    return state


async def generate_dossier_async(
    store: LocalJsonStore, out_root: Path, production_id: str, *, at: str
) -> list[str]:
    """Run the dossier stage over reviewed state; returns artifact names.

    Raises ReviewPendingError (from DossierStage) when decisions are missing.
    """
    out_root = Path(out_root)
    state = store.load(production_id)
    ctx = demo_context(out_root)
    ctx.store = store
    ctx.state = state
    await DossierStage(out_dir=out_root, generated_at=at).run(ctx)
    state.audit_log.append(
        AuditEvent(at=at, actor="system", role="system", event="dossier_generated", detail="")
    )
    store.save(state)
    return [p.name for p in sorted(out_root.iterdir()) if p.is_file()]


def generate_dossier_for(
    store: LocalJsonStore, out_root: Path, production_id: str, *, at: str
) -> list[str]:
    """Sync wrapper for non-async callers (CLI, sync tests)."""
    return asyncio.run(generate_dossier_async(store, out_root, production_id, at=at))
