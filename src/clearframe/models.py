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


class BBox(BaseModel):
    """Normalized frame box, origin top-left, all coords 0-1.

    Gemini returns [ymin, xmin, ymax, xmax] scaled 0-1000; the parser divides
    by 1000 so downstream code (UI overlay, frame crops) is resolution-free.
    """

    ymin: float = Field(ge=0, le=1)
    xmin: float = Field(ge=0, le=1)
    ymax: float = Field(ge=0, le=1)
    xmax: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _check_order(self) -> "BBox":
        if self.ymax <= self.ymin or self.xmax <= self.xmin:
            raise ValueError("bbox max coords must exceed min coords")
        return self


class DetectedElement(BaseModel):
    id: str
    label: str
    element_type: ElementType
    description: str
    time_ranges: list[TimeRange]
    prominence: Prominence
    bbox: BBox | None = None
    at_s: float | None = None


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


class Precedent(BaseModel):
    case_name: str
    citation: str
    holding: str
    relevance: str
    quote: str = ""
    source_url: str = ""


class ScriptMention(BaseModel):
    label: str
    element_type: ElementType
    scene: str


class ScriptDrift(BaseModel):
    unscripted_element_ids: list[str]
    scripted_not_seen: list[str]


class CandidateEntity(BaseModel):
    name: str
    kind: str
    url: str
    note: str


class ClearanceWatch(BaseModel):
    element_id: str
    monitor_id: str
    query: str
    frequency: str


class WatchAlert(BaseModel):
    element_id: str
    monitor_id: str
    at: str
    summary: str
    source_url: str


class Brief(BaseModel):
    side: Literal["counsel", "advocate"]
    argument: str
    precedents: list[Precedent]


class CourtOpinion(BaseModel):
    element_id: str
    holding: Literal["clear_required", "defensible", "escalate"]
    confidence: Literal["low", "medium", "high"]
    reasoning: str
    briefs: list[Brief]


class ResearchPlan(BaseModel):
    element_id: str
    processor: Literal["lite", "base", "pro", "ultra"]
    rationale: str
    est_cost_usd: float


class AuditEvent(BaseModel):
    at: str
    actor: str
    role: str
    event: str
    detail: str


class IdentityVerdict(str, Enum):
    """How well a second, independent detector agreed on WHAT this element is.

    The E&O auditor pass is Gemini checking Gemini — same model, correlated
    errors. It catches misses, not misidentifications. A misidentified brand
    routes research to the wrong rights holder and certifies a clearance that
    was never obtained, so identity gets its own corroborated/conflicted state.

    FINGERPRINTED outranks CORROBORATED: an acoustic fingerprint is a
    measurement over the audio itself (spectral peak hashing), not a
    classifier's opinion about what something looks like.
    """

    FINGERPRINTED = "FINGERPRINTED"
    CORROBORATED = "CORROBORATED"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    CONFLICTED = "CONFLICTED"


class DetectorHit(BaseModel):
    """One observation from a second, independent detector."""

    label: str
    confidence: float = Field(ge=0, le=1)
    start_s: float | None = None
    end_s: float | None = None
    bbox: BBox | None = None


class Corroboration(BaseModel):
    element_id: str
    verdict: IdentityVerdict
    detector: str
    detected_label: str | None
    confidence: float = Field(ge=0, le=1)
    note: str


class AudioProvenance(str, Enum):
    """Is the matched recording backed by a real catalogue?

    Fingerprint databases are crowd-fed. A knockoff re-upload can match the
    right TITLE while carrying a junk artist and label. If no major catalogue
    (Spotify / Apple Music / Deezer / MusicBrainz) backs the row, the title is
    usable and the attribution is not — and attribution is what flows into an
    ASCAP/BMI cue sheet, which is a legal filing.
    """

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class AudioMatch(BaseModel):
    """One acoustic fingerprint hit against a recording database."""

    title: str
    artist: str = ""
    album: str = ""
    label: str = ""
    release_date: str = ""
    isrc: str = ""
    song_link: str = ""
    at_s: float = 0.0
    confidence: float = Field(default=0.0, ge=0, le=1)
    provenance: AudioProvenance = AudioProvenance.UNVERIFIED
    catalogues: list[str] = Field(default_factory=list)


class WebFinding(BaseModel):
    """One ranked web result with an LLM-optimized excerpt (Parallel Search)."""

    title: str
    url: str
    excerpt: str


class FreshnessSignal(BaseModel):
    """A real-time web signal about the rights holder, found at review time."""

    element_id: str
    owner: str
    title: str
    url: str
    excerpt: str
    material: bool


class TerritoryRisk(BaseModel):
    element_id: str
    territory: str
    band: RiskBand
    rationale: str
    authority: str


class LicenceGrant(BaseModel):
    """A clearance the production ALREADY holds.

    ClearFrame's research answers "who owns this and what would it cost".
    The ledger answers the question a director actually asks first: "am I
    already covered?" Matching is by rights holder, then checked for the three
    gaps that sink real productions — territory, term, and media scope. The
    last one gutted WKRP in Cincinnati: music cleared for broadcast, never for
    home video or streaming.
    """

    id: str
    rights_holder: str
    work: str = ""
    scope: str = ""
    territories: list[str] = Field(default_factory=lambda: ["WORLDWIDE"])
    media: list[str] = Field(default_factory=lambda: ["ALL"])
    starts: str = ""
    expires: str | None = None
    reference: str = ""
    notes: str = ""


class CoverageStatus(str, Enum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    NOT_COVERED = "NOT_COVERED"
    UNKNOWN = "UNKNOWN"


class Coverage(BaseModel):
    element_id: str
    status: CoverageStatus
    licence_id: str | None = None
    rights_holder: str | None = None
    gaps: list[str] = Field(default_factory=list)
    note: str = ""


class Production(BaseModel):
    id: str
    title: str
    footage_uri: str
    fps: float = 24.0
    duration_s: float
    script_uri: str | None = None
    release_territories: list[str] = Field(default_factory=lambda: ["US"])
    distribution: list[str] = Field(
        default_factory=lambda: ["THEATRICAL", "STREAMING"]
    )
    has_media: bool = False


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
    audit_log: list[AuditEvent] = Field(default_factory=list)
    court: dict[str, CourtOpinion] = Field(default_factory=dict)
    research_plan: dict[str, ResearchPlan] = Field(default_factory=dict)
    script_mentions: list[ScriptMention] = Field(default_factory=list)
    drift: ScriptDrift | None = None
    candidates: dict[str, list[CandidateEntity]] = Field(default_factory=dict)
    watches: dict[str, ClearanceWatch] = Field(default_factory=dict)
    alerts: list[WatchAlert] = Field(default_factory=list)
    corroboration: dict[str, Corroboration] = Field(default_factory=dict)
    freshness: dict[str, list[FreshnessSignal]] = Field(default_factory=dict)
    territory_risk: dict[str, list[TerritoryRisk]] = Field(default_factory=dict)
    territories: list[str] = Field(default_factory=list)
    coverage: dict[str, Coverage] = Field(default_factory=dict)
    audio_matches: list[AudioMatch] = Field(default_factory=list)
    detector_hits: list[DetectorHit] = Field(default_factory=list)
