"""Shared review service: decision recording and dossier generation.

Single owner of the review rules (role gating, review reopening, append-only
audit trail) so the web API, the MCP server, and any future transport behave
identically. Timestamps (`at`) come from the caller — this module never reads
the clock.
"""

import asyncio
import os
from pathlib import Path

from clearframe.config import ClearFrameConfig
from clearframe.models import AuditEvent, Decision, ProductionState
from clearframe.pipeline import build_context, demo_context
from clearframe.stages.dossier import DossierStage
from clearframe.store import LocalJsonStore


def _dossier_ctx(out_root: Path, state: ProductionState):
    """Context for dossier-time work (watch creation): live clients when the
    environment is configured live, fixtures otherwise — a live deployment
    must not silently create fixture watches."""
    cfg = ClearFrameConfig.from_env(os.environ)
    if cfg.mode == "live" and cfg.parallel_api_key:
        return build_context(cfg, state.production, out_root)
    return demo_context(out_root)

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


WATCH_WEBHOOK_PATH = "/api/webhooks/parallel-monitor"

_IP_CATEGORIES = {"COPYRIGHT_ART", "TRADEMARK", "MUSIC_SYNC"}


def _watch_query(element, research, opinion) -> str | None:
    """What the standing watch should look for — or None if no watch is needed."""
    if research is not None and research.status == "incomplete":
        if element.category.value in _IP_CATEGORIES:
            return (
                f"Identification or attribution of '{element.label}': new registry "
                "entries, press, or databases naming the artist/owner."
            )
        return None
    holding = opinion.holding if opinion else None
    litigious = research is not None and research.licensing_posture.value == "litigious"
    if holding in {"clear_required", "escalate"} or litigious:
        owner = research.owner if research else "the rights holder"
        return (
            f"New litigation, trademark/copyright filings, enforcement actions, or "
            f"licensing-policy changes by {owner} affecting film/TV depiction of "
            f"'{element.label}'."
        )
    return None


async def create_watches(ctx, state: ProductionState, at: str) -> None:
    for el in state.elements:
        if el.id in state.watches:
            continue
        query = _watch_query(el, state.research.get(el.id), state.court.get(el.id))
        if query is None:
            continue
        watch = await ctx.parallel.create_monitor(
            el.id, query, frequency="weekly", webhook_url=WATCH_WEBHOOK_PATH
        )
        if watch is None:
            continue
        state.watches[el.id] = watch
        state.audit_log.append(
            AuditEvent(
                at=at,
                actor="system",
                role="system",
                event="watch_created",
                detail=f"{el.id}:{watch.monitor_id}",
            )
        )


async def generate_dossier_async(
    store: LocalJsonStore, out_root: Path, production_id: str, *, at: str
) -> list[str]:
    """Run the dossier stage over reviewed state; returns artifact names.

    Raises ReviewPendingError (from DossierStage) when decisions are missing.
    After the dossier, standing clearance watches (Parallel monitors) are
    created for findings whose risk can change after delivery.
    """
    out_root = Path(out_root)
    state = store.load(production_id)
    ctx = _dossier_ctx(out_root, state)
    ctx.store = store
    ctx.state = state
    await DossierStage(out_dir=out_root, generated_at=at).run(ctx)
    state.audit_log.append(
        AuditEvent(at=at, actor="system", role="system", event="dossier_generated", detail="")
    )
    await create_watches(ctx, state, at)
    store.save(state)
    return [p.name for p in sorted(out_root.iterdir()) if p.is_file()]


def record_watch_alert(
    store: LocalJsonStore,
    production_id: str,
    monitor_id: str,
    summary: str,
    source_url: str,
    *,
    at: str,
) -> str | None:
    """Apply an incoming monitor alert: reopen review for the watched element.

    Returns the reopened element id, or None if no watch matches."""
    state = store.load(production_id)
    match = next(
        (w for w in state.watches.values() if w.monitor_id == monitor_id), None
    )
    if match is None:
        return None
    from clearframe.models import WatchAlert

    state.alerts.append(
        WatchAlert(
            element_id=match.element_id,
            monitor_id=monitor_id,
            at=at,
            summary=summary,
            source_url=source_url,
        )
    )
    state.stage_status["review"] = "awaiting"
    state.audit_log.append(
        AuditEvent(
            at=at,
            actor="parallel-monitor",
            role="system",
            event="watch_alert",
            detail=f"{match.element_id}: {summary}",
        )
    )
    store.save(state)
    return match.element_id


def generate_dossier_for(
    store: LocalJsonStore, out_root: Path, production_id: str, *, at: str
) -> list[str]:
    """Sync wrapper for non-async callers (CLI, sync tests)."""
    return asyncio.run(generate_dossier_async(store, out_root, production_id, at=at))
