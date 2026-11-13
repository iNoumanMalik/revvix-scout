export type Disposition = "qualified" | "review" | "unqualified" | "disqualified";

export interface LeadListItem {
  id: string;
  company_id: string;
  company_name: string;
  normalized_domain: string | null;
  country_code: string | null;
  industry: string | null;
  employee_count: number | null;
  match_status: string;
  disposition: Disposition;
  score: number;
  created_at: string;
}

export interface LeadPage {
  items: LeadListItem[];
  next_cursor: string | null;
}

export interface ScoreComponent {
  rule_key: string;
  points: number;
  maximum_points: number;
  result: string;
  explanation: string;
  evidence_claim_ids: string[];
}

export interface ScoreDetail {
  id: string;
  icp_version_id: string;
  algorithm_version: string;
  total_score: number;
  maximum_score: number;
  normalized_score: number;
  disposition: string;
  missing_fields: string[];
  scored_at: string;
  components: ScoreComponent[];
}

export type EvidenceClassification =
  | "observed"
  | "provider_asserted"
  | "inferred"
  | "human_verified";

export interface EvidenceClaim {
  id: string;
  claim_type: string;
  value: unknown;
  classification: EvidenceClassification;
  confidence: number;
  verification_status: string;
  source_url: string;
  source_record_id: string;
  observed_at: string;
  retrieved_at: string;
}

export interface LeadDetail extends LeadListItem {
  icp_version_id: string;
  stage: string;
  score_detail: ScoreDetail;
  evidence: EvidenceClaim[];
}

export interface OpportunityHypothesis {
  id: string;
  category: string;
  title: string;
  summary: string;
  confidence: number;
  review_status: string;
  citation_claim_ids: string[];
  missing_fields: string[];
  contradictions: string[];
}

export interface OpportunityAnalysisRun {
  id: string;
  lead_id: string;
  provider_key: string;
  status: string;
  prompt_key: string;
  prompt_version: number;
  output_schema_version: number;
  taxonomy_version: number;
  model_name: string | null;
  model_version: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  injection_detected: boolean;
  excluded_claim_ids: string[];
  missing_fields: string[];
  contradictions: string[];
  error_code: string | null;
  error_message: string | null;
  hypotheses: OpportunityHypothesis[];
}

export interface DashboardFilters {
  disposition: Disposition | "";
  minScore: string;
}

export interface SessionView {
  user_id: string;
  workspace_id: string;
  role: "owner" | "admin" | "operator" | "reviewer" | "viewer" | "automation";
  display_name: string;
  auth_mode: "development" | "supabase";
  capabilities: Array<"read" | "export" | "ingest" | "run_pipeline" | "review" | "privacy">;
}

export type DashboardView = "leads" | "reviews";

export type ReviewQueueKind =
  | "business_lead"
  | "individual_candidate"
  | "entity_match"
  | "opportunity_hypothesis";

export interface ReviewQueueItem {
  id: string;
  kind: ReviewQueueKind;
  title: string;
  summary: string;
  status: string;
  created_at: string;
  primary_subject_id: string;
  secondary_subject_id: string | null;
  lead_id: string | null;
  source_url: string | null;
  score: number | null;
  possible_match_person_id: string | null;
  allowed_actions: string[];
}

export interface ReviewQueuePage {
  items: ReviewQueueItem[];
  counts: Record<string, number>;
}

export interface IndividualCandidate {
  id: string;
  provider_record_id: string;
  display_name: string;
  professional_profile_url: string;
  normalized_profile_url: string;
  persona: string | null;
  country_code: string | null;
  region: string | null;
  service_summary: string | null;
  has_professional_presence: boolean;
  has_business_relevance: boolean;
  is_fictional: boolean;
  source_url: string;
  observed_at: string;
  status: string;
  disposition: string;
  score: number;
  maximum_score: number;
  rejection_reason: string | null;
  possible_match_person_id: string | null;
  duplicate_person_id: string | null;
  evidence_classification: EvidenceClassification;
}
