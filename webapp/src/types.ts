export type RiskBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Action = "approve_risk" | "license" | "blur" | "reshoot" | "escalate";
export type Role = "legal" | "producer" | "editor";

export interface TimeRange {
  // One box per APPEARANCE. An element in four shots needs four rectangles;
  // reusing one across all of them points a reviewer at empty screen.
  bbox?: BBox | null;
  start_s: number;
  end_s: number;
}

export interface Prominence {
  screen_time_s: number;
  frame_coverage: number;
  centrality: number;
  plot_integral: boolean;
}

export interface BBox {
  ymin: number;
  xmin: number;
  ymax: number;
  xmax: number;
}

export interface Element {
  id: string;
  label: string;
  element_type: string;
  description: string;
  category: string;
  time_ranges: TimeRange[];
  prominence: Prominence;
  bbox: BBox | null;
  at_s: number | null;
  depiction: DepictionTone | null;
  /**
   * False when the scan's timecodes are physically impossible — appearances
   * shorter than one frame, or past the end of the clip. The finding stands;
   * only its timing is unusable, so no box is drawn and the reason is shown
   * instead of a rectangle nobody can pause on.
   */
  timing_reliable?: boolean;
  // A graphic the production authored itself — subtitles, captions, a lower
  // third. Listed as a finding, never boxed: its route already says "No
  // action. Recorded so the dossier is complete, not because it is a risk."
  own_content?: boolean;
  timing_note?: string;
}

export type DepictionTone =
  | "FAVOURABLE"
  | "NEUTRAL"
  | "UNFLATTERING"
  | "DISPARAGING";

export interface SponsorConflict {
  element_id: string;
  label: string;
  detected_owner: string;
  conflicts_with: string;
  sector: string;
  note: string;
}

export interface ProductionSummary {
  id: string;
  title: string;
  stage_status: Record<string, string>;
  updated_at: number;
  running: boolean;
  /** Unfinished, and nothing is working on it — the run died with its process. */
  interrupted?: boolean;
}

export interface PreviewFinding {
  element_id: string;
  label: string;
  category: string;
  provisional_score: number;
  provisional_band: string;
  identity: string | null;
  depiction: string | null;
  route_tier: string;
  disposition: string;
  awaiting_research: boolean;
}

export interface LiabilityEstimate {
  element_id: string;
  headline: string;
  clear_now: string | null;
  fix_in_post: string | null;
  statutory_min_usd: number | null;
  statutory_max_usd: number | null;
  statutory_willful_usd: number | null;
  statutory_basis: string;
  injunction_risk: string;
  injunction_basis: string;
  escalation: string[];
}

export interface PlatformOutcome {
  element_id: string;
  platform: string;
  action: string;
  confidence: string;
  detected_by: string;
  consequence: string;
  remedy: string;
  revenue_impact: string;
}

export interface AssessedExposure {
  id: string;
  kind: string;
  description: string;
  time_ranges: TimeRange[];
  territory: string;
  regime: string;
  score: number;
  band: string;
  rationale: string;
  remedy: string;
}

export type ResearchTier =
  | "LOCAL"
  | "STATUTE"
  | "SEARCH"
  | "DEEP"
  | "BLOCKED";

export interface ResearchRoute {
  element_id: string;
  tier: ResearchTier;
  rationale: string;
  basis: string;
  disposition: string;
  owner: string | null;
  posture: string | null;
  est_cost_usd: number;
  est_latency_s: number;
  enumerate_candidates: boolean;
}

export type IdentityVerdict =
  | "FINGERPRINTED"
  | "CORROBORATED"
  | "SINGLE_SOURCE"
  | "CONFLICTED";

export interface Corroboration {
  element_id: string;
  verdict: IdentityVerdict;
  detector: string;
  detected_label: string | null;
  confidence: number;
  note: string;
}

export interface FreshnessSignal {
  element_id: string;
  owner: string;
  title: string;
  url: string;
  excerpt: string;
  material: boolean;
}

export type CoverageStatus = "COVERED" | "PARTIAL" | "NOT_COVERED" | "UNKNOWN";

export interface Coverage {
  element_id: string;
  status: CoverageStatus;
  licence_id: string | null;
  rights_holder: string | null;
  gaps: string[];
  note: string;
}

export interface LicenceGrant {
  id: string;
  rights_holder: string;
  work: string;
  scope: string;
  territories: string[];
  media: string[];
  starts: string;
  expires: string | null;
  reference: string;
  notes: string;
}

export interface TerritoryRisk {
  element_id: string;
  territory: string;
  band: RiskBand;
  rationale: string;
  authority: string;
}

export interface BasisCitation {
  field: string;
  url: string;
  excerpt: string;
  reasoning: string;
  confidence: string;
}

