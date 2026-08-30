"""The deterministic entitlement engine: pure, replayable, fail-closed, model-free.

The engine owns every number and every verdict. These tests pin the accrual arithmetic against a
hand-computed oracle, prove the escalation is a property of the request (not the arithmetic), and
prove the fail-closed path: an unknown key produces NO number and routes to a human.
"""

from __future__ import annotations

from datetime import date

import pytest

from hr_policy_answers.domain.entitlement_engine import EntitlementEngine
from hr_policy_answers.domain.kernel import Decision, Severity, VerdictStatus
from hr_policy_answers.domain.models import EmployeeFacts, EntitlementRequest
from hr_policy_answers.packs import load_pack_set

from tests import REPO_ROOT

_PACKS = REPO_ROOT / "config" / "packs"
_AS_OF = date(2024, 1, 1)


def _engine() -> EntitlementEngine:
    return EntitlementEngine(load_pack_set(_PACKS))


def _compute(
    *,
    jurisdiction: str,
    employment_type: str,
    months: int,
    taken: float = 0.0,
    termination: bool = False,
):
    request = EntitlementRequest(
        facts=EmployeeFacts(
            employee_ref="EMP-TEST (FICTIONAL)",
            jurisdiction=jurisdiction,
            employment_type=employment_type,
            months_of_service=months,
            leave_taken_days=taken,
            termination_linked=termination,
        ),
        as_of=_AS_OF,
    )
    return _engine().compute(request)


@pytest.mark.parametrize(
    ("jurisdiction", "employment_type", "months", "taken", "entitled", "balance"),
    [
        ("SG", "full_time", 40, 3.0, 9.0, 6.0),  # base 7 + 2 completed extra years, cap 14
        ("SG", "full_time", 2, 0.0, 0.0, 0.0),  # below min service: not vested
        ("SG", "part_time", 40, 1.0, 6.0, 5.0),  # base 4 + 2 completed extra years, cap 8
        ("AU", "full_time", 24, 5.0, 20.0, 15.0),  # flat 20, no increment
        ("JP", "full_time", 30, 4.0, 11.0, 7.0),  # base 10 + 1 extra year
        ("JP", "full_time", 8, 0.0, 10.0, 10.0),  # just past the 6-month minimum
    ],
)
def test_accrual_matches_the_hand_computed_oracle(
    jurisdiction: str,
    employment_type: str,
    months: int,
    taken: float,
    entitled: float,
    balance: float,
) -> None:
    result = _compute(
        jurisdiction=jurisdiction, employment_type=employment_type, months=months, taken=taken
    )
    assert result.status is VerdictStatus.COMPUTED
    assert result.entitled_days == entitled
    assert result.balance_days == balance


def test_a_within_entitlement_balance_is_auto_approved() -> None:
    result = _compute(jurisdiction="SG", employment_type="full_time", months=40, taken=3.0)
    assert result.decision is Decision.ALLOWED
    assert result.requires_human_review is False
    assert result.severity is Severity.LOW
    assert result.approval_path == ("auto_approved",)


def test_a_termination_linked_question_is_always_consequential() -> None:
    """Even a healthy balance escalates when it is termination-linked: final-pay review."""
    result = _compute(
        jurisdiction="AU", employment_type="full_time", months=24, taken=5.0, termination=True
    )
    assert result.requires_human_review is True
    assert result.severity is Severity.CRITICAL
    assert result.decision is Decision.ESCALATED
    assert "legal" in result.approval_path


def test_an_overdrawn_balance_is_contested_and_escalates() -> None:
    result = _compute(jurisdiction="SG", employment_type="full_time", months=40, taken=20.0)
    assert result.balance_days == -11.0
    assert result.requires_human_review is True
    assert result.severity is Severity.HIGH


def test_an_unpacked_employment_type_fails_closed_with_no_number() -> None:
    result = _compute(jurisdiction="JP", employment_type="part_time", months=30)
    assert result.status is VerdictStatus.NEEDS_INFO
    assert result.entitled_days is None
    assert result.balance_days is None
    assert result.requires_human_review is True


def test_an_unknown_jurisdiction_fails_closed() -> None:
    result = _compute(jurisdiction="HK", employment_type="full_time", months=40)
    assert result.status is VerdictStatus.NEEDS_INFO
    assert result.requires_human_review is True
    assert result.citations, "even a refusal carries a citation of why it refused"


def test_the_engine_is_replayable() -> None:
    """Same inputs, same output, byte for byte: the point of a deterministic engine."""
    first = _compute(jurisdiction="JP", employment_type="full_time", months=30, taken=4.0)
    second = _compute(jurisdiction="JP", employment_type="full_time", months=30, taken=4.0)
    assert first == second


def test_every_computed_result_carries_its_rule_citation() -> None:
    result = _compute(jurisdiction="SG", employment_type="full_time", months=40)
    assert result.rule_hits, "a computed number must name the rule it came from"
    assert result.citations[0].source_id == "sg-ea-1968-part-iv"
