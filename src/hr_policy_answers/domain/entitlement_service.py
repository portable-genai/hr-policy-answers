"""The entitlement service: run the deterministic engine, redact, audit, return the worksheet.

The consequential decision (the balance, the eligibility, the escalation) is the pure
:class:`~.entitlement_engine.EntitlementEngine`; this layer adds the side effects the engine must
not have. It redacts before the audit write (a raw identifier never reaches the WORM record), it
records an already-redacted event, and it returns the engine's result unchanged so the API, the
CLI and the agent all see the same worksheet. Rule R8 routing is the SURFACE's job (each surface
routes in the same call that produced the result); the service does not swallow it.

The engine is injected, so a test and the eval oracle drive the exact object the service runs.
"""

from __future__ import annotations

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.observability import ObservabilityTracerPort
from .entitlement_engine import EntitlementEngine
from .kernel import AuditEvent, utcnow
from .models import EntitlementRequest, EntitlementResult
from .pii import PII_PATTERNS, redacted_citations

#: One span per entitlement verdict. Structural attributes only: see
#: :meth:`EntitlementService.assess`.
_ENTITLEMENT_SPAN = "policy_hr.entitlement"


class EntitlementService:
    """Compute an entitlement verdict and record an already-redacted audit event."""

    def __init__(
        self,
        audit: AuditSinkPort,
        engine: EntitlementEngine,
        *,
        tracer: ObservabilityTracerPort,
    ) -> None:
        self._audit = audit
        self._engine = engine
        self._tracer = tracer

    def assess(self, request: EntitlementRequest, *, actor: str) -> EntitlementResult:
        """Assess ``request`` deterministically and record the already-redacted audit event.

        The whole path runs inside one span. Its attributes are STRUCTURAL only, never the
        employee reference or any fact figure (the audit path masks the reference on
        purpose): a trace backend is not the WORM audit trail; it has no redaction stage, a
        wider read audience and no retention rule written against a regulator's requirement,
        so anything content-shaped that reaches a span has left the boundary the ``redact``
        call below exists to hold, and left it silently.
        """
        with self._tracer.span(
            _ENTITLEMENT_SPAN,
            action="entitlement",
            actor=actor,
            jurisdiction=request.facts.jurisdiction,
        ):
            return self._assess(request, actor=actor)

    def _assess(self, request: EntitlementRequest, *, actor: str) -> EntitlementResult:
        result = self._engine.compute(request)

        # Redact BEFORE the audit write: the raw facts never reach the WORM record. That has to
        # cover the CITATIONS, not just the summary. This layer masked the detail line and then
        # passed ``result.citations`` through untouched, so whatever the engine put in a citation
        # was persisted verbatim next to a summary that had just been scrubbed, and the record
        # kept what the redaction removed. The shipped packs cite a statute and carry nothing
        # personal, which is why the pass-through looked harmless; nothing in the engine's
        # contract promises that, and the engine is INJECTED, so the boundary belongs here rather
        # than in an assumption about which engine is bound.
        #
        # The worksheet itself is still returned unchanged: the API, the CLI and the agent must
        # see the engine's own answer. The other sink it feeds, the human-review-console payload, is
        # masked where
        # it crosses to the shared console (``adapters/_review_payload``).
        detail = (
            f"{result.summary} :: employee={request.facts.employee_ref} "
            f"months={request.facts.months_of_service} taken={request.facts.leave_taken_days}"
        )
        self._audit.record(
            AuditEvent(
                action="entitlement",
                actor=actor,
                decision=result.decision,
                severity=result.severity,
                redacted_summary=redact(detail, PII_PATTERNS),
                citations=redacted_citations(result.citations),
                timestamp=utcnow(),
            )
        )
        return result
