"""The deterministic entitlement engine: every number and every verdict, in pure stdlib.

This is the vertical's differentiation. Given the employee facts in a request plus the rule packs,
it computes the leave balance, the eligibility and the approval path with NO model in the loop: an
LLM may later narrate this worksheet, but it can never produce a day count or a verdict. The
computation is a single, replayable calculation from frozen inputs, exactly the extract-then-
compute split ``credit-memo-drafting``'s covenant service uses, where the model extracts
terms and the domain computes status.

Fail closed, always. An unknown jurisdiction, an employment type nobody packed a rule for, a
missing fact or a date outside every effective window yields NO verdict and
``requires_human_review`` set, never a guess. A consequential answer (a termination-linked or
final-pay question, or a contested/overdrawn balance) is routed to a human whatever the arithmetic
says. The engine talks only to models and packs: no ports, no I/O, no audit write (the service
layer owns those), so it is trivially replayable in a test and in the eval oracle.
"""

from __future__ import annotations

from datetime import date

from .kernel import Citation, Decision, Severity, VerdictStatus, utcnow
from .models import EntitlementRequest, EntitlementResult, RuleHit
from .packs import EntitlementRule, PackSet

#: Approval chains, most-authoritative last. Auto-approval is the ONLY path with no human, and it
#: is reachable only for a plainly non-consequential computed answer.
_AUTO_APPROVED: tuple[str, ...] = ("auto_approved",)
_CONTESTED_CHAIN: tuple[str, ...] = ("hr_business_partner", "payroll_control")
_TERMINATION_CHAIN: tuple[str, ...] = ("hr_business_partner", "payroll_control", "legal")
_NEEDS_INFO_CHAIN: tuple[str, ...] = ("hr_business_partner",)


class EntitlementEngine:
    """Compute an entitlement worksheet from packs and employee facts. Pure and replayable."""

    def __init__(self, packs: PackSet) -> None:
        self._packs = packs

    def compute(self, request: EntitlementRequest) -> EntitlementResult:
        """Compute the verdict for one request. Never raises on unknown input; it fails closed."""
        facts = request.facts
        as_of = request.as_of or utcnow().date()
        subject = facts.employee_ref

        rule = self._packs.match(
            jurisdiction=facts.jurisdiction,
            entitlement=request.entitlement,
            employment_type=facts.employment_type,
            as_of=as_of,
        )
        if rule is None:
            return self._needs_info(request, as_of)

        entitled = _entitled_days(rule, facts.months_of_service)
        taken = float(facts.leave_taken_days)
        balance = round(entitled - taken, 4)
        rule_hit = RuleHit(
            rule_id=rule.rule_id,
            entitlement=rule.entitlement,
            detail=(
                f"{rule.employment_type} in {rule.jurisdiction}: "
                f"{entitled:g} day(s) entitled at {facts.months_of_service} month(s) service"
            ),
            citation=rule.citation(),
        )

        overdrawn = balance < 0
        consequential = facts.termination_linked or overdrawn
        return self._computed(
            request=request,
            as_of=as_of,
            entitled=entitled,
            taken=taken,
            balance=balance,
            rule_hit=rule_hit,
            overdrawn=overdrawn,
            consequential=consequential,
            subject=subject,
        )

    def _computed(
        self,
        *,
        request: EntitlementRequest,
        as_of: date,
        entitled: float,
        taken: float,
        balance: float,
        rule_hit: RuleHit,
        overdrawn: bool,
        consequential: bool,
        subject: str,
    ) -> EntitlementResult:
        facts = request.facts
        if facts.termination_linked:
            severity = Severity.CRITICAL
            approval = _TERMINATION_CHAIN
            reason = "termination-linked entitlement: final-pay review required"
        elif overdrawn:
            severity = Severity.HIGH
            approval = _CONTESTED_CHAIN
            reason = "contested balance: recorded leave exceeds the computed entitlement"
        else:
            severity = Severity.LOW
            approval = _AUTO_APPROVED
            reason = "within entitlement"
        decision = Decision.ESCALATED if consequential else Decision.ALLOWED
        summary = (
            f"{subject} ({facts.jurisdiction}/{facts.employment_type}): "
            f"{balance:g} day(s) balance of {entitled:g} entitled, {reason} "
            f"(as of {as_of.isoformat()})"
        )
        return EntitlementResult(
            subject=subject,
            severity=severity,
            decision=decision,
            summary=summary,
            requires_human_review=consequential,
            citations=(rule_hit.citation,),
            status=VerdictStatus.COMPUTED,
            jurisdiction=facts.jurisdiction,
            employment_type=facts.employment_type,
            entitled_days=entitled,
            taken_days=taken,
            balance_days=balance,
            approval_path=approval,
            rule_hits=(rule_hit,),
        )

    def _needs_info(self, request: EntitlementRequest, as_of: date) -> EntitlementResult:
        """No rule matched: refuse to guess, route to a human, carry no number."""
        facts = request.facts
        summary = (
            f"{facts.employee_ref}: no effective {request.entitlement} rule for "
            f"{facts.jurisdiction}/{facts.employment_type} as of {as_of.isoformat()}; "
            "routed for human review rather than guessing"
        )
        citation = Citation(
            source_id="engine:needs_info",
            title="Fail-closed: no matching entitlement rule",
            snippet=f"{facts.jurisdiction}/{request.entitlement}/{facts.employment_type}",
        )
        return EntitlementResult(
            subject=facts.employee_ref,
            severity=Severity.MEDIUM,
            decision=Decision.ESCALATED,
            summary=summary,
            requires_human_review=True,
            citations=(citation,),
            status=VerdictStatus.NEEDS_INFO,
            jurisdiction=facts.jurisdiction,
            employment_type=facts.employment_type,
            entitled_days=None,
            taken_days=float(facts.leave_taken_days),
            balance_days=None,
            approval_path=_NEEDS_INFO_CHAIN,
            rule_hits=(),
        )


def _entitled_days(rule: EntitlementRule, months_of_service: int) -> float:
    """Entitled days for one rule at a given tenure. The engine's one accrual formula.

    Below ``min_months_service`` the entitlement has not vested, so it is zero. Otherwise the base
    accrues, and each COMPLETED year of service beyond the first adds the yearly increment, capped
    at ``max_days``. Deterministic and monotonic in tenure by construction.
    """
    if months_of_service < rule.min_months_service:
        return 0.0
    extra_years = max(0, (months_of_service // 12) - 1)
    accrued = rule.base_days + rule.increment_days_per_year * extra_years
    return float(min(accrued, rule.max_days))
