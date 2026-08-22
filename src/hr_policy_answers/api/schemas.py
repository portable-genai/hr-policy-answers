"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from ..domain.models import EntitlementResult, TriageResult


class TriageRequest(BaseModel):
    subject: str
    text: str


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class TriageResponse(BaseModel):
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    #: Where the escalation WENT (rule R8): the Hrz7 review id, or the local queue reference.
    #: Empty only when the result did not escalate. A caller can tell a routed escalation from
    #: a flag that stopped here, which is the whole point of the rule.
    review_ref: str = ""
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, result: TriageResult, *, review_ref: str = "") -> TriageResponse:
        return cls(
            subject=result.subject,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            review_ref=review_ref,
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class EntitlementRequestModel(BaseModel):
    """One entitlement question: structured employee facts, never free text.

    ``employee_ref`` is an opaque, fictional reference; the server never trusts a client-asserted
    identity for the audit actor (that is the verified principal).
    """

    employee_ref: str
    jurisdiction: str
    employment_type: str
    months_of_service: int
    leave_taken_days: float = 0.0
    termination_linked: bool = False
    entitlement: str = "annual_leave"
    as_of: date | None = None


class RuleHitModel(BaseModel):
    rule_id: str
    entitlement: str
    detail: str
    citation: CitationModel


class EntitlementResponse(BaseModel):
    """The deterministic worksheet plus the R8 routing outcome.

    ``entitled_days`` / ``balance_days`` are ``null`` exactly when ``status`` is ``needs_info``: a
    fail-closed verdict carries no number, so a caller can never read a refusal as a computed zero.
    """

    subject: str
    status: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    jurisdiction: str
    employment_type: str
    entitled_days: float | None = None
    taken_days: float | None = None
    balance_days: float | None = None
    approval_path: list[str] = []
    rule_hits: list[RuleHitModel] = []
    review_ref: str = ""
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(cls, result: EntitlementResult, *, review_ref: str = "") -> EntitlementResponse:
        return cls(
            subject=result.subject,
            status=result.status.value,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            jurisdiction=result.jurisdiction,
            employment_type=result.employment_type,
            entitled_days=result.entitled_days,
            taken_days=result.taken_days,
            balance_days=result.balance_days,
            approval_path=list(result.approval_path),
            rule_hits=[
                RuleHitModel(
                    rule_id=hit.rule_id,
                    entitlement=hit.entitlement,
                    detail=hit.detail,
                    citation=CitationModel(
                        source_id=hit.citation.source_id,
                        title=hit.citation.title,
                        snippet=hit.citation.snippet,
                    ),
                )
                for hit in result.rule_hits
            ],
            review_ref=review_ref,
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
