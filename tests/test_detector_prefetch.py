"""An empty prefetch is not a missing prefetch.

`scan` runs Cloud Video Intelligence concurrently with Gemini and stashes the
result, so `corroborate` can consume it for free. The guard was `if not hits`,
which cannot tell "the detector ran and found nothing" from "the detector never
ran" — so a clip where VI recognised no catalogued logo paid its full latency a
second time, for the same empty answer.

Measured at 65 seconds on a 41.5s clip, every live run, for zero extra signal.

This is the AudD bug in a different module: an inactive account returned HTTP
200 with error 900, which looked identical to a genuine no-match, and the fix
was `state.audio_checked` — a flag that separates "asked and got nothing" from
"never asked". The same fix applies here.
"""

import pytest

from clearframe.models import Production, ProductionState
from clearframe.pipeline import PipelineContext
from clearframe.stages.corroborate import CorroborateStage


class CountingCorroborator:
    name = "test-detector"

    def __init__(self, hits=()):
        self.calls = 0
        self._hits = list(hits)

    async def detect(self, footage_uri, duration_s):
        self.calls += 1
        return list(self._hits)


def ctx_with(state, corroborator):
    return PipelineContext(
        state=state, gemini=None, parallel=None, store=None,
        court=None, corroborator=corroborator, audio=None,
    )


def base_state(**patch):
    prod = Production(id="p", title="t", footage_uri="c.mp4", duration_s=41.5)
    return ProductionState(production=prod, **patch)


@pytest.mark.asyncio
async def test_an_empty_prefetch_is_not_called_again():
    """The 65-second bug, exactly."""
    det = CountingCorroborator(hits=[])
    state = base_state(detector_hits=[], detector_checked=True)

    await CorroborateStage().run(ctx_with(state, det))

    assert det.calls == 0


@pytest.mark.asyncio
async def test_an_absent_prefetch_still_calls_the_detector():
    det = CountingCorroborator(hits=[])
    state = base_state(detector_hits=[], detector_checked=False)

    await CorroborateStage().run(ctx_with(state, det))

    assert det.calls == 1
    # And having asked is now recorded, so nothing asks again.
    assert state.detector_checked is True


@pytest.mark.asyncio
async def test_the_stage_still_works_with_no_detector_at_all():
    state = base_state()
    await CorroborateStage().run(ctx_with(state, None))
    assert state.detector_checked is False
