"""Deterministic, provider-free M7 opportunity-analysis fixture."""

from uuid import UUID

from revvix_scout.domain.opportunities import (
    AnalysisEvidence,
    OpportunityAnalysisDraft,
    OpportunityHypothesisDraft,
)
from revvix_scout.providers.opportunity_contracts import (
    OpportunityAnalysisQuery,
    OpportunityAnalysisResult,
)


class FictionalOpportunityAnalysisProvider:
    key = "fictional_opportunity_analyzer"
    is_live = False
    supports_tools = False

    def estimate_units(self, query: OpportunityAnalysisQuery) -> int:
        return 1

    def analyze(self, query: OpportunityAnalysisQuery) -> OpportunityAnalysisResult:
        technology_need = _first_claim(query, "technology_need")
        category = (
            technology_need.normalized_value
            if technology_need is not None
            and technology_need.normalized_value in query.allowed_categories
            else None
        )
        if technology_need is None or category is None:
            analysis = OpportunityAnalysisDraft(
                hypotheses=(),
                missing_fields=("technology_need",),
            )
        else:
            industry = _first_claim(query, "industry")
            citations: tuple[UUID, ...] = (technology_need.claim_id,)
            if industry is not None:
                citations += (industry.claim_id,)
            analysis = OpportunityAnalysisDraft(
                hypotheses=(
                    OpportunityHypothesisDraft(
                        category=category,
                        title="Review a potential workflow automation opportunity",
                        summary=(
                            "The fictional evidence suggests a workflow issue worth "
                            "operator review; the hypothesis is not a verified buying signal."
                        ),
                        confidence=0.72,
                        citation_claim_ids=citations,
                        missing_fields=("process_owner", "current_system"),
                    ),
                )
            )
        return OpportunityAnalysisResult(
            analysis=analysis,
            model_name="deterministic-fixture",
            model_version="m7-fixture-1",
            prompt_tokens=0,
            completion_tokens=0,
            actual_units=1,
        )


def _first_claim(query: OpportunityAnalysisQuery, claim_type: str) -> AnalysisEvidence | None:
    candidates = tuple(item for item in query.evidence if item.claim_type == claim_type)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.normalized_value, str(item.claim_id)))
