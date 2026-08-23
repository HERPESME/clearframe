"""One pass sees about 60% of what the scan can find.

Measured, not assumed. Three identical baseline runs over the same 41.5s clip,
clustered with the project's own `matching.labels_match`:

    15 distinct things across the three runs
    mean 9.0 per run
    only 3 of 15 appeared in all three
    7 of 15 appeared in exactly one

Recall is this product's entire safety claim — "we find what you missed" — so
a 40% miss rate per pass is the largest hole in it. No parameter fixes it:
media_resolution is rejected by the model (400), and fps=2 was strictly worse
(mean 6.5 findings, and its apparent speed advantage was just producing less).

What does fix it is another pass. The auditor already proved that, and this
runs a second INDEPENDENT scan concurrently with the first, then primes the
auditor on the union of both — so the audit knows more before it starts, and
the extra pass costs almost no wall clock because it overlaps.
"""

import asyncio

import pytest

from clearframe.models import DetectedElement, ElementType, Prominence, TimeRange
from clearframe.stages.scan import merge_passes


def det(eid, label):
    return DetectedElement(
        id=eid, label=label, element_type=ElementType.LOGO, description="",
        time_ranges=[TimeRange(start_s=1.0, end_s=4.0)],
        prominence=Prominence(screen_time_s=3.0, frame_coverage=0.2,
                              centrality=0.5, plot_integral=False),
    )


class RecordingGemini:
    """Two independent passes that disagree, exactly like the real ones."""

    def __init__(self):
        self.scan_calls = 0
        self.audit_seen: list[str] = []
        self.concurrent = False
        self._active = 0

    async def scan(self, uri, duration_s, context=""):
        from clearframe.integrations.gemini_client import ScanResult

        self._active += 1
        if self._active > 1:
            self.concurrent = True
        self.scan_calls += 1
        n = self.scan_calls
        await asyncio.sleep(0.01)
        self._active -= 1
        found = (
            [det("1", "Calvin Klein"), det("2", "Wristwatch")]
            if n == 1
            else [det("1", "Calvin Klein"), det("2", "Aviator Sunglasses")]
        )
        return ScanResult(detections=found, unscanned_ranges=[])

    async def audit_scan(self, uri, duration_s, found_labels, context=""):
        from clearframe.integrations.gemini_client import ScanResult

        self.audit_seen = list(found_labels)
        return ScanResult(detections=[det("1", "National")], unscanned_ranges=[])


@pytest.mark.asyncio
async def test_two_independent_passes_run_and_their_findings_union():
    from clearframe.stages.scan import gather_detections

    g = RecordingGemini()
    detections, _first, _audit = await gather_detections(g, "clip.mp4", 41.5, "", passes=2)

    labels = {d.label for d in detections}
    assert g.scan_calls == 2
    assert labels == {"Calvin Klein", "Wristwatch", "Aviator Sunglasses", "National"}


@pytest.mark.asyncio
async def test_the_passes_overlap_rather_than_queue():
    """The extra recall has to be nearly free in wall clock or it will be cut."""
    from clearframe.stages.scan import gather_detections

    g = RecordingGemini()
    await gather_detections(g, "clip.mp4", 41.5, "", passes=2)
    assert g.concurrent is True


@pytest.mark.asyncio
async def test_the_auditor_is_primed_on_everything_both_passes_found():
    from clearframe.stages.scan import gather_detections

    g = RecordingGemini()
    await gather_detections(g, "clip.mp4", 41.5, "", passes=2)
    assert set(g.audit_seen) == {"Calvin Klein", "Wristwatch", "Aviator Sunglasses"}


@pytest.mark.asyncio
async def test_one_pass_still_works():
    """passes=1 must behave exactly as before, for fixtures and demo mode."""
    from clearframe.stages.scan import gather_detections

    g = RecordingGemini()
    detections, _first, _audit = await gather_detections(g, "clip.mp4", 41.5, "", passes=1)
    assert g.scan_calls == 1
    assert {d.label for d in detections} == {"Calvin Klein", "Wristwatch", "National"}
