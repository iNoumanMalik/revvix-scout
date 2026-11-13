import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  downloadExport,
  fetchLatestOpportunityAnalysis,
  fetchLead,
  fetchLeads,
  fetchIndividualCandidate,
  fetchReviewQueue,
  fetchSession,
  reviewEntityMatch,
  reviewIndividualCandidate,
  reviewOpportunity,
  reverseOpportunityReview,
  runOpportunityAnalysis,
} from "./api";
import {
  browserAuthConfigured,
  observeBrowserSession,
  signIn,
  signOut,
} from "./auth";
import { readDashboardState, writeDashboardState } from "./query";
import type {
  DashboardFilters,
  DashboardView,
  EvidenceClassification,
  IndividualCandidate,
  LeadDetail,
  LeadListItem,
  OpportunityAnalysisRun,
  OpportunityHypothesis,
  ReviewQueueItem,
  ReviewQueuePage,
  SessionView,
} from "./types";

const initial = readDashboardState(window.location.search);

export default function App({ authRequired = browserAuthConfigured }: { authRequired?: boolean }) {
  const [browserReady, setBrowserReady] = useState(!authRequired);
  const [hasBrowserSession, setHasBrowserSession] = useState(!authRequired);

  useEffect(() => {
    if (!authRequired) {
      setBrowserReady(true);
      setHasBrowserSession(true);
      return () => undefined;
    }
    return observeBrowserSession((session) => {
        setHasBrowserSession(Boolean(session));
        setBrowserReady(true);
      });
  }, [authRequired]);

  if (!browserReady) return <FullPageStatus message="Restoring your secure session…" />;
  if (!hasBrowserSession) return <SignInScreen />;
  return <SessionGate />;
}

function SessionGate() {
  const [actor, setActor] = useState<SessionView | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchSession()
      .then((value) => active && setActor(value))
      .catch((reason: unknown) => active && setSessionError(messageFor(reason)));
    return () => {
      active = false;
    };
  }, []);

  if (sessionError) return <FullPageStatus message={sessionError} error />;
  if (!actor) return <FullPageStatus message="Authorizing workspace access…" />;
  return <Dashboard actor={actor} />;
}

