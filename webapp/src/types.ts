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

export interface Element {
  id: string;
  label: string;
  element_type: string;
  description: string;
  category: string;
  time_ranges: TimeRange[];
  prominence: Prominence;
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
  stage?: string;
  element_id?: string;
  label?: string;
  processor?: string;
  status?: string;
  owner?: string | null;
  holding?: CourtHolding;
  count?: number;
  total_est_cost_usd?: number;
}

export interface ProductionState {
  production: {
    id: string;
    title: string;
    footage_uri: string;
    fps: number;
    duration_s: number;
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
}
