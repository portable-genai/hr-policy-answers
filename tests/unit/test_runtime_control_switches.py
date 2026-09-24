"""Review routing has a switch, default on, and every caller says what happened to a hand-off.

The fleet's runtime-control contract (2026-09-24). Review routing is the one cheap runtime
control this service has: ``POLICYHR_REVIEW_ROUTING`` is read in three states; off binds a
disabled router and says so at startup; on under the managed profile refuses to boot without a
console; and the triage and entitlement paths on the API, the agent tools and the CLI report
``review_routing`` rather than failing an already-computed result when the console is
unreachable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hr_policy_answers.adapters.controls import (
    DisabledReviewRouter,
    RecordingReviewRouter,
    ReviewRouting,
)
from hr_policy_answers.agent import tools
from hr_policy_answers.cli.main import main as cli_main
from hr_policy_answers.config import (
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    ProfileChoice,
    Settings,
    build_container,
    warn_switched_off,
)
from hr_policy_answers.domain.triage_service import TriageService
from hr_policy_answers.envread import ConfiguredEmptyError

from tests.conftest import LOOPBACK_PEER, local_settings, reimport
from tests.fixtures import sample_cases

_AUDITOR = {"X-Dev-Persona": "auditor"}
_LOCAL_ROUTE = "hr_policy_answers.adapters.local.review_router.LocalReviewRouter.route"
_CONSEQUENTIAL = {
    "employee_ref": "EMP-7788 (FICTIONAL)",
    "jurisdiction": "AU",
    "employment_type": "full_time",
    "months_of_service": 24,
    "leave_taken_days": 5.0,
    "termination_linked": True,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REVIEW_ROUTING_ENV, raising=False)
    monkeypatch.delenv("HUMAN_REVIEW_URL", raising=False)


def _client() -> TestClient:
    """A fresh local app, so its per-process container reads this test's posture."""
    return TestClient(reimport("hr_policy_answers.api.app").app, client=LOOPBACK_PEER)


def _escalated() -> Any:
    container = build_container(local_settings())
    result = TriageService(container.audit, tracer=container.tracer).triage(
        sample_cases.ESCALATING_CASE, actor=sample_cases.ACTOR
    )
    assert result.requires_human_review
    return result


def _managed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hr_policy_answers.config.resolve_profile",
        lambda environ=None: ProfileChoice(profile="gcp", explicit=True),
    )


class _Accepting:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def route(self, result: Any, *, maker: str, tenant: str = "", action: str = "") -> str:
        self.actions.append(action)
        return "review-1"


class _Refusing:
    def route(self, result: Any, *, maker: str, tenant: str = "", action: str = "") -> str:
        raise ConnectionError("console unreachable")


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_routing_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(review_routing=True)


def test_routing_switched_off_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.switched_off() == (REVIEW_ROUTING_ENV,)


def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=REVIEW_ROUTING_ENV):
        Settings.load()


def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "sometimes")
    with pytest.raises(ValueError, match=REVIEW_ROUTING_ENV):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled router, and says so once
# --------------------------------------------------------------------------- #
def test_off_binds_the_disabled_router() -> None:
    settings = local_settings(controls=ControlSwitches(review_routing=False))
    assert isinstance(Container(settings).review_router, DisabledReviewRouter)


def test_on_binds_the_profile_router() -> None:
    assert not isinstance(Container(local_settings()).review_router, DisabledReviewRouter)


def test_the_off_posture_is_logged_once_however_many_containers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    warn_switched_off.cache_clear()
    settings = local_settings(controls=ControlSwitches(review_routing=False))
    with caplog.at_level(logging.WARNING, logger="hr_policy_answers.config"):
        for _ in range(3):
            build_container(settings)
    assert caplog.text.count(REVIEW_ROUTING_ENV) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under the managed profile
