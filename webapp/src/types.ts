export type RiskBand = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Action = "approve_risk" | "license" | "blur" | "reshoot" | "escalate";
export type Role = "legal" | "producer" | "editor";

export interface TimeRange {
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
  sponsor_conflicts: SponsorConflict[];
  freshness: Record<string, FreshnessSignal[]>;
  territory_risk: Record<string, TerritoryRisk[]>;
  territories: string[];
  coverage: Record<string, Coverage>;
}
