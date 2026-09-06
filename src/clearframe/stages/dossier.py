"""Stage 6: assemble the reviewed dossier and write the report.

Two artifacts, and they are the same document in two formats: HTML to read in
the browser, DOCX to file with an E&O application and mark up in Word.

The EDL, the marker CSV, the PRO cue sheet and the raw JSON dump used to be
written here too, and were offered to the user as five equal filename links —
so the deliverable was one file among five, and three of them were spreadsheets.
A clearance report is a document. It is now presented as one.
"""

from datetime import datetime, timezone
from pathlib import Path

from clearframe.dossier import build_dossier, pending_ids
from clearframe.exporters.dossier_docx import render_dossier_docx
from clearframe.exporters.dossier_html import render_dossier_html
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

        self.out_dir.mkdir(parents=True, exist_ok=True)
        (self.out_dir / "dossier.html").write_text(render_dossier_html(dossier))
        render_dossier_docx(dossier, self.out_dir / "dossier.docx")
        ctx.state.stage_status["review"] = "complete"
