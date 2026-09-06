"""Deterministic pipeline orchestrator: fixed stage order, resumable, persisted per stage."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from clearframe.integrations.audio_client import AudioIdClient, FixtureAudioClient
from clearframe.integrations.court_client import CourtClient, FixtureCourtClient
from clearframe.integrations.gemini_client import FixtureGeminiClient, GeminiClient
from clearframe.integrations.parallel_client import FixtureParallelClient, ParallelClient
from clearframe.integrations.vision_client import (
    CorroborationClient,
    FixtureVisionClient,
)
from clearframe.models import Production, ProductionState
from clearframe.store import LicenceStore, LocalJsonStore

FIXTURES_DIR = Path(__file__).parent / "integrations" / "fixtures"

ANALYSIS_STAGES = (
    "script",
    "scan",
    "triage",
    "corroborate",
    "drift",
    "preview",
    "research",
    "freshness",
    "risk",
    "territory",
    "coverage",
    "remediation",
    "court",
)


@dataclass
class PipelineContext:
    state: ProductionState
    gemini: GeminiClient
    parallel: ParallelClient
    store: LocalJsonStore
    court: "CourtClient | None" = None
    corroborator: "CorroborationClient | None" = None
    audio: "AudioIdClient | None" = None
    licences: list = field(default_factory=list)
    listener: "Callable[[dict], None] | None" = None

    def emit(self, event: dict) -> None:
        """Publish a pipeline progress event (Mission Control); no-op unheard."""
        if self.listener is not None:
            self.listener(event)


class Stage(Protocol):
    name: str

    async def run(self, ctx: PipelineContext) -> None: ...


class Pipeline:
    def __init__(self, stages: list[Stage]):
        self.stages = stages

    async def run(self, ctx: PipelineContext) -> ProductionState:
        for stage in self.stages:
            if ctx.state.stage_status.get(stage.name) == "complete":
                ctx.emit({"type": "stage_skipped", "stage": stage.name})
                continue
            ctx.emit({"type": "stage_start", "stage": stage.name})
            ctx.state.stage_status[stage.name] = "running"
            await stage.run(ctx)
            ctx.state.stage_status[stage.name] = "complete"
            ctx.store.save(ctx.state)
            ctx.emit({"type": "stage_complete", "stage": stage.name})
        if all(ctx.state.stage_status.get(s) == "complete" for s in ANALYSIS_STAGES):
            ctx.state.stage_status.setdefault("review", "awaiting")
            ctx.store.save(ctx.state)
        return ctx.state


def build_demo_pipeline(max_research: int | None = None) -> list[Stage]:
    import os

    from clearframe.stages.remediation import RemediationStage
    from clearframe.stages.research import ResearchStage
    from clearframe.stages.risk import RiskStage
    from clearframe.stages.scan import ScanStage
    from clearframe.stages.triage_stage import TriageStage

    from clearframe.stages.corroborate import CorroborateStage
    from clearframe.stages.court import CourtStage
    from clearframe.stages.coverage import CoverageStage
    from clearframe.stages.drift_stage import DriftStage
    from clearframe.stages.freshness import FreshnessStage
    from clearframe.stages.preview import PreviewStage
    from clearframe.stages.script import ScriptStage
    from clearframe.stages.territory_stage import TerritoryStage

    if max_research is None:
        max_research = int(os.environ.get("CLEARFRAME_MAX_RESEARCH", "25"))
    return [
        ScriptStage(),
        ScanStage(),
        TriageStage(),
        CorroborateStage(),
        DriftStage(),
        PreviewStage(),
        ResearchStage(max_research=max_research),
        FreshnessStage(),
        RiskStage(),
        TerritoryStage(),
        CoverageStage(),
        RemediationStage(),
        CourtStage(),
    ]


def build_context(
    cfg,
    production: Production,
    out_root: Path,
    *,
    owner_uid: str = "",
    licences: list | None = None,
) -> PipelineContext:
    """Build a PipelineContext from a ClearFrameConfig (demo fixtures or live clients).

    `owner_uid` selects whose rights ledger the coverage stage reads. Empty — the
    default, and what the CLI, the MCP server and demo mode pass — means the
    deployment-wide ledger, unchanged. A signed-in upload passes the uploader's
    id so their licences decide their coverage and nobody else's.

    `licences` lets a caller that has already opened the right ledger hand it
    over. That caller is the worker, and it has to: `out_root` on Cloud Run is a
    per-instance tmpfs, so reading the ledger from disk there opened an empty
    file however many grants the user had uploaded through the API — and an
    empty ledger reports every finding uncovered without ever looking wrong.
    Left `None`, the local file is read exactly as before, which is what keeps
    the CLI, the MCP server and demo mode untouched.
    """
    if cfg.mode == "live":
        from clearframe.integrations.gemini_live import LiveGeminiClient
        from clearframe.integrations.parallel_client import LiveParallelClient

        from clearframe.integrations.court_client import LiveCourtClient

        gemini: GeminiClient = LiveGeminiClient(
            project=cfg.project, location=cfg.location, model=cfg.gemini_model
        )
        parallel: ParallelClient = LiveParallelClient(api_key=cfg.parallel_api_key)
        court: CourtClient = LiveCourtClient(
            project=cfg.project, location=cfg.location, model=cfg.gemini_model
        )
        from clearframe.integrations.vision_client import LiveVideoIntelligenceClient

        corroborator: CorroborationClient = LiveVideoIntelligenceClient()

        # Fingerprinting is optional: without a token music stays SINGLE_SOURCE,
        # which is the honest state, not a failure.
        if cfg.audd_api_token:
            from clearframe.integrations.audio_client import LiveAudDClient

            audio: AudioIdClient | None = LiveAudDClient(api_token=cfg.audd_api_token)
        else:
            audio = None
    else:
        gemini = FixtureGeminiClient(FIXTURES_DIR)
        parallel = FixtureParallelClient(FIXTURES_DIR)
        court = FixtureCourtClient(FIXTURES_DIR)
        corroborator = FixtureVisionClient(FIXTURES_DIR)
        audio = FixtureAudioClient(FIXTURES_DIR)
    return PipelineContext(
        state=ProductionState(production=production),
        gemini=gemini,
        parallel=parallel,
        store=LocalJsonStore(Path(out_root) / "state"),
        court=court,
        corroborator=corroborator,
        audio=audio,
        licences=(
            licences
            if licences is not None
            else LicenceStore(Path(out_root) / "state", owner_uid=owner_uid).load()
        ),
    )


def demo_context(out_root: Path) -> PipelineContext:
    production = Production(
        id="demo",
        title="Golden Hour",
        footage_uri="demo://salted-scene",
        duration_s=62.0,
        script_uri="demo://golden-hour-script",
        release_territories=["US", "DE", "FR"],
    )
    return PipelineContext(
        state=ProductionState(production=production),
        gemini=FixtureGeminiClient(FIXTURES_DIR),
        parallel=FixtureParallelClient(FIXTURES_DIR),
        store=LocalJsonStore(Path(out_root) / "state"),
        court=FixtureCourtClient(FIXTURES_DIR),
        corroborator=FixtureVisionClient(FIXTURES_DIR),
        audio=FixtureAudioClient(FIXTURES_DIR),
        licences=LicenceStore(Path(out_root) / "state").seed_demo(),
    )
