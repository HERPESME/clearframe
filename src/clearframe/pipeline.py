"""Deterministic pipeline orchestrator: fixed stage order, resumable, persisted per stage."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from clearframe.integrations.gemini_client import FixtureGeminiClient, GeminiClient
from clearframe.integrations.parallel_client import FixtureParallelClient, ParallelClient
from clearframe.models import Production, ProductionState
from clearframe.store import LocalJsonStore

FIXTURES_DIR = Path(__file__).parent / "integrations" / "fixtures"

ANALYSIS_STAGES = ("scan", "triage", "research", "risk", "remediation")


@dataclass
class PipelineContext:
    state: ProductionState
    gemini: GeminiClient
    parallel: ParallelClient
    store: LocalJsonStore


class Stage(Protocol):
    name: str

    async def run(self, ctx: PipelineContext) -> None: ...


class Pipeline:
    def __init__(self, stages: list[Stage]):
        self.stages = stages

    async def run(self, ctx: PipelineContext) -> ProductionState:
        for stage in self.stages:
            if ctx.state.stage_status.get(stage.name) == "complete":
                continue
            ctx.state.stage_status[stage.name] = "running"
            await stage.run(ctx)
            ctx.state.stage_status[stage.name] = "complete"
            ctx.store.save(ctx.state)
        if all(ctx.state.stage_status.get(s) == "complete" for s in ANALYSIS_STAGES):
            ctx.state.stage_status.setdefault("review", "awaiting")
            ctx.store.save(ctx.state)
        return ctx.state


def build_demo_pipeline() -> list[Stage]:
    from clearframe.stages.remediation import RemediationStage
    from clearframe.stages.research import ResearchStage
    from clearframe.stages.risk import RiskStage
    from clearframe.stages.scan import ScanStage
    from clearframe.stages.triage_stage import TriageStage

    return [ScanStage(), TriageStage(), ResearchStage(), RiskStage(), RemediationStage()]


def build_context(cfg, production: Production, out_root: Path) -> PipelineContext:
    """Build a PipelineContext from a ClearFrameConfig (demo fixtures or live clients)."""
    if cfg.mode == "live":
        from clearframe.integrations.gemini_live import LiveGeminiClient
        from clearframe.integrations.parallel_client import LiveParallelClient

        gemini: GeminiClient = LiveGeminiClient(
            project=cfg.project, location=cfg.location, model=cfg.gemini_model
        )
        parallel: ParallelClient = LiveParallelClient(api_key=cfg.parallel_api_key)
    else:
        gemini = FixtureGeminiClient(FIXTURES_DIR)
        parallel = FixtureParallelClient(FIXTURES_DIR)
    return PipelineContext(
        state=ProductionState(production=production),
        gemini=gemini,
        parallel=parallel,
        store=LocalJsonStore(Path(out_root) / "state"),
    )


def demo_context(out_root: Path) -> PipelineContext:
    production = Production(
        id="demo",
        title="Golden Hour",
        footage_uri="demo://salted-scene",
        duration_s=62.0,
    )
    return PipelineContext(
        state=ProductionState(production=production),
        gemini=FixtureGeminiClient(FIXTURES_DIR),
        parallel=FixtureParallelClient(FIXTURES_DIR),
        store=LocalJsonStore(Path(out_root) / "state"),
    )
