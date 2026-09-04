"""Canonical synthetic cases, shared by the unit and contract suites.

Every party is obviously fictional and every address is an ``.example`` domain or an RFC 5737 /
RFC 3849 literal. One canonical escalating case and one canonical routine case are enough for
the contract suite: parity means the SAME request through every implementation, so the request
has to have one home rather than being retyped per test.
"""

from __future__ import annotations

from hr_policy_answers.domain.models import (
    EmployeeFacts,
    EntitlementRequest,
    TriageInput,
)

#: The verified principal the tests attribute work to (never a client-asserted actor).
ACTOR = "analyst@bank.example"

#: A tenant partition, so the outbound-review assertions are not all on the empty string.
TENANT = "demo-bank"

#: A case that MUST escalate: the deterministic band is HIGH, so rule R8 routing applies.
ESCALATING_CASE = TriageInput(
    subject="Acme Holdings (FICTIONAL)",
    text="urgent data breach reported by the branch",
)

#: A case that must NOT escalate: a router that manufactured a review here would be lying.
ROUTINE_CASE = TriageInput(
    subject="Beta Trading (FICTIONAL)",
    text="routine note about a stationery order",
)

#: A planted identifier, so a redaction assertion has an independent literal to look for
#: rather than trusting the pattern pack to agree with itself.
PLANTED_NRIC = "S1234567D"

#: The second planted literal. An address and a national id take different pack rows, so a
#: single planted token cannot tell "the boundary held" from "one row happened to match".
PLANTED_EMAIL = "ops@gamma.example"

#: An escalating case that also carries personal data, for the redact-before-anything proofs.
#:
#: The identifier sits in the SUBJECT as well as the body, because an HR case is filed ABOUT a
#: named employee and that is how a real one arrives. While the fixture planted it only in the
#: free text, every LOCATOR built out of the subject stayed unproven: the citation
#: ``source_id`` the triage service composes as ``case:<subject>``, and the ``case_ref`` and
#: ``source_key`` the human-review-console payload derives from it. The snippet was masked and the
#: locator
#: beside it carried the identifier verbatim.
PII_CASE = TriageInput(
    subject=f"Grievance for employee {PLANTED_NRIC} (FICTIONAL)",
    text=f"urgent breach, NRIC {PLANTED_NRIC} and mail {PLANTED_EMAIL} on file",
)

# --------------------------------------------------------------------------------------------- #
# Entitlement fixtures: obviously synthetic employees, one per verdict shape.
# --------------------------------------------------------------------------------------------- #

#: A routine, within-entitlement question: computed, auto-approved, NOT routed.
ROUTINE_ENTITLEMENT = EntitlementRequest(
    facts=EmployeeFacts(
        employee_ref="EMP-4021 (FICTIONAL)",
        jurisdiction="SG",
        employment_type="full_time",
        months_of_service=40,
        leave_taken_days=3.0,
    ),
)

#: A consequential (termination-linked) question: computed, escalated, routed.
CONSEQUENTIAL_ENTITLEMENT = EntitlementRequest(
    facts=EmployeeFacts(
        employee_ref="EMP-7788 (FICTIONAL)",
        jurisdiction="AU",
        employment_type="full_time",
        months_of_service=24,
        leave_taken_days=5.0,
        termination_linked=True,
    ),
)

#: A fail-closed question: no packed rule for the key, so the engine refuses and routes.
FAILCLOSED_ENTITLEMENT = EntitlementRequest(
    facts=EmployeeFacts(
        employee_ref="EMP-3380 (FICTIONAL)",
        jurisdiction="JP",
        employment_type="part_time",
        months_of_service=30,
    ),
)

#: A consequential question carrying a planted national id in the employee reference, for the
#: redact-before-audit proof on the entitlement path.
PII_ENTITLEMENT = EntitlementRequest(
    facts=EmployeeFacts(
        employee_ref=f"EMP NRIC {PLANTED_NRIC} (FICTIONAL)",
        jurisdiction="SG",
        employment_type="full_time",
        months_of_service=30,
        leave_taken_days=2.0,
        termination_linked=True,
    ),
)