# --------------------------------------------------------------------------- #
def test_routing_on_under_gcp_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _managed(monkeypatch)
    with pytest.raises(ConfiguredEmptyError, match="HUMAN_REVIEW_URL"):
        Settings.load()


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    _managed(monkeypatch)
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "false")
    assert Settings.load().controls.review_routing is False


def test_routing_on_under_gcp_with_a_console_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _managed(monkeypatch)
    monkeypatch.setenv("HUMAN_REVIEW_URL", "https://review.example.test")
    assert Settings.load().review_url == "https://review.example.test"


# --------------------------------------------------------------------------- #
# The four routing outcomes, and the console label carried through
# --------------------------------------------------------------------------- #
def test_routing_outcomes_take_each_of_their_four_values() -> None:
    result = _escalated()

    assert RecordingReviewRouter(_Accepting()).outcome is ReviewRouting.NOT_REQUIRED

    inner = _Accepting()
    routed = RecordingReviewRouter(inner)
    assert routed.route(result, maker="m", action="hr_policy_answers:entitlement") == "review-1"
    assert routed.outcome is ReviewRouting.ROUTED
    assert inner.actions == ["hr_policy_answers:entitlement"]

    off = RecordingReviewRouter(DisabledReviewRouter(local_settings()))
    assert off.route(result, maker="m") == ""
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    assert failed.route(result, maker="m") == ""
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="hr_policy_answers.adapters.controls"):
        assert failed.route(_escalated(), maker="m") == ""
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


# --------------------------------------------------------------------------- #
# Every caller reports it: the API, the agent tools, the CLI
# --------------------------------------------------------------------------- #
def _calls(client: TestClient) -> list[Any]:
    case = sample_cases.ESCALATING_CASE
    return [
        client.post(
            "/v1/triage", json={"subject": case.subject, "text": case.text}, headers=_AUDITOR
        ),
        client.post("/v1/entitlement", json=_CONSEQUENTIAL, headers=_AUDITOR),
    ]


@pytest.fixture()
def client() -> Iterator[TestClient]:
    with _client() as c:
        yield c


def test_the_api_reports_a_routed_hand_off(client: TestClient) -> None:
    for response in _calls(client):
        body = response.json()
        assert body["review_routing"] == "routed"
        assert body["review_ref"]


def test_the_api_reports_nothing_to_route(client: TestClient) -> None:
    routine = {**_CONSEQUENTIAL, "jurisdiction": "SG", "months_of_service": 40}
    routine.update(leave_taken_days=3.0, termination_linked=False)
    body = client.post("/v1/entitlement", json=routine, headers=_AUDITOR).json()
    assert body["requires_human_review"] is False
    assert body["review_routing"] == "not_required"


def test_the_api_reports_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    with _client() as client:
        for response in _calls(client):
            assert response.json()["review_routing"] == "off"
            assert response.json()["review_ref"] == ""


def test_the_api_reports_a_failed_hand_off_instead_of_failing_the_request(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    for response in _calls(client):
        assert response.status_code == 200
        assert response.json()["review_routing"] == "failed"
        assert response.json()["review_ref"] == ""


def test_the_agent_tools_report_the_hand_off(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = local_settings()
    case = sample_cases.ESCALATING_CASE
    assert tools.triage_case(case.subject, case.text, settings=settings)["review_routing"] == (
        "routed"
    )

    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    failed = tools.assess_entitlement(**_CONSEQUENTIAL, settings=settings)
    assert failed["review_routing"] == "failed"
    assert failed["review_ref"] == ""


def test_the_cli_reports_the_hand_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    case = sample_cases.ESCALATING_CASE
    assert cli_main(["triage", case.subject, case.text]) == 0
    assert "human review hand-off : routed" in capsys.readouterr().out

    monkeypatch.setattr(_LOCAL_ROUTE, _Refusing.route)
    args = ["assess", "EMP-7788 (FICTIONAL)", "AU", "full_time", "24"]
    assert cli_main([*args, "--taken", "5", "--termination-linked"]) == 0
    assert "human review hand-off : failed" in capsys.readouterr().out
