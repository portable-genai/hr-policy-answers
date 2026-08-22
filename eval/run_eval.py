#!/usr/bin/env python3
"""Evaluation gate for Policy and HR Copilot (H2).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change. It drives the REAL
  deterministic ``EntitlementEngine`` and ``EntitlementService`` against a golden set with SDK-free
  local adapters and scores three metrics, each against the dataset's OWN independent oracle:

  * ``entitlement_accuracy`` - the engine's computed balance and verdict status vs the hand-computed
    ``expected_balance`` / ``expected_status`` in the dataset (NOT the engine's own answer);
  * ``review_safety`` - every consequential golden (``expected_review``) ends
    ``requires_human_review``, so no consequential entitlement is auto-answered (rule R8 / P-06);
  * ``pii_safety`` - no raw identifier planted in a case survives into ANY content-bearing field
    of an audit record, the citations included (see :func:`audit_surfaces`).

* **gate** - the promotion verdict from the shared Hrz4 authority (requires the ``gcp`` profile),
  via ``agent_eval_kit.PromotionGateClient``.

Each metric is proven able to go RED, and against the SHIPPED scorer rather than a lookalike
written for the test: ``tests/unit/test_entitlement_eval.py`` drives the first two per market
through ``agent_eval_kit.assert_each_can_go_red``, and ``tests/unit/test_not_falsely_green.py``
imports :func:`audit_surfaces` and :func:`pii_safety` from this module and scores them over rows
the real pipeline persisted. A metric that cannot fail proves nothing, and a falsification proof
aimed at a copy of the metric proves nothing about the metric.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent_eval_kit import EvalMetricResult, EvalReport, PromotionGateClient, eval_main
from pii_kit import pack_leak

from hr_policy_answers.adapters.local.audit import (
    LocalAuditAdapter,
)
from hr_policy_answers.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from hr_policy_answers.config import (
    Settings,
)
from hr_policy_answers.domain.entitlement_engine import (
    EntitlementEngine,
)
from hr_policy_answers.domain.entitlement_service import (
    EntitlementService,
)
from hr_policy_answers.domain.kernel import (
    VerdictStatus,
)
from hr_policy_answers.domain.models import (
    EmployeeFacts,
    EntitlementRequest,
    EntitlementResult,
)
from hr_policy_answers.domain.packs import (
    load_pack_set,
)
from hr_policy_answers.domain.pii import (
    PII_PATTERNS,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_entitlements.jsonl"

THRESHOLDS: dict[str, float] = {
    "entitlement_accuracy": 0.99,
    "review_safety": 0.99,
    "pii_safety": 0.99,
}
#: The registered Hrz4 metric bundle for this vertical (Hrz4 owns the metrics + thresholds).
_BUNDLE = "hr-policy-answers"


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


@lru_cache(maxsize=1)
def _engine() -> EntitlementEngine:
    """The engine bound to the shipped packs, loaded from the repo (explicit path, no CWD guess)."""
    return EntitlementEngine(load_pack_set(_REPO_ROOT / "config" / "packs"))


def request_from(case: dict[str, Any]) -> EntitlementRequest:
    """Build the engine request from one golden case (the inputs only, never the expected_*)."""
    return EntitlementRequest(
        facts=EmployeeFacts(
            employee_ref=str(case["employee_ref"]),
            jurisdiction=str(case["jurisdiction"]),
            employment_type=str(case["employment_type"]),
            months_of_service=int(case["months_of_service"]),
            leave_taken_days=float(case.get("leave_taken_days", 0.0)),
            termination_linked=bool(case.get("termination_linked", False)),
        ),
        entitlement=str(case.get("entitlement", "annual_leave")),
    )


def accuracy_score(case: dict[str, Any], result: EntitlementResult) -> float:
    """Score one engine result against the case's INDEPENDENT oracle. 1.0 on an exact match.

    A ``needs_info`` oracle demands the fail-closed shape (no number). A ``computed`` oracle demands
    the exact ``expected_balance``. The engine's own answer is never consulted as the truth: the
    dataset is.
    """
    expected_status = str(case["expected_status"])
    if expected_status == VerdictStatus.NEEDS_INFO.value:
        ok = result.status is VerdictStatus.NEEDS_INFO and result.balance_days is None
        return 1.0 if ok else 0.0
    if result.status is not VerdictStatus.COMPUTED or result.balance_days is None:
        return 0.0
    expected_balance = float(case["expected_balance"])
    return 1.0 if abs(result.balance_days - expected_balance) < 1e-9 else 0.0


def accuracy_of_case(case: dict[str, Any]) -> float:
    """Run the engine on one case and score it against its oracle (the per-market red probe)."""
    return accuracy_score(case, _engine().compute(request_from(case)))


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def audit_surfaces(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every CONTENT-bearing field of each persisted audit row, citations included.

    ``redacted_summary`` is one field of several the WORM record keeps, and scoring it alone is
    how a metric ends up certifying the leak it exists to catch: the summary is masked, the
    citations stored beside it in the same row are not, and the identifier survives in a record
    the metric has just called clean. A citation's ``source_id`` is content here, not a bare
    locator, because a locator is built out of the identifiers the case supplied.

    ``actor`` is deliberately absent. It is the VERIFIED principal and an address by design, so a
    blanket scan over a whole row could never go green, and a metric that can never go green is a
    metric somebody switches off. Scanning the content fields is what makes this both sound and
    reachable.
    """
    out: list[str] = []
    for row in rows:
        out.append(str(row.get("redacted_summary", "")))
        out.append(json.dumps(row.get("citations", []), sort_keys=True, default=str))
    return out


def pii_safety(surfaces: Sequence[str], planted: Sequence[str]) -> float:
    """1.0 unless a raw identifier survived into an audit record, by pack row OR by literal.

    The pack scan uses the same rows the redactor masks with, so it catches PII the pipeline
    re-introduced after redaction; the planted-literal scan is an independent oracle that still
    fires when a pack row is narrowed or broken (the two-part scorer lesson from the C4 rollout).
    """
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in surfaces)
    literal_leaked = any(token in text for token in planted for text in surfaces)
    return 0.0 if (pack_leaked or literal_leaked) else 1.0


def run_smoke(dataset: Path) -> EvalReport:
    cases = load_cases(dataset)
    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    service = EntitlementService(audit, _engine(), tracer=LocalNoopTracerAdapter(settings))

    accuracy_scores: list[float] = []
    review_scores: list[float] = []
    for case in cases:
        result = service.assess(request_from(case), actor="eval-bot")
        accuracy_scores.append(accuracy_score(case, result))
        # review_safety: recall over the CONSEQUENTIAL goldens. A consequential case the engine
        # failed to route is an auto-answered decision, which is the exact failure R8 forbids.
        if bool(case.get("expected_review")):
            review_scores.append(1.0 if result.requires_human_review else 0.0)

    # pii_safety: no raw identifier may survive into any audit record.
    surfaces = audit_surfaces(audit.log.read_all())
    planted = [str(case["planted"]) for case in cases if case.get("planted")]

    results = (
        EvalMetricResult.scored(
            "entitlement_accuracy",
            _mean(accuracy_scores),
            THRESHOLDS["entitlement_accuracy"],
        ),
        EvalMetricResult.scored("review_safety", _mean(review_scores), THRESHOLDS["review_safety"]),
        EvalMetricResult.scored(
            "pii_safety", pii_safety(surfaces, planted), THRESHOLDS["pii_safety"]
        ),
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(cases))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"POLICYHR_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("POLICYHR_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / Hrz4 evaluation gate for H2.",
        )
    )
