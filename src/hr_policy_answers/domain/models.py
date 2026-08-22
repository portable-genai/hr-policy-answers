"""Vertical artifact models: this service's own request and result types.

The artifacts THIS vertical produces, as opposed to the vertical-neutral machinery in
``kernel.py``. The service's own name is deliberately not substituted into this docstring: a
rendered line whose length depends on ``friendly_name`` fails the repo's own format check for
no reason but the length of its name.

A fork building a different vertical rewrites this module and keeps ``kernel.py`` untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .kernel import Citation, Decision, Severity, VerdictStatus


@dataclass(frozen=True, slots=True)
class TriageInput:
    """One case to screen: a subject and its free-text description.

    The generic decision surface: an HR/policy question is screened into a severity band and
    sensitive bands route to a human. The specialised, number-producing path is the entitlement
    engine below; this remains the intake for free-text questions that carry no structured facts.
    """

    subject: str
    text: str


@dataclass(frozen=True, slots=True)
class TriageResult:
    """The screening decision: a severity, a soft-escalation flag, and cited reasoning."""

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    citations: tuple[Citation, ...] = ()


# --------------------------------------------------------------------------------------------- #
# The entitlement vertical: structured employee facts in, a deterministic worksheet out.
# --------------------------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class EmployeeFacts:
    """The structured facts the entitlement engine reasons over. Obviously synthetic in tests.

    ``employee_ref`` is an opaque, fictional reference, never a real identifier. Every field the
    verdict depends on is here rather than in free text, because a number the engine computes must
    be replayable from data, not parsed from prose.
    """

    employee_ref: str
    jurisdiction: str
    employment_type: str
    months_of_service: int
    leave_taken_days: float = 0.0
    #: Set when the request is tied to a termination or final-pay event. Always consequential:
    #: the engine routes it to a human whatever the arithmetic says.
    termination_linked: bool = False


@dataclass(frozen=True, slots=True)
class EntitlementRequest:
    """One entitlement question: whose facts, which entitlement, as of when."""

    facts: EmployeeFacts
    entitlement: str = "annual_leave"
    #: The date the verdict is computed AS OF, so an effective-window change is deterministic and
    #: a replay a year later does not silently pick a different rule.
    as_of: date | None = None


@dataclass(frozen=True, slots=True)
class RuleHit:
    """One rule the engine applied, with the citation that makes its contribution traceable."""

    rule_id: str
    entitlement: str
    detail: str
    citation: Citation


@dataclass(frozen=True, slots=True)
class EntitlementResult:
    """The deterministic entitlement worksheet plus the review-routable decision fields.

    The first block is what rule R8 routing and the audit trail read (it satisfies
    :class:`~.kernel.ReviewableResult`); the second block is the worksheet a reviewer inspects.
    ``entitled_days`` / ``balance_days`` are ``None`` exactly when ``status`` is ``NEEDS_INFO``:
    a fail-closed verdict carries no number, so nothing downstream can mistake a refusal for a
    computed zero.
    """

    subject: str
    severity: Severity
    decision: Decision
    summary: str
    requires_human_review: bool
    citations: tuple[Citation, ...] = ()

    status: VerdictStatus = VerdictStatus.COMPUTED
    jurisdiction: str = ""
    employment_type: str = ""
    entitled_days: float | None = None
    taken_days: float | None = None
    balance_days: float | None = None
    approval_path: tuple[str, ...] = ()
    rule_hits: tuple[RuleHit, ...] = field(default_factory=tuple)
