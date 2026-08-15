"""ClearFrame CLI: run the clearance pipeline and export the dossier."""

import argparse
import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

from clearframe.config import ClearFrameConfig, validate_live
from clearframe.dossier import auto_decisions
from clearframe.models import Production
from clearframe.pipeline import (
    Pipeline,
    PipelineContext,
    build_context,
    build_demo_pipeline,
    demo_context,
)
from clearframe.stages.dossier import DossierStage


def _print_summary(state) -> None:
    print(f"\nClearance summary — “{state.production.title}”")
    print(f"{'ELEMENT':<32} {'BAND':<9} {'SCORE':>5}  {'OWNER':<38} ACTION")
    for el in sorted(state.elements, key=lambda e: state.risk[e.id].score, reverse=True):
        risk = state.risk[el.id]
        research = state.research.get(el.id)
        owner = (research.owner if research and research.owner else "UNKNOWN")[:38]
        decision = state.decisions.get(el.id)
        action = decision.action.upper() if decision else "PENDING"
        print(f"{el.label[:32]:<32} {risk.band.value:<9} {risk.score:>5}  {owner:<38} {action}")


def _try_resume(ctx: PipelineContext) -> None:
    """Reuse persisted state from a previous run of the same production/footage.

    Live-mode stages (Gemini scan, Parallel research) are expensive; a crash
    mid-pipeline should not force a full re-run.
    """
    try:
        existing = ctx.store.load(ctx.state.production.id)
    except FileNotFoundError:
        return
    if existing.production.footage_uri == ctx.state.production.footage_uri:
        done = [s for s, v in existing.stage_status.items() if v == "complete"]
        if done:
            print(f"Resuming production '{existing.production.id}' (completed: {', '.join(done)})")
        ctx.state = existing


async def _run(ctx: PipelineContext, out_dir: Path, auto_approve: bool) -> int:
    _try_resume(ctx)
    state = await Pipeline(build_demo_pipeline()).run(ctx)

    if auto_approve:
        from clearframe.dossier import build_dossier
        from clearframe.exporters.dossier_html import render_dossier_html
        from clearframe.models import AuditEvent
        from clearframe.review import create_watches

        at = datetime.now(timezone.utc).isoformat()
        state.decisions = auto_decisions(state)
        for decision in state.decisions.values():
            state.audit_log.append(
                AuditEvent(
                    at=at,
                    actor=decision.reviewer,
                    role=decision.role,
                    event="decision",
                    detail=f"{decision.element_id}:{decision.action}",
                )
            )
        stage = DossierStage(out_dir=out_dir, generated_at=at)
        await stage.run(ctx)
        state.audit_log.append(
            AuditEvent(at=at, actor="system", role="system", event="dossier_generated", detail="")
        )
        await create_watches(ctx, state, at)
        # regenerate the dossier HTML so its audit-trail section includes this run
        (out_dir / "dossier.html").write_text(
            render_dossier_html(build_dossier(state, generated_at=at))
        )
        ctx.store.save(state)
        _print_summary(state)
        print(f"\nArtifacts written to {out_dir}/:")
        for name in sorted(p.name for p in out_dir.iterdir() if p.is_file()):
            print(f"  - {name}")
    else:
        _print_summary(state)
        print(
            "\nPipeline paused: awaiting human review. "
            "Open the review UI (python -m clearframe serve) or re-run with "
            "--auto-approve to apply demo decisions and generate the dossier."
        )
    return 0


def _cmd_run(args) -> int:
    out_dir: Path = args.out
    if args.live:
        cfg = ClearFrameConfig.from_env(os.environ)
        cfg = cfg.model_copy(update={"mode": "live"})
        missing = validate_live(cfg)
        if missing:
            print(
                "Live mode needs credentials. Missing environment variables: "
                + ", ".join(missing)
            )
            return 2
        if not args.footage:
            print("Live mode requires --footage <path or gs:// URI>.")
            return 2
        production = Production(
            id=args.production_id,
            title=args.title,
            footage_uri=args.footage,
            fps=args.fps,
            duration_s=args.duration_s,
        )
        ctx = build_context(cfg, production, out_dir)
    else:
        ctx = demo_context(out_dir)

    if args.adk:
        if not args.auto_approve:
            print("--adk requires --auto-approve (the ADK run includes the dossier stage).")
            return 2
        try:
            from clearframe.adk.agents import run_pipeline_adk
        except ImportError:
            print('The ADK runner needs the cloud extra: pip install -e ".[cloud]"')
            return 2
        state = asyncio.run(run_pipeline_adk(ctx, out_dir, auto_approve=True))
        _print_summary(state)
        print(f"\nPipeline executed as an ADK SequentialAgent. Artifacts in {out_dir}/.")
        return 0
    return asyncio.run(_run(ctx, out_dir, args.auto_approve))


def _cmd_serve(args) -> int:
    import uvicorn

    from clearframe.webapp.server import create_app

    app = create_app(out_root=args.out)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clearframe")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the clearance pipeline")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument(
        "--demo", action="store_true", help="Use recorded fixtures (no credentials)"
    )
    mode.add_argument(
        "--live", action="store_true", help="Use Vertex Gemini + Parallel Task API"
    )
    run.add_argument("--footage", help="Footage path or gs:// URI (live mode)")
    run.add_argument("--title", default="Untitled Production")
    run.add_argument("--production-id", default="prod-1")
    run.add_argument("--duration-s", type=float, default=0.0)
    run.add_argument("--fps", type=float, default=24.0, help="Footage frame rate")
    run.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    run.add_argument(
        "--auto-approve",
        action="store_true",
        help="Apply demo review decisions and generate the dossier",
    )
    run.add_argument(
        "--adk",
        action="store_true",
        help="Execute the pipeline through the Google ADK SequentialAgent runner "
        "(requires the cloud extra and --auto-approve)",
    )
    run.set_defaults(func=_cmd_run)

    serve = sub.add_parser("serve", help="Serve the clearance review web app")
    serve.add_argument("--out", type=Path, default=Path("out"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    if args.command == "run" and not (args.demo or args.live):
        args.demo = True
    return args.func(args)
