"""Domain models for the ClearFrame clearance pipeline."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ElementType(str, Enum):
    LOGO = "LOGO"
    ARTWORK = "ARTWORK"
    MUSIC = "MUSIC"
    FACE = "FACE"
    TATTOO = "TATTOO"
    LOCATION = "LOCATION"
    TEXT = "TEXT"


class ClearanceCategory(str, Enum):
    TRADEMARK = "TRADEMARK"
    COPYRIGHT_ART = "COPYRIGHT_ART"
    MUSIC_SYNC = "MUSIC_SYNC"
    RIGHT_OF_PUBLICITY = "RIGHT_OF_PUBLICITY"
    LOCATION = "LOCATION"
    TEXT_ON_SCREEN = "TEXT_ON_SCREEN"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LicensingPosture(str, Enum):
    PERMISSIVE = "permissive"
    STANDARD = "standard"
    LITIGIOUS = "litigious"
    UNKNOWN = "unknown"


class TimeRange(BaseModel):
    start_s: float = Field(ge=0)
    end_s: float

    @model_validator(mode="after")
    def _check_order(self) -> "TimeRange":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


class Prominence(BaseModel):
    screen_time_s: float = Field(ge=0)
    frame_coverage: float = Field(ge=0, le=1)
    centrality: float = Field(ge=0, le=1)
    plot_integral: bool


class DetectedElement(BaseModel):
    id: str
    label: str
    element_type: ElementType
    description: str
    time_ranges: list[TimeRange]
    prominence: Prominence


class TriagedElement(DetectedElement):
    category: ClearanceCategory


class BasisCitation(BaseModel):
    field: str
    url: str
    excerpt: str
    reasoning: str
    confidence: str


class ResearchResult(BaseModel):
    element_id: str
    owner: str | None
    owner_confidence: str
    licensing_contact: str | None
    licensing_posture: LicensingPosture
    litigation_history: list[str]
    estimated_license_cost_band: str | None
    basis: list[BasisCitation]
    status: Literal["complete", "incomplete"]

    @property
    def is_incomplete(self) -> bool:
        return self.status == "incomplete"


def research_is_incomplete(research: "ResearchResult | None") -> bool:
    """Shared predicate: no research at all counts as incomplete."""
    return research is None or research.is_incomplete


class RiskAssessment(BaseModel):
    element_id: str
    score: int
    band: RiskBand
    factors: dict[str, float]
    de_minimis: bool


class RemediationOption(BaseModel):
    kind: Literal["license", "blur", "reshoot", "fair_use_memo"]
    summary: str
    detail: str
    est_cost_band: str | None


class Decision(BaseModel):
    element_id: str
    action: Literal["approve_risk", "license", "blur", "reshoot", "escalate"]
    reviewer: str
    role: str
    note: str


class Production(BaseModel):
    id: str
    title: str
    footage_uri: str
    fps: float = 24.0
    duration_s: float


class ProductionState(BaseModel):
    production: Production
    stage_status: dict[str, str] = Field(default_factory=dict)
    detections: list[DetectedElement] = Field(default_factory=list)
    elements: list[TriagedElement] = Field(default_factory=list)
    research: dict[str, ResearchResult] = Field(default_factory=dict)
    risk: dict[str, RiskAssessment] = Field(default_factory=dict)
    remediation: dict[str, list[RemediationOption]] = Field(default_factory=dict)
    decisions: dict[str, Decision] = Field(default_factory=dict)
    unscanned_ranges: list[TimeRange] = Field(default_factory=list)
