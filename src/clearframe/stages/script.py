"""Stage 0: script pre-scan — clearance reading before a frame is shot."""

from pathlib import Path

from clearframe.pipeline import FIXTURES_DIR, PipelineContext


def _load_script_text(script_uri: str) -> str:
    if script_uri.startswith("demo://"):
        name = script_uri.removeprefix("demo://").removesuffix("-script")
        return (FIXTURES_DIR / "script" / f"{name}.txt").read_text()
    return Path(script_uri).read_text()


class ScriptStage:
    name = "script"

    async def run(self, ctx: PipelineContext) -> None:
        script_uri = ctx.state.production.script_uri
        if not script_uri:
            ctx.emit({"type": "script_mentions", "count": 0, "skipped": True})
            return
        text = _load_script_text(script_uri)
        ctx.state.script_mentions = await ctx.gemini.scan_script(text)
        ctx.emit({"type": "script_mentions", "count": len(ctx.state.script_mentions)})
