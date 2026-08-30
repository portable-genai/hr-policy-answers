"""The entitlement service: run the engine, redact before the audit write, record, return.

The service adds the side effects the pure engine must not have. These tests prove the audit event
is written already-redacted (a planted national id never reaches the WORM record), that the actor
is the one passed (never a client-asserted employee_ref), and that the returned worksheet is the
engine's unchanged.
"""

from __future__ import annotations

import json

from hr_policy_answers.adapters._review_payload import result_to_review
from hr_policy_answers.adapters.local.audit import LocalAuditAdapter
from hr_policy_answers.adapters.local.tracer import LocalNoopTracerAdapter
from hr_policy_answers.config import Settings
from hr_policy_answers.domain.entitlement_engine import EntitlementEngine
from hr_policy_answers.domain.entitlement_service import EntitlementService
from hr_policy_answers.domain.kernel import Citation, Decision, Severity, VerdictStatus
from hr_policy_answers.domain.models import EntitlementRequest, EntitlementResult
from hr_policy_answers.packs import default_engine

from tests.fixtures import sample_cases


def _service(
    engine: EntitlementEngine | None = None,
) -> tuple[EntitlementService, LocalAuditAdapter]:
    """The engine is required now, so ``None`` here means "the shipped packs", explicitly.

    It used to mean the same thing implicitly, resolved inside the service by reading the pack
    directory off the filesystem. Naming it at the seam is what let that read move out of the
    core entirely: the domain is handed an engine, and never goes looking for one.
    """
    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    resolved = engine if engine is not None else default_engine()
    return EntitlementService(audit, resolved, tracer=LocalNoopTracerAdapter(settings)), audit


class _RefQuotingEngine(EntitlementEngine):
    """An engine whose citation quotes the employee reference it was handed.

    The engine is INJECTED by design, and the shipped packs happen to cite a statute, so today's
    citations carry nothing personal and the service's pass-through looked harmless. Nothing in
    the engine's contract promises that: a pack that cites the case it was applied to is one pack
    away, and the service's redact-before-the-audit-write promise has to hold for whatever engine
    it is handed rather than for the one bound this week. This engine is that next pack.
    """

    def __init__(self) -> None:
        """No packs: :meth:`compute` never consults them, so there is nothing to load."""

    def compute(self, request: EntitlementRequest) -> EntitlementResult:
        ref = request.facts.employee_ref
        return EntitlementResult(
            subject=ref,
            severity=Severity.CRITICAL,
            decision=Decision.ESCALATED,
            summary=f"{ref}: termination-linked, final-pay review required",
            requires_human_review=True,
            citations=(
                Citation(
                    source_id=f"case:{ref}",
                    title=f"Final pay worksheet for {ref}",
                    snippet=f"balance recomputed for {ref}",
                ),
            ),
            status=VerdictStatus.COMPUTED,
            jurisdiction=request.facts.jurisdiction,
            employment_type=request.facts.employment_type,
            entitled_days=8.0,
            taken_days=2.0,
            balance_days=6.0,
            approval_path=("hr_business_partner", "payroll_control", "legal"),
        )


def test_a_computed_result_is_returned_unchanged() -> None:
    service, _ = _service()
    result = service.assess(sample_cases.ROUTINE_ENTITLEMENT, actor="hr@bank.example")
    assert result.status is VerdictStatus.COMPUTED
    assert result.balance_days == 6.0
    assert result.requires_human_review is False


def test_pii_is_redacted_before_the_audit_write() -> None:
    service, audit = _service()
    service.assess(sample_cases.PII_ENTITLEMENT, actor="hr@bank.example")
    records = audit.log.read_all()
    assert records, "an audit event should have been recorded"
    summary = str(records[-1]["redacted_summary"])
    assert sample_cases.PLANTED_NRIC not in summary
    assert "REDACTED" in summary
    assert records[-1]["actor"] == "hr@bank.example"
    assert audit.log.verify_chain().ok


def test_no_planted_identifier_reaches_any_sink_the_engine_citations_feed() -> None:
    """One test for every sink the engine's citations reach, because the fix is ONE boundary.

    The service masked ``redacted_summary`` and then handed ``result.citations`` straight into
    the SAME audit event, so whatever the engine put in a citation was persisted verbatim beside
    a summary that had just been scrubbed. The worksheet itself is returned UNCHANGED on purpose
    (the API, the CLI and the agent must all see the engine's answer), so the two sinks that must
    hold are the WORM record and the outbound Hrz7 payload, and each is closed at its own edge:
    the audit write here, and ``_kit_citations`` where the payload crosses to a shared console.

    There is no model sink on this path: the engine is pure stdlib and this repo binds no
    narration port, so no case text crosses to a model at all.
    """
    service, audit = _service(_RefQuotingEngine())
    result = service.assess(sample_cases.PII_ENTITLEMENT, actor=sample_cases.ACTOR)
    planted = sample_cases.PLANTED_NRIC

    rows = audit.log.read_all()
    assert rows, "an audit event should have been recorded"
    # CONTENT fields only: `actor` is the verified principal and an address by design, so a
    # blanket scan over the whole row could never be green and would just get switched off.
    content = json.dumps(
        [{"redacted_summary": r["redacted_summary"], "citations": r["citations"]} for r in rows],
        default=str,
    )
    assert planted not in content, f"{planted} survived into the WORM record: {content}"
    assert "REDACTED" in content

    wire = json.dumps(
        result_to_review(result, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT).to_payload(),
        default=str,
    )
    assert planted not in wire, f"{planted} survived onto the wire to Hrz7: {wire}"

    assert audit.log.verify_chain().ok


def test_the_actor_is_never_the_client_asserted_employee_ref() -> None:
    service, audit = _service()
    service.assess(sample_cases.ROUTINE_ENTITLEMENT, actor="verified@bank.example")
    record = audit.log.read_all()[-1]
    assert record["actor"] == "verified@bank.example"
    assert "EMP-4021" not in record["actor"]


def test_a_fail_closed_result_still_records_an_audit_event() -> None:
    service, audit = _service()
    result = service.assess(sample_cases.FAILCLOSED_ENTITLEMENT, actor="hr@bank.example")
    assert result.status is VerdictStatus.NEEDS_INFO
    assert result.requires_human_review is True
    assert audit.log.read_all(), "a refusal is still an auditable event"
