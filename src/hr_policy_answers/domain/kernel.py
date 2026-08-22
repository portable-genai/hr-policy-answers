"""Vertical-neutral domain kernel: pure-stdlib types the service reasons over.

Taxonomies are ``StrEnum``s from the commons (a member IS its wire value), citations carry
provenance, and the WORM audit record is stored already-redacted. Nothing here imports a web
framework or a cloud SDK (the commons packages it uses are themselves stdlib).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from hex_service_kit.enums import LenientStrEnum


def utcnow() -> datetime:
    """Timezone-aware UTC now (the single clock the domain uses)."""
    return datetime.now(UTC)


class Severity(LenientStrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(LenientStrEnum):
    ALLOWED = "allowed"
    ESCALATED = "escalated"  # routed to a human (maker-checker, P-06)


class VerdictStatus(LenientStrEnum):
    """Whether the deterministic engine reached a numeric verdict, or failed closed to a human.

    ``COMPUTED`` means the engine produced a number from a matched rule. ``NEEDS_INFO`` means it
    refused to guess (unknown jurisdiction, unpacked employment type, a missing fact): there is no
    number, and the result is routed to a human by construction, never auto-answered.
    """

    COMPUTED = "computed"
    NEEDS_INFO = "needs_info"


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to a generated claim (source + optional locator)."""

    source_id: str
    title: str
    snippet: str = ""


@runtime_checkable
class ReviewableResult(Protocol):
    """The shape rule R8 routing needs from any result it may escalate.

    Both the generic decision result and the entitlement result satisfy it, so one review
    converter and one :class:`~..ports.review_router.ReviewRouterPort` serve every producer
    without the router layer depending on any one vertical's model. The members are read-only
    (declared as properties) so a frozen dataclass field satisfies them.
    """

    @property
    def subject(self) -> str: ...
    @property
    def severity(self) -> Severity: ...
    @property
    def decision(self) -> Decision: ...
    @property
    def summary(self) -> str: ...
    @property
    def requires_human_review(self) -> bool: ...
    @property
    def citations(self) -> tuple[Citation, ...]: ...


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, already-redacted record of one interaction (P-04 / rule R2)."""

    action: str
    actor: str
    decision: Decision
    severity: Severity
    redacted_summary: str
    citations: tuple[Citation, ...] = ()
    timestamp: datetime = field(default_factory=utcnow)
