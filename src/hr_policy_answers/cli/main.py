"""Minimal stdlib CLI: assess an entitlement, screen a case, or verify the audit chain.

argparse only, no extra deps. ``assess`` is the deterministic entitlement path (the vertical's
headline); ``triage`` is the generic free-text screening surface. Both route consequential results
to human review in the same call that produced them (rule R8).
"""

from __future__ import annotations

import argparse
import sys

from hex_service_kit.logging import configure_logging

from ..config import build_container
from ..domain.entitlement_service import EntitlementService
from ..domain.models import EmployeeFacts, EntitlementRequest, TriageInput
from ..domain.triage_service import TriageService
from ..packs import default_engine

_ENTITLEMENT_ACTION = "hr_policy_answers:entitlement"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hr_policy_answers")
    sub = parser.add_subparsers(dest="command", required=True)

    triage_cmd = sub.add_parser("triage", help="Screen a single free-text case.")
    triage_cmd.add_argument("subject")
    triage_cmd.add_argument("text")
    triage_cmd.add_argument("--actor", default="cli-user@bank.example")
    triage_cmd.add_argument(
        "--tenant", default="", help="Tenant partition asserted to human-review-console."
    )

    assess_cmd = sub.add_parser("assess", help="Compute an HR entitlement deterministically.")
    assess_cmd.add_argument("employee_ref")
    assess_cmd.add_argument("jurisdiction", help="SG, AU or JP.")
    assess_cmd.add_argument("employment_type", help="full_time or part_time.")
    assess_cmd.add_argument("months_of_service", type=int)
    assess_cmd.add_argument("--taken", type=float, default=0.0, help="Leave days already taken.")
    assess_cmd.add_argument("--termination-linked", action="store_true")
    assess_cmd.add_argument("--entitlement", default="annual_leave")
    assess_cmd.add_argument("--actor", default="cli-user@bank.example")
    assess_cmd.add_argument(
        "--tenant", default="", help="Tenant partition asserted to human-review-console."
    )

    args = parser.parse_args(argv)
    container = build_container()
    # Idempotent: a process that is both an API app and a CLI configures once.
    configure_logging(container.settings.profile, service="hr-policy-answers")

    if args.command == "triage":
        service = TriageService(container.audit, tracer=container.tracer)
        result = service.triage(TriageInput(subject=args.subject, text=args.text), actor=args.actor)
        print(f"{result.subject}: {result.severity.value} ({result.decision.value})")
        print(f"  requires_human_review: {result.requires_human_review}")
        if result.requires_human_review:
            # Rule R8 on the CLI path too: the same escalation, the same router. A surface that
            # only printed the flag would be a second place for an escalation to stop.
            ref = container.review_router.route(result, maker=args.actor, tenant=args.tenant)
            print(f"  routed to human review: {ref}")
        return 0

    if args.command == "assess":
        ent_service = EntitlementService(container.audit, default_engine(), tracer=container.tracer)
        ent = ent_service.assess(
            EntitlementRequest(
                facts=EmployeeFacts(
                    employee_ref=args.employee_ref,
                    jurisdiction=args.jurisdiction,
                    employment_type=args.employment_type,
                    months_of_service=args.months_of_service,
                    leave_taken_days=args.taken,
                    termination_linked=args.termination_linked,
                ),
                entitlement=args.entitlement,
            ),
            actor=args.actor,
        )
        print(f"{ent.subject}: {ent.status.value} ({ent.decision.value})")
        print(f"  entitled: {ent.entitled_days}  taken: {ent.taken_days}")
        print(f"  balance: {ent.balance_days}")
        print(f"  approval path: {' -> '.join(ent.approval_path)}")
        print(f"  requires_human_review: {ent.requires_human_review}")
        if ent.requires_human_review:
            ref = container.review_router.route(
                ent, maker=args.actor, tenant=args.tenant, action=_ENTITLEMENT_ACTION
            )
            print(f"  routed to human review: {ref}")
        return 0

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
