"""ClearFrame CLI: run the clearance pipeline and export the dossier."""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from clearframe.dossier import auto_decisions
from clearframe.pipeline import Pipeline, build_demo_pipeline, demo_context
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


async def _run_demo(out_dir: Path, auto_approve: bool) -> int:
    ctx = demo_context(out_dir)
    state = await Pipeline(build_demo_pipeline()).run(ctx)

    if auto_approve:
        state.decisions = auto_decisions(state)
        stage = DossierStage(
            out_dir=out_dir, generated_at=datetime.now(timezone.utc).isoformat()
        )
        await stage.run(ctx)
        ctx.store.save(state)
        _print_summary(state)
        print(f"\nArtifacts written to {out_dir}/:")
        for name in ("dossier.html", "dossier.json", "markers.edl", "markers.csv"):
            print(f"  - {name}")
    else:
        _print_summary(state)
        print(
            "\nPipeline paused: awaiting human review. "
            "Re-run with --auto-approve to apply demo decisions and generate the dossier."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="clearframe")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run the clearance pipeline")
    run.add_argument("--demo", action="store_true", help="Use recorded fixtures (no credentials)")
    run.add_argument("--out", type=Path, default=Path("out"), help="Output directory")
    run.add_argument(
        "--auto-approve",
        action="store_true",
        help="Apply demo review decisions and generate the dossier",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        print(
            "Live mode arrives in Phase 2 (Vertex Gemini + Parallel API). "
            "Use --demo for the fixture-backed pipeline."
        )
        return 2
    return asyncio.run(_run_demo(args.out, args.auto_approve))
