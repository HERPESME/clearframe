"""Google ADK adapter: exposes the ClearFrame pipeline as a SequentialAgent.

Each pipeline stage becomes a deterministic custom BaseAgent; the
SequentialAgent enforces the fixed clearance workflow order. The same
PipelineContext used by the plain orchestrator is shared across stage agents,
so ADK execution and local execution are behaviorally identical.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator

from google.adk.agents import BaseAgent, SequentialAgent
from google.adk.events import Event, EventActions
from pydantic import ConfigDict

from clearframe.dossier import auto_decisions
from clearframe.pipeline import PipelineContext, Stage, build_demo_pipeline
from clearframe.stages.dossier import DossierStage

if TYPE_CHECKING:
    from google.adk.agents.invocation_context import InvocationContext

STATE_PREFIX = "clearframe:"


class StageAgent(BaseAgent):
    """Runs one ClearFrame pipeline stage and records completion in session state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    stage: Any  # Stage protocol — Protocols aren't valid pydantic field types
    pipeline_ctx: Any  # PipelineContext

    async def _run_async_impl(
        self, ctx: "InvocationContext"
    ) -> AsyncGenerator[Event, None]:
        self.pipeline_ctx.state.stage_status[self.stage.name] = "running"
        await self.stage.run(self.pipeline_ctx)
        self.pipeline_ctx.state.stage_status[self.stage.name] = "complete"
        self.pipeline_ctx.store.save(self.pipeline_ctx.state)
        yield Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            actions=EventActions(
                state_delta={STATE_PREFIX + self.stage.name: "complete"}
            ),
        )


class _AutoApproveDossierStage:
    """Dossier stage variant that applies demo decisions when none exist yet."""

    name = "dossier"

    def __init__(self, out_dir: Path):
        self._inner = DossierStage(out_dir=out_dir)

    async def run(self, ctx: PipelineContext) -> None:
        if not ctx.state.decisions:
            ctx.state.decisions = auto_decisions(ctx.state)
        await self._inner.run(ctx)


def build_clearframe_agent(
    ctx: PipelineContext, out_dir: Path, auto_approve: bool = False
) -> SequentialAgent:
    stages: list[Stage] = list(build_demo_pipeline())
    stages.append(
        _AutoApproveDossierStage(out_dir) if auto_approve else DossierStage(out_dir=out_dir)
    )
    return SequentialAgent(
        name="clearframe_pipeline",
        description=(
            "Deterministic rights-clearance pipeline: scan footage, triage elements, "
            "research rights holders, score risk, draft remediation, emit dossier."
        ),
        sub_agents=[
            StageAgent(name=f"clearframe_{stage.name}", stage=stage, pipeline_ctx=ctx)
            for stage in stages
        ],
    )
