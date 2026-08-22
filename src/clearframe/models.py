"""Domain models for the ClearFrame clearance pipeline."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ElementType(str, Enum):
    LOGO = "LOGO"
    # A drawn, animated or rendered character. Deliberately distinct from
    # FACE: a fictional character has no right of publicity — there is nobody
    # to consent — and the right that DOES exist is copyright in the design,
    # owned by the studio and cleared by a licence.
    CHARACTER = "CHARACTER"
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


class UseContext(str, Enum):
    """What KIND of work this is — which decides whether the shield applies.

    Rogers v. Grimaldi protects expressive works: a trademark yields unless the
    use has no artistic relevance or explicitly misleads about source. An
    advertisement is commercial speech and gets no such protection, and the
    Supreme Court narrowed Rogers further in Jack Daniel's v. VIP (2023).

    The litigation record splits cleanly along this line. Every brand-owner WIN
    is an advert — Falkner v. General Motors (Cadillac campaign), Mercedes-Benz
    v. the Detroit muralists, Revok v. H&M. Every brand-owner LOSS is an
    expressive work — Wham-O v. Paramount, Caterpillar v. Disney, Louis Vuitton
    v. Warner Bros.

    EXPRESSIVE is the default and the calibration baseline, so a production that
    does not declare a context scores exactly as it did before this existed.
    """

    EXPRESSIVE = "EXPRESSIVE"      # film, TV, skit, narrative short
    SPONSORED = "SPONSORED"        # creator content with a paid placement
    ADVERTISING = "ADVERTISING"    # commercial, brand campaign, promo
    NEWS = "NEWS"                  # reportage; strongest protection
    EDUCATIONAL = "EDUCATIONAL"    # teaching, commentary, criticism


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


class DepictionTone(str, Enum):
    """How the element is PORTRAYED, not whether it is present.

    The litigation record says brand owners rarely object to presence and
    reliably object to portrayal. Wham-O sued Paramount over a gag in which a
    character was hurt by a Slip 'N Slide. In-Sink-Erator complained when a
    character's hand was mangled in a garbage disposal on NBC's Heroes — and
    NBC digitally erased the mark rather than litigate, paying in post.

    One question added to a scan we already run answers three threat classes:
    trademark disparagement, false endorsement, and trade libel against a
    named business.

    None means the scan did not report it, which must behave exactly as
    NEUTRAL so that every stored state and fixture predating this is unchanged.
    """

    FAVOURABLE = "FAVOURABLE"        # reads as endorsement; free advertising
    NEUTRAL = "NEUTRAL"              # simply present
    UNFLATTERING = "UNFLATTERING"    # associated with failure, mess, mishap
    DISPARAGING = "DISPARAGING"      # associated with harm, crime, illness, contempt


class DetectedElement(BaseModel):
    id: str
    label: str
    element_type: ElementType
    description: str
    time_ranges: list[TimeRange]
    prominence: Prominence
    bbox: BBox | None = None
    at_s: float | None = None
    depiction: DepictionTone | None = None


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


class ResearchTier(str, Enum):
    """Which rung of the escalation ladder answered this finding.

    Ordered cheapest-first. A finding enters at LOCAL and stops at the first
    rung that can genuinely answer it, so only DEEP costs minutes.
    """

    LOCAL = "LOCAL"        # local rights table — 0ms, $0
    STATUTE = "STATUTE"    # deterministic law — 0ms, $0
    SEARCH = "SEARCH"      # Parallel Search — ~2s, $0.005
    DEEP = "DEEP"          # Parallel Task — minutes, $0.01-0.30
    BLOCKED = "BLOCKED"    # disputed identity; research would be meaningless


class ResearchRoute(BaseModel):
    """How one finding will be resolved, and why.

    `disposition` and `basis` exist so a cheap route is never a silent skip:
    the dossier can state what the producer must actually DO about a finding
    that cost nothing to resolve, and under what authority.
    """

    element_id: str
    tier: ResearchTier
    rationale: str
    basis: str = ""
    disposition: str = ""
    owner: str | None = None
    posture: LicensingPosture | None = None
    est_cost_usd: float = 0.0
    est_latency_s: float = 0.0
    enumerate_candidates: bool = False


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


class RightsType(str, Enum):
    """Which half (or which kind) of a right a grant actually conveys.

    Music needs TWO licences from two different holders: the synchronisation
    licence for the composition (publisher) and the master-use licence for the
    recording (label). Holding one and shipping on it is the most common music
    clearance failure in the industry, and it was previously unrepresentable
    here — `scope` was free text, so a sync-only grant read as full coverage.
    """

    ALL = "ALL"          # grant does not distinguish; the default
    SYNC = "SYNC"        # composition, from the publisher
    MASTER = "MASTER"    # sound recording, from the label
    BOTH = "BOTH"        # one paper covering composition and recording
    PRINT = "PRINT"      # reproduction of artwork or a photograph


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
    rights_type: RightsType = RightsType.ALL
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
    use_context: UseContext = UseContext.EXPRESSIVE
    sponsors: list[str] = Field(default_factory=list)
    # Where this will be published. Defaults to "none" — theatrical, festival
    # or broadcast delivery — because no automated enforcement exists there,
    # which makes clearance more important rather than less: there is no
    # takedown to react to, only a distributor rejecting delivery.
    platform: str = "none"
    distribution: list[str] = Field(
        default_factory=lambda: ["THEATRICAL", "STREAMING"]
    )
    has_media: bool = False


class SponsorConflict(BaseModel):
    """A competitor's mark in shot while a sponsor is paying for the production.

    Not an infringement at all — a contract problem. Brand deals routinely carry
    category exclusivity, so a rival logo can void the fee even though showing
    it is perfectly lawful. Nothing else in this pipeline would flag it, because
    nothing is being infringed.
    """

    element_id: str
    label: str
    detected_owner: str
    conflicts_with: str
    sector: str
    note: str


class DetectionMethod(str, Enum):
    """HOW a platform would find this — which decides whether it will."""

    AUDIO_FINGERPRINT = "AUDIO_FINGERPRINT"   # automated, at industrial scale
    VIDEO_FINGERPRINT = "VIDEO_FINGERPRINT"   # automated, for reused footage
    HUMAN_REPORT = "HUMAN_REPORT"             # only if someone notices and files
    NOT_DETECTED = "NOT_DETECTED"


class PlatformAction(str, Enum):
    """What the platform does — which is not what a court would do.

    In 2025 YouTube processed 2.5 billion Content ID claims, 99%+ automated,
    and rights holders chose to MONETISE over 90% of them. The dominant outcome
    is not removal, it is revenue diversion — and the system does not evaluate
    fair use, so a perfect legal argument does not prevent the claim.
    """

    CLAIM_LIKELY = "CLAIM_LIKELY"              # automated match; revenue diverted
    CLAIM_POSSIBLE = "CLAIM_POSSIBLE"          # may match; identity unconfirmed
    MANUAL_COMPLAINT = "MANUAL_COMPLAINT"      # only if a human notices and files
    PRIVACY_COMPLAINT = "PRIVACY_COMPLAINT"    # a person, not a rights holder
    NO_PLATFORM_ACTION = "NO_PLATFORM_ACTION"


class PlatformOutcome(BaseModel):
    """What happens to this finding when the video is published.

    Deliberately separate from `RiskAssessment`. Risk scores how likely you are
    to LOSE; this scores how likely you are to be CAUGHT, and the two invert: a
    background mural carries real legal weight and is almost never detected,
    while a twelve-second music bed has an excellent fair-use argument and is
    caught essentially every time.
    """

    element_id: str
    platform: str
    action: PlatformAction
    confidence: str
    detected_by: DetectionMethod
    consequence: str
    remedy: str
    revenue_impact: str = ""


class PlatformPolicy(BaseModel):
    """How one platform enforces. Data, not code — see data/platforms.json."""

    key: str
    name: str
    audio_matching: bool
    video_matching: bool
    considers_fair_use: bool
    strikes_to_termination: int | None
    strike_expiry_days: int | None
    default_claim_outcome: str
    trademark_complaint: str
    privacy_complaint: str
    note: str = ""


class ExposureKind(str, Enum):
    """On-screen exposure that is not intellectual property at all.

    A creator filming at home who leaves a delivery label, a bank statement or
    a laptop screen in frame has a real problem no clearance tool looks for,
    because nothing is being infringed. It is the purest unknown-unknown in the
    threat surface — and it comes free from a scan already being run.
    """

    MINOR = "MINOR"                            # a child, identifiable
    PERSONAL_DATA = "PERSONAL_DATA"            # address, phone, email, account number
    DOCUMENT = "DOCUMENT"                      # letter, statement, ID, contract
    SCREEN_CONTENT = "SCREEN_CONTENT"          # phone or monitor showing private content
    VEHICLE_PLATE = "VEHICLE_PLATE"            # registration plate
    LOCATION_IDENTIFIER = "LOCATION_IDENTIFIER"  # house number, street sign at a home


class ExposureFinding(BaseModel):
    """One thing on screen that should probably not be published."""

    id: str
    kind: ExposureKind
    description: str
    time_ranges: list[TimeRange]
    bbox: BBox | None = None


class AssessedExposure(BaseModel):
    """An exposure with its severity, the regime that governs it, and the fix."""

    id: str
    kind: ExposureKind
    description: str
    time_ranges: list[TimeRange]
    bbox: BBox | None = None
    territory: str
    regime: str
    score: int = Field(ge=0, le=100)
    band: RiskBand
    rationale: str
    remedy: str


class PreviewFinding(BaseModel):
    """One finding as it stands BEFORE any rights research has run.

    Everything here is derivable from the footage alone — what it is, when it
    appears, where in frame, how exposed the production is by prominence, and
    which jurisdiction bands it worst. The only thing missing is who owns it.

    That distinction is worth a stage of its own. On a live 30-second clip the
    footage-derived picture was complete at ~90 seconds while the run took 9m43s,
    because deep ownership research on the two or three findings that genuinely
    need it is minutes long by nature. Making an editor wait for the slowest
    rights lookup before seeing which shots to pull is a UI decision, not a
    technical constraint.
    """

    element_id: str
    label: str
    category: ClearanceCategory
    time_ranges: list[TimeRange]
    bbox: BBox | None = None
    at_s: float | None = None
    provisional_score: int
    provisional_band: RiskBand
    identity: IdentityVerdict | None = None
    depiction: DepictionTone | None = None
    territory: list[TerritoryRisk] = Field(default_factory=list)
    route_tier: ResearchTier
    disposition: str = ""
    awaiting_research: bool = False


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
    routes: dict[str, ResearchRoute] = Field(default_factory=dict)
    sponsor_conflicts: list[SponsorConflict] = Field(default_factory=list)
    platform_outcomes: list[PlatformOutcome] = Field(default_factory=list)
    # element id -> list of {territory, name, available, authority, note}.
    # Stored untyped because `territory.Defence` imports from this module.
    defences: dict[str, list[dict]] = Field(default_factory=dict)
    exposures: list[ExposureFinding] = Field(default_factory=list)
    assessed_exposures: list[AssessedExposure] = Field(default_factory=list)
    preview: list[PreviewFinding] = Field(default_factory=list)
    detector_hits: list[DetectorHit] = Field(default_factory=list)
