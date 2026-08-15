"""Stage 6: assemble the reviewed dossier and write all export artifacts."""

from datetime import datetime, timezone
from pathlib import Path

from clearframe.dossier import build_dossier, pending_ids
from clearframe.exporters.csv_markers import render_csv
from clearframe.exporters.cue_sheet import render_cue_sheet
from clearframe.exporters.dossier_html import render_dossier_html
from clearframe.exporters.edl import elements_to_markers, render_edl
from clearframe.models import ClearanceCategory
from clearframe.pipeline import PipelineContext


class ReviewPendingError(Exception):
    """Raised when dossier generation is attempted before every element has a decision."""


class DossierStage:
    name = "dossier"

    def __init__(self, out_dir: Path, generated_at: str | None = None):
        self.out_dir = Path(out_dir)
        self.generated_at = generated_at

    async def run(self, ctx: PipelineContext) -> None:
        missing = pending_ids(ctx.state)
        if missing:
            raise ReviewPendingError(
                f"Elements awaiting review decision: {', '.join(missing)}"
            )

        generated_at = self.generated_at or datetime.now(timezone.utc).isoformat()
        dossier = build_dossier(ctx.state, generated_at=generated_at)
        markers = elements_to_markers(ctx.state.elements, ctx.state.risk)
        fps = ctx.state.production.fps

        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "dossier.html").write_text(render_dossier_html(dossier))
        (self.out_dir / "dossier.json").write_text(dossier.model_dump_json(indent=2))
        (self.out_dir / "markers.edl").write_text(
            render_edl(f"ClearFrame Risk Markers - {ctx.state.production.title}", markers, fps)
        )
        (self.out_dir / "markers.csv").write_text(render_csv(markers, fps))
        if any(
            el.category == ClearanceCategory.MUSIC_SYNC for el in ctx.state.elements
        ):
            (self.out_dir / "cue_sheet.csv").write_text(
                render_cue_sheet(
                    ctx.state.production, ctx.state.elements, ctx.state.research
                )
            )
        ctx.state.stage_status["review"] = "complete"
