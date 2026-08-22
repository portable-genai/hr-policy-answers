"""Each copilot path opens ONE span, and no span carries content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit
store. So the value of tracing these paths depends entirely on the spans carrying
structural attributes only: which action, whose, which jurisdiction. A case's free text, an
employee reference, a fact figure or a planted identifier reaching a span has left the
boundary the services' ``redact`` calls exist to hold, and it has left it silently.

Two orchestrators are pinned because both sit on real request paths: the entitlement
computation (API, CLI, agent tool, demo, eval) and the manual triage scaffold (API, CLI,
agent tool). They do not nest: neither drives the other. The content cases drive the case
whose text carries a planted NRIC and the entitlement request whose employee reference
carries the same, so the checks run against input that would actually leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from hr_policy_answers.config import Settings, build_container
from hr_policy_answers.domain.entitlement_service import EntitlementService
from hr_policy_answers.domain.models import EntitlementRequest, TriageInput
from hr_policy_answers.domain.triage_service import TriageService

from tests.fixtures import sample_cases

#: Every attribute key each span is allowed to carry. A verdict that started explaining
#: itself on the span (a balance, an employee, a rule) would widen these sets, which is the
#: point of asserting on the set rather than on the individual keys.
_TRIAGE_KEYS = {"action", "actor"}
_ENTITLEMENT_KEYS = {"action", "actor", "jurisdiction"}


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _triage(case: TriageInput) -> _RecordingTracer:
    tracer = _RecordingTracer()
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = TriageService(container.audit, tracer=tracer)  # type: ignore[arg-type]
    service.triage(case, actor=sample_cases.ACTOR)
    return tracer


def _assess(request: EntitlementRequest) -> _RecordingTracer:
    tracer = _RecordingTracer()
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    service = EntitlementService(container.audit, tracer=tracer)  # type: ignore[arg-type]
    service.assess(request, actor=sample_cases.ACTOR)
    return tracer


def _emitted(tracer: _RecordingTracer) -> str:
    """Every attribute KEY and VALUE that was emitted, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


def test_triaging_a_case_opens_exactly_one_named_span() -> None:
    tracer = _triage(sample_cases.ROUTINE_CASE)
    assert [name for name, _ in tracer.spans] == ["policy_hr.triage"]


def test_assessing_an_entitlement_opens_exactly_one_named_span() -> None:
    tracer = _assess(sample_cases.PII_ENTITLEMENT)
    assert [name for name, _ in tracer.spans] == ["policy_hr.entitlement"]


def test_the_triage_span_carries_the_structural_attributes_an_operator_needs() -> None:
    _, attributes = _triage(sample_cases.ROUTINE_CASE).spans[0]
    assert attributes["action"] == "triage"
    assert attributes["actor"] == sample_cases.ACTOR


def test_the_entitlement_span_carries_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose computation is slow, under which rules", and nothing more."""
    _, attributes = _assess(sample_cases.PII_ENTITLEMENT).spans[0]
    assert attributes["action"] == "entitlement"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["jurisdiction"] == sample_cases.PII_ENTITLEMENT.facts.jurisdiction


@pytest.mark.parametrize(
    "case",
    [sample_cases.ROUTINE_CASE, sample_cases.ESCALATING_CASE, sample_cases.PII_CASE],
    ids=["routine", "escalating", "pii"],
)
def test_the_triage_attribute_set_is_a_fixed_allowlist_whatever_the_verdict(
    case: TriageInput,
) -> None:
    for _, attributes in _triage(case).spans:
        assert set(attributes) == _TRIAGE_KEYS, (
            "a new span attribute appeared; confirm it is structural, then widen "
            "_TRIAGE_KEYS here deliberately"
        )


@pytest.mark.parametrize(
    "request_",
    [
        sample_cases.CONSEQUENTIAL_ENTITLEMENT,
        sample_cases.FAILCLOSED_ENTITLEMENT,
        sample_cases.PII_ENTITLEMENT,
    ],
    ids=["consequential", "failclosed", "pii"],
)
def test_the_entitlement_attribute_set_is_a_fixed_allowlist_whatever_the_verdict(
    request_: EntitlementRequest,
) -> None:
    """A fail-closed refusal must not start attaching its reason, or the facts, to the span."""
    for _, attributes in _assess(request_).spans:
        assert set(attributes) == _ENTITLEMENT_KEYS, (
            "a new span attribute appeared; confirm it is structural, then widen "
            "_ENTITLEMENT_KEYS here deliberately"
        )


def test_no_triage_span_attribute_carries_case_content_or_the_planted_identifier() -> None:
    emitted = _emitted(_triage(sample_cases.PII_CASE)).lower()
    forbidden = (
        sample_cases.PLANTED_NRIC,
        sample_cases.PII_CASE.text,
        sample_cases.PII_CASE.subject,
        "ops@gamma.example",
    )
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal.lower() not in emitted, f"a span attribute carried {literal!r}"


def test_no_entitlement_span_attribute_carries_the_employee_or_a_fact_figure() -> None:
    """The request used here has an NRIC planted in its employee reference."""
    facts = sample_cases.PII_ENTITLEMENT.facts
    emitted = _emitted(_assess(sample_cases.PII_ENTITLEMENT)).lower()
    forbidden = (
        sample_cases.PLANTED_NRIC,
        facts.employee_ref,
        str(facts.months_of_service),
        str(facts.leave_taken_days),
    )
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal.lower() not in emitted, f"a span attribute carried {literal!r}"


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    values = [
        value
        for tracer in (
            _triage(sample_cases.ESCALATING_CASE),
            _assess(sample_cases.CONSEQUENTIAL_ENTITLEMENT),
        )
        for _, attributes in tracer.spans
        for value in attributes.values()
    ]
    assert values
    assert all(isinstance(value, str) for value in values)
