"""The /v1/entitlement surface: verified-principal identity, deterministic worksheet, R8 routing.

The endpoint computes with the pure engine and routes consequential results in the same request.
These tests drive it through the shared loopback ``api_client`` fixture (the only posture the local
profile serves), and assert the worksheet, the fail-closed shape and the R8 routing reference.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _body(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "employee_ref": "EMP-4021 (FICTIONAL)",
        "jurisdiction": "SG",
        "employment_type": "full_time",
        "months_of_service": 40,
        "leave_taken_days": 3.0,
        "termination_linked": False,
    }
    base.update(overrides)
    return base


def test_a_routine_entitlement_is_computed_and_not_routed(api_client: TestClient) -> None:
    resp = api_client.post("/v1/entitlement", json=_body(), headers={"X-Dev-Persona": "auditor"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "computed"
    assert body["balance_days"] == 6.0
    assert body["requires_human_review"] is False
    assert body["review_ref"] == ""
    assert body["rule_hits"], "a computed number must cite the rule it came from"


def test_a_termination_linked_entitlement_is_routed(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/entitlement",
        json=_body(
            jurisdiction="AU", months_of_service=24, leave_taken_days=5.0, termination_linked=True
        ),
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["requires_human_review"] is True
    assert body["severity"] == "critical"
    # Rule R8: the escalation was routed, not merely flagged.
    assert body["review_ref"], "a consequential entitlement with no routing reference went nowhere"


def test_an_unpacked_key_fails_closed_with_no_number(api_client: TestClient) -> None:
    resp = api_client.post(
        "/v1/entitlement",
        json=_body(jurisdiction="JP", employment_type="part_time"),
        headers={"X-Dev-Persona": "auditor"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "needs_info"
    assert body["balance_days"] is None
    assert body["requires_human_review"] is True
    assert body["review_ref"], "a fail-closed result must still route to a human"


def test_the_endpoint_requires_a_verified_principal(api_client: TestClient) -> None:
    resp = api_client.post("/v1/entitlement", json=_body(), headers={"X-Dev-Persona": "ghost"})
    assert resp.status_code == 401
