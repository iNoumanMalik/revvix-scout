import { accessToken } from "./auth";
import { listQuery } from "./query";
import type {
  DashboardFilters,
  IndividualCandidate,
  LeadDetail,
  LeadPage,
  OpportunityAnalysisRun,
  OpportunityHypothesis,
  ReviewQueuePage,
  SessionView,
} from "./types";

async function request<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const token = await accessToken();
  let requestInit = init;
  if (token) {
    const headers = new Headers(init?.headers);
    headers.set("authorization", `Bearer ${token}`);
    requestInit = { ...init, headers };
  }
  const response = await fetch(input, requestInit);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchSession(): Promise<SessionView> {
  return request<SessionView>("/v1/session");
}

export function fetchReviewQueue(): Promise<ReviewQueuePage> {
  return request<ReviewQueuePage>("/v1/review-queue?limit=200");
}

export function fetchIndividualCandidate(candidateId: string): Promise<IndividualCandidate> {
  return request<IndividualCandidate>(
    `/v1/individual-candidates/${encodeURIComponent(candidateId)}`,
  );
}

export function reviewIndividualCandidate(
  candidateId: string,
  action: "promote_new" | "link_existing" | "reject",
  reason: string,
  personId?: string,
): Promise<unknown> {
  return request(`/v1/individual-candidates/${encodeURIComponent(candidateId)}/review`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      action,
      person_id: action === "link_existing" ? personId : undefined,
      reason,
    }),
  });
}

export function reviewEntityMatch(
  candidateId: string,
  action: "merge" | "reject",
  survivorId?: string,
): Promise<unknown> {
  return request(`/v1/entity-match-candidates/${encodeURIComponent(candidateId)}/review`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      action,
      survivor_id: action === "merge" ? survivorId : undefined,
      reason: `Operator ${action === "merge" ? "confirmed" : "rejected"} this fictional duplicate suggestion.`,
    }),
  });
}

export function fetchLeads(filters: DashboardFilters, cursor?: string): Promise<LeadPage> {
  return request<LeadPage>(`/v1/leads?${listQuery(filters, cursor)}`);
}

export function fetchLead(leadId: string): Promise<LeadDetail> {
  return request<LeadDetail>(`/v1/leads/${encodeURIComponent(leadId)}`);
}

export function runOpportunityAnalysis(leadId: string): Promise<OpportunityAnalysisRun> {
  return request<OpportunityAnalysisRun>(
    `/v1/leads/${encodeURIComponent(leadId)}/opportunity-analysis-runs`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        provider_key: "fictional_opportunity_analyzer",
        idempotency_key: `dashboard-${crypto.randomUUID()}`,
      }),
    },
  );
}

export async function fetchLatestOpportunityAnalysis(
  leadId: string,
): Promise<OpportunityAnalysisRun | null> {
  const token = await accessToken();
  const headers = new Headers();
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(
    `/v1/leads/${encodeURIComponent(leadId)}/opportunity-analysis-runs/latest`,
    token ? { headers } : undefined,
  );
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
  return (await response.json()) as OpportunityAnalysisRun;
}

export function reviewOpportunity(
  hypothesisId: string,
  decision: "accept" | "reject",
): Promise<OpportunityHypothesis> {
  return request<OpportunityHypothesis>(
    `/v1/opportunity-hypotheses/${encodeURIComponent(hypothesisId)}/review`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        decision,
        reason: `Operator ${decision}ed this hypothesis in the Scout dashboard.`,
      }),
    },
  );
}

export function reverseOpportunityReview(
  hypothesisId: string,
): Promise<OpportunityHypothesis> {
  return request<OpportunityHypothesis>(
    `/v1/opportunity-hypotheses/${encodeURIComponent(hypothesisId)}/review/reverse`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        reason: "Operator reopened this advisory hypothesis for correction in the Scout dashboard.",
      }),
    },
  );
}

export function exportUrl(filters: DashboardFilters): string {
  const params = new URLSearchParams();
  if (filters.disposition) params.set("disposition", filters.disposition);
  if (filters.minScore) params.set("min_score", filters.minScore);
  const query = params.toString();
  return `/v1/leads/export.csv${query ? `?${query}` : ""}`;
}

export async function downloadExport(filters: DashboardFilters): Promise<void> {
  const token = await accessToken();
  const headers = new Headers();
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(exportUrl(filters), token ? { headers } : undefined);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Export failed with status ${response.status}`);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = "revvix-scout-leads.csv";
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}
