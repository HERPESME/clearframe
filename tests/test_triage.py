from clearframe.models import (
    ClearanceCategory,
    DetectedElement,
    ElementType,
    Prominence,
    TimeRange,
)
from clearframe.triage import triage


def det(id, label, t, start, end, st=2.0, cov=0.1, cen=0.5, plot=False):
    return DetectedElement(
        id=id,
        label=label,
        element_type=t,
        description="d",
        time_ranges=[TimeRange(start_s=start, end_s=end)],
        prominence=Prominence(
            screen_time_s=st, frame_coverage=cov, centrality=cen, plot_integral=plot
        ),
    )


def test_tattoo_maps_to_copyright():
    out = triage([det("a", "tribal tattoo", ElementType.TATTOO, 0, 2)])
    assert out[0].category == ClearanceCategory.COPYRIGHT_ART


def test_duplicates_merge_across_shots():
    out = triage(
        [
            det("a", "Nike hoodie", ElementType.LOGO, 0, 5, st=5),
            det("b", "nike hoodie ", ElementType.LOGO, 20, 30, st=10, cov=0.2, plot=True),
        ]
    )
    assert len(out) == 1
    merged = out[0]
    assert merged.prominence.screen_time_s == 15
    assert merged.prominence.frame_coverage == 0.2
    assert merged.prominence.plot_integral is True
    assert [r.start_s for r in merged.time_ranges] == [0, 20]