export interface Research {
  element_id: string;
  owner: string | null;
  owner_confidence: string;
  licensing_contact: string | null;
  licensing_posture: string;
  litigation_history: string[];
  estimated_license_cost_band: string | null;
  basis: BasisCitation[];
  status: "complete" | "incomplete";
}

export interface Risk {
  element_id: string;
  score: number;
  band: RiskBand;
  factors: Record<string, number>;
  de_minimis: boolean;
}

export interface RemediationOption {
  kind: "license" | "blur" | "reshoot" | "fair_use_memo";
  summary: string;
  detail: string;
  est_cost_band: string | null;
}

export interface Decision {
  element_id: string;
  action: Action;
  reviewer: string;
  role: string;
  note: string;
}

export interface Precedent {
  case_name: string;
  citation: string;
  holding: string;
  relevance: string;
  quote: string;
  source_url: string;
}

export interface ScriptDrift {
  unscripted_element_ids: string[];
  scripted_not_seen: string[];
}

export interface CandidateEntity {
  name: string;
  kind: string;
  url: string;
  note: string;
}

export interface ClearanceWatch {
  element_id: string;
  monitor_id: string;
  query: string;
  frequency: string;
}

export interface WatchAlert {
  element_id: string;
  monitor_id: string;
  at: string;
  summary: string;
  source_url: string;
}

export interface CourtBrief {
  side: "counsel" | "advocate";
  argument: string;
  precedents: Precedent[];
}

export type CourtHolding = "clear_required" | "defensible" | "escalate";

export interface CourtOpinion {
  element_id: string;
  holding: CourtHolding;
  confidence: string;
  reasoning: string;
  briefs: CourtBrief[];
}

export interface ResearchPlan {
  element_id: string;
  processor: "lite" | "base" | "pro" | "ultra";
  rationale: string;
  est_cost_usd: number;
}

export interface PipelineEvent {
  type: string;
  detected_label?: string | null;
  material?: number;
  signals?: number;
  divergent?: number;
  territories?: number;
  FINGERPRINTED?: number;
  CORROBORATED?: number;
  SINGLE_SOURCE?: number;
  CONFLICTED?: number;
  stage?: string;
  element_id?: string;
  label?: string;
  processor?: string;
  status?: string;
  owner?: string | null;
  holding?: CourtHolding;
  count?: number;
  total_est_cost_usd?: number;
  deep_runs?: number;
  awaiting_research?: number;
  conflicts_with?: string;
  sector?: string;
  resolved_now?: number;
  findings?: {
    element_id: string;
    label: string;
    category: string;
    band: string;
    score: number;
    tier: string;
    identity: string | null;
    start_s: number | null;
    awaiting_research: boolean;
  }[];
  routes?: Record<string, number>;
  tier?: string;
}

/**
 * A face the scan attributed to a named performer.
 *
 * Not an Element: it carries no category, no band and no route, because the
 * production engaged this person. Held apart so it is never drawn on the
 * frame — asked to place a named performer, the model answers with the whole
 * frame, and that rectangle sat on top of every real finding.
 */
export interface CastCredit {
  id: string;
  label: string;
  character: string | null;
  performer: string;
  screen_time_s: number;
  basis: string;
}

export interface ProductionState {
  production: {
    id: string;
    title: string;
    footage_uri: string;
    fps: number;
    duration_s: number;
    release_territories: string[];
    distribution: string[];
    has_media: boolean;
    media_version: string;
  };
  stage_status: Record<string, string>;
  elements: Element[];
  research: Record<string, Research>;
  risk: Record<string, Risk>;
  remediation: Record<string, RemediationOption[]>;
  decisions: Record<string, Decision>;
  unscanned_ranges: TimeRange[];
  court: Record<string, CourtOpinion>;
  research_plan: Record<string, ResearchPlan>;
  drift: ScriptDrift | null;
  candidates: Record<string, CandidateEntity[]>;
  watches: Record<string, ClearanceWatch>;
  alerts: WatchAlert[];
  corroboration: Record<string, Corroboration>;
  routes: Record<string, ResearchRoute>;
  liability: Record<string, LiabilityEstimate>;
  preview: PreviewFinding[];
  sponsor_conflicts: SponsorConflict[];
  assessed_exposures: AssessedExposure[];
  platform_outcomes: PlatformOutcome[];
  freshness: Record<string, FreshnessSignal[]>;
  territory_risk: Record<string, TerritoryRisk[]>;
  territories: string[];
  coverage: Record<string, Coverage>;
  cast: CastCredit[];
  subsumed_ids: string[];
  source_work_summary: {
    title: string;
    rights_holder: string | null;
    confidence: string;
    subsumed: number;
    independent: number;
    headline: string;
    action: string;
    caveat: string;
  } | null;
}
