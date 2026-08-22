"""The deterministic triage service: severity bands, soft escalation, redact-before-audit."""

from __future__ import annotations

import json

from hex_service_kit.serialization import to_jsonable

from hr_policy_answers.adapters._review_payload import (
    result_to_review,
)
from hr_policy_answers.adapters.local.audit import (
    LocalAuditAdapter,
)
from hr_policy_answers.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from hr_policy_answers.config import (
    Settings,
)
from hr_policy_answers.domain.kernel import (
    Decision,
    Severity,
)
from hr_policy_answers.domain.models import (
    TriageInput,
)
from hr_policy_answers.domain.triage_service import (
    TriageService,
)

from tests.fixtures import sample_cases


def _service() -> tuple[TriageService, LocalAuditAdapter]:
    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    return TriageService(audit, tracer=LocalNoopTracerAdapter(settings)), audit


def _severity(text: str) -> Severity:
    service, _ = _service()
    return service.triage(TriageInput("X", text), actor="a").severity


def test_severity_bands_are_deterministic() -> None:
    assert _severity("possible fraud") is Severity.CRITICAL
    assert _severity("data breach") is Severity.HIGH
    assert _severity("billing dispute") is Severity.MEDIUM
    assert _severity("all fine") is Severity.LOW


def test_high_and_critical_escalate_softly() -> None:
    service, _ = _service()
    high = service.triage(TriageInput("X", "urgent leak"), actor="a")
    assert high.decision is Decision.ESCALATED
    assert high.requires_human_review is True

    low = service.triage(TriageInput("X", "routine note"), actor="a")
    assert low.decision is Decision.ALLOWED
    assert low.requires_human_review is False


def test_no_planted_identifier_reaches_any_sink_the_raw_case_text_feeds() -> None:
    """One test for every sink the caller's raw text reaches, because the fix is ONE boundary.

    The service redacted at the sinks it remembered and passed the citation through untouched:
    ``redacted_summary`` was masked and the citation stored beside it in the SAME WORM record
    kept the identifier verbatim, in the ``snippet`` cut from the case text and in the
    ``source_id`` composed as ``case:<subject>``. The record a regulator reads back therefore
    held exactly what the redaction was there to remove, and the Hrz7 payload the router derives
    from the same citation carried it to a shared console.

    Asserting per sink is how the next sink gets forgotten, so this walks all of them: the WORM
    record's content fields, the returned result, and the outbound review. There is no model
    sink on this path (this repo binds no narration or generation port; the severity band is
    pure stdlib), so there is nothing to tap there, and adding one must not be the moment
    somebody rediscovers this.
    """
    service, audit = _service()
    result = service.triage(sample_cases.PII_CASE, actor=sample_cases.ACTOR)

    planted = (sample_cases.PLANTED_NRIC, sample_cases.PLANTED_EMAIL)
    rows = audit.log.read_all()
    assert rows, "an audit event should have been recorded"

    # The WORM record, CONTENT fields only: `actor` is the verified principal and an address by
    # design, so scanning the whole row could never be green and would just get switched off.
    content = json.dumps(
        [{"redacted_summary": r["redacted_summary"], "citations": r["citations"]} for r in rows],
        default=str,
    )
    for token in planted:
        assert token not in content, f"{token} survived into the WORM record: {content}"
    assert "REDACTED" in content

    # The returned result, which is also what the router converts into the outbound review.
    returned = json.dumps(to_jsonable(result.citations), default=str)
    for token in planted:
        assert token not in returned, f"{token} survived into the returned citations: {returned}"

    # The outbound Hrz7 payload: a SHARED console, so the locator fields count as content too.
    wire = json.dumps(
        result_to_review(result, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT).to_payload(),
        default=str,
    )
    for token in planted:
        assert token not in wire, f"{token} survived onto the wire to Hrz7: {wire}"

    assert audit.log.verify_chain().ok


def test_pii_is_redacted_before_the_audit_write() -> None:
    service, audit = _service()
    service.triage(
        TriageInput("Gamma LLP", "urgent breach, NRIC S1234567D on file"),
        actor="analyst@bank.example",
    )
    records = audit.log.read_all()
    assert records, "an audit event should have been recorded"
    summary = records[-1]["redacted_summary"]
    # The raw identifier never reaches the WORM record; the actor is the verified principal.
    assert "S1234567D" not in summary
    assert "REDACTED" in summary
    assert records[-1]["actor"] == "analyst@bank.example"
    assert audit.log.verify_chain().ok
