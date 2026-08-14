import pytest
from pydantic import ValidationError

from clearframe.models import (
    DetectedElement,
    ElementType,
    Production,
    ProductionState,
    Prominence,
    TimeRange,
)


def test_time_range_validates_order():
    with pytest.raises(ValidationError):
        TimeRange(start_s=5.0, end_s=2.0)


def test_time_range_duration():
    assert TimeRange(start_s=1.0, end_s=3.5).duration_s == 2.5


def test_prominence_bounds():
    with pytest.raises(ValidationError):
        Prominence(screen_time_s=1, frame_coverage=1.5, centrality=0.5, plot_integral=False)


def test_production_state_roundtrip():
    state = ProductionState(
        production=Production(id="p1", title="Demo", footage_uri="demo://scene", duration_s=62.0)
    )
    data = state.model_dump_json()
    assert ProductionState.model_validate_json(data).production.title == "Demo"