function Dashboard({ actor }: { actor: SessionView }) {
  const canExport = actor.capabilities.includes("export");
  const canReview = actor.capabilities.includes("review");
  const canRunPipeline = actor.capabilities.includes("run_pipeline");
  const [view, setView] = useState<DashboardView>(initial.view);
  const [filters, setFilters] = useState<DashboardFilters>(initial.filters);
  const [draftFilters, setDraftFilters] = useState<DashboardFilters>(initial.filters);
  const [leads, setLeads] = useState<LeadListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(initial.leadId);
  const [detail, setDetail] = useState<LeadDetail | null>(null);
  const [analysis, setAnalysis] = useState<OpportunityAnalysisRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [reviewQueue, setReviewQueue] = useState<ReviewQueuePage | null>(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [resolvingReviewId, setResolvingReviewId] = useState<string | null>(null);
  const [selectedIndividualId, setSelectedIndividualId] = useState<string | null>(null);
  const [individualDetail, setIndividualDetail] = useState<IndividualCandidate | null>(null);
  const [individualLoading, setIndividualLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetchLeads(filters)
      .then((page) => {
        if (!active) return;
        setLeads(page.items);
        setNextCursor(page.next_cursor);
      })
      .catch((reason: unknown) => active && setError(messageFor(reason)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [filters]);

  useEffect(() => {
    if (view !== "reviews") return;
    let active = true;
    setReviewLoading(true);
    setError(null);
    fetchReviewQueue()
      .then((queue) => active && setReviewQueue(queue))
      .catch((reason: unknown) => active && setError(messageFor(reason)))
      .finally(() => active && setReviewLoading(false));
    return () => {
      active = false;
    };
  }, [view]);

  useEffect(() => {
    if (!selectedIndividualId) {
      setIndividualDetail(null);
      return;
    }
    let active = true;
    setIndividualLoading(true);
    setError(null);
    fetchIndividualCandidate(selectedIndividualId)
      .then((candidate) => active && setIndividualDetail(candidate))
      .catch((reason: unknown) => active && setError(messageFor(reason)))
      .finally(() => active && setIndividualLoading(false));
    return () => {
      active = false;
    };
  }, [selectedIndividualId]);

  useEffect(() => {
    if (!selectedLeadId) {
      setDetail(null);
      setAnalysis(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setError(null);
    Promise.all([fetchLead(selectedLeadId), fetchLatestOpportunityAnalysis(selectedLeadId)])
      .then(([lead, latest]) => {
        if (!active) return;
        setDetail(lead);
        setAnalysis(latest);
      })
      .catch((reason: unknown) => active && setError(messageFor(reason)))
      .finally(() => active && setDetailLoading(false));
    return () => {
      active = false;
    };
  }, [selectedLeadId]);

  useEffect(() => {
    const onPopState = () => {
      const state = readDashboardState(window.location.search);
      setFilters(state.filters);
      setDraftFilters(state.filters);
      setSelectedLeadId(state.leadId);
      setView(state.view);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const metrics = useMemo(() => {
    const qualified = leads.filter((lead) => lead.disposition === "qualified").length;
    const review = leads.filter(
      (lead) => lead.disposition === "review" || lead.match_status === "needs_review",
    ).length;
    const average = leads.length
      ? Math.round(leads.reduce((total, lead) => total + lead.score, 0) / leads.length)
      : 0;
    return { qualified, review, average };
  }, [leads]);

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilters(draftFilters);
    window.history.pushState({}, "", writeDashboardState(draftFilters, selectedLeadId, view));
  }

  function selectLead(leadId: string) {
    setSelectedLeadId(leadId);
    window.history.pushState({}, "", writeDashboardState(filters, leadId, view));
  }

  function closeDetail() {
    setSelectedLeadId(null);
    window.history.pushState({}, "", writeDashboardState(filters, null, view));
  }

  function selectView(nextView: DashboardView) {
    setView(nextView);
    window.history.pushState(
      {},
      "",
      writeDashboardState(filters, nextView === "leads" ? selectedLeadId : null, nextView),
    );
  }

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await fetchLeads(filters, nextCursor);
      setLeads((current) => [...current, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setLoadingMore(false);
    }
  }

  async function analyzeLead() {
    if (!detail || analysisLoading) return;
    setAnalysisLoading(true);
    setError(null);
    try {
      setAnalysis(await runOpportunityAnalysis(detail.id));
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setAnalysisLoading(false);
    }
  }

  async function decideHypothesis(
    hypothesis: OpportunityHypothesis,
    decision: "accept" | "reject",
  ) {
    try {
      const updated = await reviewOpportunity(hypothesis.id, decision);
      setAnalysis((current) =>
        current
          ? {
              ...current,
              hypotheses: current.hypotheses.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
    } catch (reason) {
      setError(messageFor(reason));
    }
  }

  async function reopenHypothesis(hypothesis: OpportunityHypothesis) {
    try {
      const updated = await reverseOpportunityReview(hypothesis.id);
      setAnalysis((current) =>
        current
          ? {
              ...current,
              hypotheses: current.hypotheses.map((item) =>
                item.id === updated.id ? updated : item,
              ),
            }
          : current,
      );
    } catch (reason) {
      setError(messageFor(reason));
    }
  }

  async function exportLeads() {
    if (exportLoading) return;
    setExportLoading(true);
    setError(null);
    try {
      await downloadExport(filters);
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setExportLoading(false);
    }
  }

  async function resolveReview(item: ReviewQueueItem, action: string) {
    if (resolvingReviewId || !canReview) return;
    setResolvingReviewId(item.id);
    setError(null);
    try {
      if (item.kind === "entity_match") {
        const survivor = action === "merge_left"
          ? item.primary_subject_id
          : item.secondary_subject_id ?? undefined;
        await reviewEntityMatch(item.id, action === "reject" ? "reject" : "merge", survivor);
      } else if (item.kind === "opportunity_hypothesis") {
        await reviewOpportunity(item.id, action as "accept" | "reject");
      }
      setReviewQueue(await fetchReviewQueue());
    } catch (reason) {
      setError(messageFor(reason));
    } finally {
      setResolvingReviewId(null);
    }
  }

  async function resolveIndividual(
    candidate: IndividualCandidate,
    action: "promote_new" | "link_existing" | "reject",
    reason: string,
  ) {
    if (resolvingReviewId || !canReview) return;
    setResolvingReviewId(candidate.id);
    setError(null);
    try {
      await reviewIndividualCandidate(
        candidate.id,
        action,
        reason,
        candidate.possible_match_person_id ?? undefined,
      );
      setReviewQueue(await fetchReviewQueue());
      setSelectedIndividualId(null);
    } catch (reviewError) {
      setError(messageFor(reviewError));
    } finally {
      setResolvingReviewId(null);
    }
  }

  function openReviewLead(item: ReviewQueueItem) {
    if (!item.lead_id) return;
    setView("leads");
    setSelectedLeadId(item.lead_id);
    window.history.pushState({}, "", writeDashboardState(filters, item.lead_id, "leads"));
  }

  return (
    <div className="min-h-screen bg-[var(--canvas)] text-[var(--ink)]">
      <div className="dashboard-background" inert={Boolean(selectedLeadId || selectedIndividualId)}>
      <header className="topbar">
        <div className="brand-lockup" aria-label="Revvix Scout">
          <span className="brand-mark" aria-hidden="true">R</span>
          <span>
            <strong>Revvix</strong>
            <span className="brand-product">Scout</span>
          </span>
        </div>
        <div className="topbar-context">
          <span className="environment-pill"><span aria-hidden="true" /> {actor.auth_mode === "development" ? "Local development" : "Authenticated"}</span>
          <span className="workspace-label">Revvix AI workspace</span>
          {actor.auth_mode === "supabase" ? (
            <button className="avatar" type="button" onClick={() => void signOut()} aria-label={`Sign out ${actor.display_name}`}>{initials(actor.display_name)}</button>
          ) : (
            <span className="avatar avatar-static" title={`${actor.display_name} · ${actor.role}`}>{initials(actor.display_name)}</span>
          )}
        </div>
      </header>

      <div className="app-shell">
        <nav className="sidebar" aria-label="Primary navigation">
          <p className="nav-label">Workspace</p>
          <button className={`nav-item ${view === "leads" ? "nav-item-active" : ""}`} type="button" onClick={() => selectView("leads")} aria-current={view === "leads" ? "page" : undefined}>
            <GridIcon /> Lead intelligence
          </button>
          <button className={`nav-item ${view === "reviews" ? "nav-item-active" : ""}`} type="button" onClick={() => selectView("reviews")} aria-current={view === "reviews" ? "page" : undefined}>
            <QueueIcon /> Review queues {reviewQueue && <small>{reviewQueue.items.length}</small>}
          </button>
          <span className="nav-item nav-item-disabled" aria-disabled="true">
            <PulseIcon /> Usage & jobs <small>M9</small>
          </span>
          <div className="sidebar-note">
            <span className="note-icon" aria-hidden="true">i</span>
            <p><strong>Safe development mode</strong>Live providers and outreach are disabled.</p>
          </div>
        </nav>

        <label className="mobile-view-switcher">
          <span>Workspace view</span>
          <select
            aria-label="Mobile workspace view"
            value={view}
            onChange={(event) => selectView(event.target.value as DashboardView)}
          >
            <option value="leads">Lead intelligence</option>
            <option value="reviews">Review queues</option>
          </select>
        </label>

        <main id="main-content" className="main-content" tabIndex={-1}>
          {error && (
            <div className="alert" role="alert">
              <strong>Something needs attention.</strong> {error}
              <button type="button" onClick={() => setError(null)} aria-label="Dismiss error">×</button>
            </div>
          )}
          {view === "leads" ? <>
          <div className="page-heading">
            <div>
              <p className="eyebrow">Lead intelligence</p>
              <h1>Evidence before inference.</h1>
              <p>Review qualified prospects, inspect their source trail, and keep AI hypotheses separate.</p>
            </div>
            <button className="button button-secondary" type="button" onClick={() => void exportLeads()} disabled={exportLoading || !canExport}>
              <DownloadIcon /> {exportLoading ? "Preparing export…" : "Export filtered CSV"}
            </button>
          </div>

          <section className="metric-grid" aria-label="Current page summary">
            <Metric label="Visible leads" value={leads.length} detail="Current filtered page" />
            <Metric label="Qualified" value={metrics.qualified} detail="Ready for operator review" tone="mint" />
            <Metric label="Needs review" value={metrics.review} detail="Evidence or match ambiguity" tone="amber" />
            <Metric label="Average score" value={metrics.average} detail="Deterministic ICP score" suffix="/100" />
          </section>

          <section className="workspace-card" aria-labelledby="lead-table-title">
            <div className="card-header">
              <div>
                <h2 id="lead-table-title">Business leads</h2>
                <p>Newest first · deterministic scoring · source-backed claims</p>
              </div>
              <form className="filter-row" onSubmit={applyFilters} aria-label="Filter leads">
                <label>
                  <span>Disposition</span>
                  <select
                    value={draftFilters.disposition}
                    onChange={(event) =>
                      setDraftFilters((current) => ({
                        ...current,
                        disposition: event.target.value as DashboardFilters["disposition"],
                      }))
                    }
                  >
                    <option value="">All dispositions</option>
                    <option value="qualified">Qualified</option>
                    <option value="review">Needs review</option>
                    <option value="unqualified">Unqualified</option>
                    <option value="disqualified">Disqualified</option>
                  </select>
                </label>
                <label>
                  <span>Minimum score</span>
                  <input
                    type="number"
                    inputMode="numeric"
                    min="0"
                    max="100"
                    placeholder="Any"
                    value={draftFilters.minScore}
                    onChange={(event) =>
                      setDraftFilters((current) => ({ ...current, minScore: event.target.value }))
                    }
                  />
                </label>
                <button className="button button-primary" type="submit">Apply filters</button>
              </form>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Company</th>
                    <th scope="col">Profile</th>
                    <th scope="col">Evidence status</th>
                    <th scope="col">ICP score</th>
                    <th scope="col"><span className="sr-only">Open</span></th>
                  </tr>
                </thead>
                <tbody>
                  {loading ? (
                    <TableMessage message="Loading evidence-backed leads…" />
                  ) : leads.length === 0 ? (
                    <TableMessage message="No leads match these filters." />
                  ) : (
                    leads.map((lead) => (
                      <tr key={lead.id} className={selectedLeadId === lead.id ? "row-selected" : ""}>
                        <td>
                          <button className="company-link" type="button" onClick={() => selectLead(lead.id)} aria-label={`View details for ${lead.company_name}`}>
                            <span className="company-monogram" aria-hidden="true">{initials(lead.company_name)}</span>
                            <span><strong>{lead.company_name}</strong><small>{lead.normalized_domain ?? "No domain"}</small></span>
                          </button>
                        </td>
                        <td><strong>{humanize(lead.industry ?? "unknown")}</strong><small>{lead.employee_count ?? "—"} employees · {lead.country_code ?? "—"}</small></td>
                        <td><StatusBadge value={lead.match_status} /></td>
                        <td><Score value={lead.score} /></td>
                        <td><button className="icon-button" type="button" onClick={() => selectLead(lead.id)} aria-label={`Open ${lead.company_name}`}><ChevronIcon /></button></td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            <div className="table-footer">
              <span>{leads.length} lead{leads.length === 1 ? "" : "s"} loaded</span>
              {nextCursor && <button className="button button-secondary" type="button" onClick={loadMore} disabled={loadingMore}>{loadingMore ? "Loading…" : "Load next page"}</button>}
            </div>
          </section>
          </> : <ReviewQueues
            queue={reviewQueue}
            loading={reviewLoading}
            resolvingId={resolvingReviewId}
            readOnly={!canReview}
            onResolve={resolveReview}
            onOpenLead={openReviewLead}
            onInspectIndividual={(item) => setSelectedIndividualId(item.id)}
          />}
        </main>
      </div>
      </div>

      {selectedLeadId && (
        <LeadPanel
          detail={detail}
          analysis={analysis}
          loading={detailLoading}
          analysisLoading={analysisLoading}
          onClose={closeDetail}
          onAnalyze={analyzeLead}
          onDecision={decideHypothesis}
          onReopen={reopenHypothesis}
          canAnalyze={canRunPipeline}
          canReview={canReview}
        />
      )}
      {selectedIndividualId && <IndividualReviewPanel
        candidate={individualDetail}
        loading={individualLoading}
        resolving={resolvingReviewId === selectedIndividualId}
        readOnly={!canReview}
        onClose={() => setSelectedIndividualId(null)}
        onResolve={resolveIndividual}
      />}
    </div>
  );
}

function ReviewQueues({ queue, loading, resolvingId, readOnly, onResolve, onOpenLead, onInspectIndividual }: {
  queue: ReviewQueuePage | null;
  loading: boolean;
  resolvingId: string | null;
  readOnly: boolean;
  onResolve: (item: ReviewQueueItem, action: string) => void;
  onOpenLead: (item: ReviewQueueItem) => void;
  onInspectIndividual: (item: ReviewQueueItem) => void;
}) {
  const items = queue?.items ?? [];
  return <>
    <div className="page-heading">
      <div>
        <p className="eyebrow">Review queues</p>
        <h1>Human decisions, one trail.</h1>
        <p>Resolve identity ambiguity and advisory hypotheses without mixing them with verified evidence.</p>
      </div>
      {readOnly && <span className="badge badge-neutral">Read-only role</span>}
    </div>
    <section className="metric-grid" aria-label="Pending review summary">
      <Metric label="All pending" value={items.length} detail="Across the current workspace" />
      <Metric label="Business leads" value={queue?.counts.business_lead ?? 0} detail="Qualification or identity" tone="amber" />
      <Metric label="Individuals" value={queue?.counts.individual_candidate ?? 0} detail="Fictional candidates only" tone="mint" />
      <Metric label="Duplicates & AI" value={(queue?.counts.entity_match ?? 0) + (queue?.counts.opportunity_hypothesis ?? 0)} detail="Explicit approval required" />
    </section>
    <section className="workspace-card" aria-labelledby="review-list-title">
      <div className="card-header">
        <div><h2 id="review-list-title">Pending decisions</h2><p>Newest first · workspace scoped · decisions are recorded</p></div>
      </div>
      <div className="review-list" aria-live="polite">
        {loading ? <p className="empty-note">Loading review work…</p> : items.length === 0 ? <p className="empty-note">No pending review work. The queue is clear.</p> : items.map((item) => (
          <article className="review-card" key={`${item.kind}-${item.id}`}>
            <div className="review-card-copy">
              <div className="hypothesis-meta"><span className="badge badge-neutral">{humanize(item.kind)}</span><StatusBadge value={item.status} /></div>
              <h3>{item.title}</h3>
              <p>{item.summary}</p>
              <footer>
                <time dateTime={item.created_at}>{new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(new Date(item.created_at))}</time>
                {item.source_url && <a href={item.source_url} target="_blank" rel="noreferrer">View source</a>}
                {item.score !== null && <span>{item.kind === "individual_candidate" ? `${Math.round(item.score)} qualification points` : `${Math.round(item.score * 100)}% confidence`}</span>}
              </footer>
            </div>
            <div className="review-actions" aria-label={`Actions for ${item.title}`}>
              {item.kind === "business_lead" && <button className="button button-primary" type="button" onClick={() => onOpenLead(item)}>Open evidence</button>}
              {item.kind === "individual_candidate" && <>
                <button className="button button-primary" type="button" onClick={() => onInspectIndividual(item)}>Inspect &amp; decide</button>
              </>}
              {item.kind === "entity_match" && <>
                <button className="button button-secondary" type="button" disabled={readOnly || resolvingId === item.id} onClick={() => onResolve(item, "reject")}>Keep separate</button>
                <button className="button button-secondary" type="button" disabled={readOnly || resolvingId === item.id} onClick={() => onResolve(item, "merge_right")}>Merge into right</button>
                <button className="button button-primary" type="button" disabled={readOnly || resolvingId === item.id} onClick={() => onResolve(item, "merge_left")}>Merge into left</button>
              </>}
              {item.kind === "opportunity_hypothesis" && <>
                <button className="button button-secondary" type="button" disabled={readOnly || resolvingId === item.id} onClick={() => onResolve(item, "reject")}>Reject</button>
                <button className="button button-primary" type="button" disabled={readOnly || resolvingId === item.id} onClick={() => onResolve(item, "accept")}>Accept for planning</button>
              </>}
            </div>
          </article>
        ))}
      </div>
    </section>
  </>;
}

function IndividualReviewPanel({ candidate, loading, resolving, readOnly, onClose, onResolve }: {
  candidate: IndividualCandidate | null;
  loading: boolean;
  resolving: boolean;
  readOnly: boolean;
  onClose: () => void;
  onResolve: (
    candidate: IndividualCandidate,
    action: "promote_new" | "link_existing" | "reject",
    reason: string,
  ) => void;
}) {
  const [reason, setReason] = useState("");
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    closeButtonRef.current?.focus();
    return () => previousFocus?.focus();
  }, []);
  const decisionDisabled = readOnly || resolving || reason.trim().length < 3;
  return <div className="panel-layer">
    <div className="panel-backdrop" onClick={onClose} aria-hidden="true" />
    <div ref={panelRef} className="detail-panel" role="dialog" aria-modal="true" aria-label="Individual candidate review" onKeyDown={(event) => handleDialogKeyDown(event, panelRef.current, onClose)}>
      <div className="panel-topline"><span>Individual review</span><button ref={closeButtonRef} className="icon-button" type="button" onClick={onClose} aria-label="Close individual review">×</button></div>
      {loading || !candidate ? <div className="panel-loading" role="status">Loading individual evidence…</div> : <>
        <div className="lead-identity">
          <span className="company-monogram company-monogram-large" aria-hidden="true">{initials(candidate.display_name)}</span>
          <div><h2>{candidate.display_name}</h2><span className="missing-domain">{candidate.persona ? humanize(candidate.persona) : "Persona not classified"}</span></div>
          <StatusBadge value={candidate.status} />
        </div>
        <section className="detail-section" aria-labelledby="individual-evidence-heading">
          <div className="section-title"><div><p className="eyebrow">Provider assertion</p><h3 id="individual-evidence-heading">Candidate evidence</h3></div><Score value={Math.round((candidate.score / candidate.maximum_score) * 100)} /></div>
          <dl className="individual-facts">
            <div><dt>Location</dt><dd>{[candidate.region, candidate.country_code].filter(Boolean).join(", ") || "Not provided"}</dd></div>
            <div><dt>Professional presence</dt><dd>{candidate.has_professional_presence ? "Present" : "Missing"}</dd></div>
            <div><dt>Business relevance</dt><dd>{candidate.has_business_relevance ? "Supported" : "Not supported"}</dd></div>
            <div><dt>Data boundary</dt><dd>{candidate.is_fictional ? "Fictional fixture" : "Retention-controlled record"}</dd></div>
          </dl>
          <p className="individual-summary">{candidate.service_summary ?? "No service summary was supplied."}</p>
          <div className="source-row"><span className={`badge badge-${candidate.evidence_classification}`}>{classificationLabel(candidate.evidence_classification)}</span><a href={candidate.professional_profile_url} target="_blank" rel="noreferrer">View professional profile</a><a href={candidate.source_url} target="_blank" rel="noreferrer">View source</a></div>
        </section>
        {candidate.possible_match_person_id && <section className="detail-section" aria-labelledby="possible-match-heading"><p className="eyebrow">Identity ambiguity</p><h3 id="possible-match-heading">Possible existing person</h3><p className="match-reference">{candidate.possible_match_person_id}</p><p className="provenance-note"><LockIcon /> Linking requires an explicit human decision and preserves the source profile.</p></section>}
        <section className="detail-section" aria-labelledby="decision-heading">
          <div className="section-title"><div><p className="eyebrow">Recorded human decision</p><h3 id="decision-heading">Resolve candidate</h3></div></div>
          <label className="reason-field"><span>Decision reason</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} maxLength={500} placeholder="Record the evidence and rationale for this decision." disabled={readOnly} /></label>
          {readOnly && <p className="provenance-note"><LockIcon /> Your role can inspect this record but cannot resolve it.</p>}
          <div className="review-actions">
            <button className="button button-secondary" type="button" disabled={decisionDisabled} onClick={() => onResolve(candidate, "reject", reason.trim())}>Reject</button>
            {candidate.possible_match_person_id && <button className="button button-secondary" type="button" disabled={decisionDisabled} onClick={() => onResolve(candidate, "link_existing", reason.trim())}>Link possible match</button>}
            <button className="button button-primary" type="button" disabled={decisionDisabled} onClick={() => onResolve(candidate, "promote_new", reason.trim())}>Promote as new</button>
          </div>
        </section>
      </>}
    </div>
  </div>;
}

function LeadPanel({ detail, analysis, loading, analysisLoading, onClose, onAnalyze, onDecision, onReopen, canAnalyze, canReview }: {
  detail: LeadDetail | null;
  analysis: OpportunityAnalysisRun | null;
  loading: boolean;
  analysisLoading: boolean;
  onClose: () => void;
  onAnalyze: () => void;
  onDecision: (hypothesis: OpportunityHypothesis, decision: "accept" | "reject") => void;
  onReopen: (hypothesis: OpportunityHypothesis) => void;
  canAnalyze: boolean;
  canReview: boolean;
}) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    closeButtonRef.current?.focus();
    return () => previousFocus?.focus();
  }, []);
  return (
    <div className="panel-layer">
      <div className="panel-backdrop" onClick={onClose} aria-hidden="true" />
      <div ref={panelRef} className="detail-panel" role="dialog" aria-modal="true" aria-label="Lead detail" onKeyDown={(event) => handleDialogKeyDown(event, panelRef.current, onClose)}>
        <div className="panel-topline">
          <span>Lead record</span>
          <button ref={closeButtonRef} className="icon-button" type="button" onClick={onClose} aria-label="Close lead detail">×</button>
        </div>
        {loading || !detail ? <div className="panel-loading" role="status">Loading lead evidence…</div> : (
          <>
            <div className="lead-identity">
              <span className="company-monogram company-monogram-large" aria-hidden="true">{initials(detail.company_name)}</span>
              <div><h2>{detail.company_name}</h2>{detail.normalized_domain ? <a href={`https://${detail.normalized_domain}`} target="_blank" rel="noreferrer">{detail.normalized_domain}</a> : <span className="missing-domain">No verified domain</span>}</div>
              <StatusBadge value={detail.disposition} />
            </div>
            <div className="detail-tabs" role="tablist" aria-label="Lead record sections">
              <button role="tab" aria-selected="true">Intelligence</button>
              <button role="tab" aria-selected="false" disabled>Activity</button>
            </div>
            <section className="detail-section" aria-labelledby="score-heading">
              <div className="section-title"><div><p className="eyebrow">Deterministic qualification</p><h3 id="score-heading">ICP score explanation</h3></div><Score value={detail.score_detail.total_score} large /></div>
              <div className="score-components">
                {detail.score_detail.components.map((component) => (
                  <div className="score-component" key={component.rule_key}>
                    <span><strong>{humanize(component.rule_key)}</strong><small>{component.explanation}</small></span>
                    <b>{component.points}/{component.maximum_points}</b>
                  </div>
                ))}
              </div>
              <p className="provenance-note"><LockIcon /> Reproducible with {detail.score_detail.algorithm_version}; AI output never changes this score.</p>
            </section>
            <section className="detail-section" aria-labelledby="evidence-heading">
              <div className="section-title"><div><p className="eyebrow">Source trail</p><h3 id="evidence-heading">Evidence claims</h3></div><span className="count-badge">{detail.evidence.length}</span></div>
              <div className="evidence-list">
                {detail.evidence.map((claim) => <EvidenceCard key={claim.id} claim={claim} />)}
              </div>
            </section>
            <section className="detail-section hypothesis-section" aria-labelledby="hypothesis-heading">
              <div className="section-title">
                <div><p className="eyebrow eyebrow-ai">AI advisory layer</p><h3 id="hypothesis-heading">Opportunity hypotheses</h3></div>
                <button className="button button-primary" type="button" onClick={onAnalyze} disabled={analysisLoading || !canAnalyze}>{analysisLoading ? "Analyzing…" : analysis ? "Refresh analysis" : "Run fictional analysis"}</button>
              </div>
              <div className="ai-boundary"><SparkIcon /><p><strong>Hypotheses are not facts.</strong> Every statement below must cite evidence and requires operator review.</p></div>
              {!analysis ? <p className="empty-note">No opportunity analysis has been recorded for this lead.</p> : analysis.hypotheses.length === 0 ? <p className="empty-note">The analysis found insufficient evidence for a grounded hypothesis.</p> : analysis.hypotheses.map((hypothesis) => (
                <article className="hypothesis-card" key={hypothesis.id}>
                  <div className="hypothesis-meta"><span className="badge badge-ai">AI hypothesis</span><span>{Math.round(hypothesis.confidence * 100)}% model confidence</span></div>
                  <h4>{hypothesis.title}</h4>
                  <p>{hypothesis.summary}</p>
                  <div className="citation-row"><LinkIcon /> {hypothesis.citation_claim_ids.length} cited claim{hypothesis.citation_claim_ids.length === 1 ? "" : "s"}</div>
                  {hypothesis.review_status === "unreviewed" ? <div className="review-actions"><button className="button button-secondary" type="button" disabled={!canReview} onClick={() => onDecision(hypothesis, "reject")}>Reject</button><button className="button button-primary" type="button" disabled={!canReview} onClick={() => onDecision(hypothesis, "accept")}>Accept for planning</button></div> : <div className="review-actions"><StatusBadge value={hypothesis.review_status} /><button className="button button-secondary" type="button" disabled={!canReview} onClick={() => onReopen(hypothesis)}>Reopen review</button></div>}
                </article>
              ))}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function EvidenceCard({ claim }: { claim: LeadDetail["evidence"][number] }) {
  const label = classificationLabel(claim.classification);
  return <article className="evidence-card"><div><span className={`badge badge-${claim.classification}`}>{label}</span><span className="confidence">{Math.round(claim.confidence * 100)}% confidence</span></div><h4>{humanize(claim.claim_type)}</h4><p>{displayValue(claim.value)}</p><footer><a href={claim.source_url} target="_blank" rel="noreferrer">View source</a><time dateTime={claim.observed_at}>{new Intl.DateTimeFormat("en-GB", { dateStyle: "medium" }).format(new Date(claim.observed_at))}</time></footer></article>;
}

function SignInScreen() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (reason) {
      setError(messageFor(reason));
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="sign-in-title">
        <div className="brand-mark" aria-hidden="true">R</div>
        <p className="eyebrow">Revvix Scout</p>
        <h1 id="sign-in-title">Operator sign in</h1>
        <p>Use an invited internal account. Public signups are disabled.</p>
        {error && <div className="alert" role="alert">{error}</div>}
        <form onSubmit={submit}>
          <label>
            <span>Email</span>
            <input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>
            <span>Password</span>
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          <button className="button button-primary" type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}

function FullPageStatus({ message, error = false }: { message: string; error?: boolean }) {
  return <main className="auth-shell"><p className={error ? "auth-status auth-status-error" : "auth-status"} role={error ? "alert" : "status"}>{message}</p></main>;
}

function Metric({ label, value, detail, tone = "navy", suffix = "" }: { label: string; value: number; detail: string; tone?: "navy" | "mint" | "amber"; suffix?: string }) {
  return <article className={`metric-card metric-${tone}`}><span>{label}</span><strong>{value}<small>{suffix}</small></strong><p>{detail}</p></article>;
}

function StatusBadge({ value }: { value: string }) {
  const tone = value.includes("qualified") || value === "resolved" || value === "accepted" ? "success" : value.includes("review") || value === "unreviewed" ? "warning" : "neutral";
  return <span className={`badge badge-${tone}`}><span aria-hidden="true" />{humanize(value)}</span>;
}

function Score({ value, large = false }: { value: number; large?: boolean }) {
  return <span className={`score ${large ? "score-large" : ""}`}><span className="score-ring" style={{ "--score": `${value * 3.6}deg` } as React.CSSProperties}>{value}</span><small>/100</small></span>;
}

function TableMessage({ message }: { message: string }) {
  return <tr><td className="table-message" colSpan={5}>{message}</td></tr>;
}

function classificationLabel(value: EvidenceClassification) {
  return { observed: "Observed fact", provider_asserted: "Provider assertion", inferred: "Inference", human_verified: "Human verified" }[value];
}

function displayValue(value: unknown) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function initials(value: string) {
  return value.split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
}

function messageFor(reason: unknown) {
  return reason instanceof Error ? reason.message : "Unexpected dashboard error";
}

function handleDialogKeyDown(
  event: React.KeyboardEvent<HTMLDivElement>,
  panel: HTMLDivElement | null,
  onClose: () => void,
) {
  if (event.key === "Escape") {
    event.preventDefault();
    onClose();
    return;
  }
  if (event.key !== "Tab" || !panel) return;
  const focusable = Array.from(
    panel.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
  if (focusable.length === 0) return;
  const first = focusable[0]!;
  const last = focusable.at(-1)!;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function GridIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></svg>; }
function QueueIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/></svg>; }
function PulseIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l2-6 4 12 2-6h6"/></svg>; }
function DownloadIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M5 21h14"/></svg>; }
function ChevronIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7"/></svg>; }
function LockIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>; }
function SparkIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 2 1.5 6.5L20 10l-6.5 1.5L12 18l-1.5-6.5L4 10l6.5-1.5L12 2Z"/><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></svg>; }
function LinkIcon() { return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.2 1.2M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.2-1.2"/></svg>; }
