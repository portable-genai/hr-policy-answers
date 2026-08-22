"""Every entitlement metric is proven able to go RED, per market, or it proves nothing.

The recurring failure ``agent_eval_kit`` exists to catch is a metric that cannot fail: a scorer
that reads the pipeline's own answer, or a golden set that planted no target. Here the oracle is
independent (the dataset's hand-computed ``expected_balance`` / ``expected_status``), and this
suite cashes that: for each jurisdiction, a correct case must PASS and a case whose oracle has been
mutated to a WRONG balance must FAIL. If the mutated oracle still passed, the metric would be
reading the engine rather than scoring it.
"""

from __future__ import annotations

from typing import Any

import pytest
from agent_eval_kit import assert_each_can_go_red
from run_eval import DEFAULT_DATASET, accuracy_of_case, load_cases


def _cases_by_market() -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """One (green, red) pair per market, built from the first COMPUTED case of that market.

    ``green`` is the real case (correct oracle); ``red`` copies it with the expected balance moved,
    so the same engine output no longer matches and the metric must go red.
    """
    pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for case in load_cases(DEFAULT_DATASET):
        market = str(case["market"])
        if case["expected_status"] != "computed" or market in pairs:
            continue
        red = dict(case)
        red["expected_balance"] = float(case["expected_balance"]) + 1.0
        pairs[market] = (case, red)
    return pairs


def test_entitlement_accuracy_can_go_red_per_market() -> None:
    pairs = _cases_by_market()
    assert set(pairs) == {"SG", "AU", "JP"}, "every packed jurisdiction needs a red probe"
    assert_each_can_go_red(
        accuracy_of_case,
        pairs,
        threshold=0.99,
        metric="entitlement_accuracy",
    )


def _review_score(case: dict[str, Any]) -> float:
    """1.0 when a consequential case ends pending review. Reads the ENGINE, scores the ORACLE."""
    from run_eval import _engine, request_from

    result = _engine().compute(request_from(case))
    return 1.0 if result.requires_human_review else 0.0


def test_review_safety_can_go_red() -> None:
    """A consequential golden (green) routes; a non-consequential one (red) does not."""
    from agent_eval_kit import assert_can_go_red

    cases = {c["id"]: c for c in load_cases(DEFAULT_DATASET)}
    consequential = cases["e-sg-2"]  # termination-linked -> must route
    routine = cases["e-au-1"]  # within entitlement -> must NOT route
    assert_can_go_red(
        _review_score,
        green=consequential,
        red=routine,
        threshold=0.99,
        metric="review_safety",
    )


@pytest.mark.parametrize(
    ("case_id", "expected_balance", "expected_status", "expected_review"),
    [
        ("e-sg-1", 6.0, "computed", False),
        ("e-sg-3", -11.0, "computed", True),
        ("e-jp-2", 10.0, "computed", False),
        ("e-jp-failclosed", None, "needs_info", True),
        ("e-unknown-jurisdiction", None, "needs_info", True),
    ],
)
def test_engine_matches_the_independent_oracle(
    case_id: str,
    expected_balance: float | None,
    expected_status: str,
    expected_review: bool,
) -> None:
    """Spot-check the engine against the hand-computed oracle for representative cases."""
    from run_eval import _engine, request_from

    case = {c["id"]: c for c in load_cases(DEFAULT_DATASET)}[case_id]
    result = _engine().compute(request_from(case))
    assert result.status.value == expected_status
    assert result.balance_days == expected_balance
    assert result.requires_human_review is expected_review
