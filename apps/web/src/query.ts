import type { DashboardFilters, DashboardView, Disposition } from "./types";

const dispositions = new Set<Disposition>([
  "qualified",
  "review",
  "unqualified",
  "disqualified",
]);

export function readDashboardState(search: string): {
  filters: DashboardFilters;
  leadId: string | null;
  view: DashboardView;
} {
  const params = new URLSearchParams(search);
  const rawDisposition = params.get("disposition") ?? "";
  const disposition = dispositions.has(rawDisposition as Disposition)
    ? (rawDisposition as Disposition)
    : "";
  const rawScore = params.get("min_score") ?? "";
  const minScore = /^\d{1,3}$/.test(rawScore) && Number(rawScore) <= 100 ? rawScore : "";
  return {
    filters: { disposition, minScore },
    leadId: params.get("lead"),
    view: params.get("view") === "reviews" ? "reviews" : "leads",
  };
}

export function writeDashboardState(
  filters: DashboardFilters,
  leadId: string | null,
  view: DashboardView = "leads",
): string {
  const params = new URLSearchParams();
  if (filters.disposition) params.set("disposition", filters.disposition);
  if (filters.minScore) params.set("min_score", filters.minScore);
  if (leadId) params.set("lead", leadId);
  if (view === "reviews") params.set("view", view);
  const query = params.toString();
  return query ? `?${query}` : window.location.pathname;
}

export function listQuery(filters: DashboardFilters, cursor?: string): string {
  const params = new URLSearchParams({ limit: "25" });
  if (filters.disposition) params.set("disposition", filters.disposition);
  if (filters.minScore) params.set("min_score", filters.minScore);
  if (cursor) params.set("cursor", cursor);
  return params.toString();
}
