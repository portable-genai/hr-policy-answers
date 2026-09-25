"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

This service binds no model port: triage and the entitlement worksheet are deterministic
engines, so they note nothing and their responses carry neither header, and the pill keeps
showing ``no-model``. The route is still proved to carry both headers the day an adapter notes
something, by standing a noting engine in for the real one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance

from hr_policy_answers import config
from hr_policy_answers.api import app as app_module
from hr_policy_answers.domain.models import TriageInput, TriageResult
from hr_policy_answers.domain.triage_service import TriageService

from tests import REPO_ROOT
from tests.fixtures import sample_cases

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"


def _triage(api_client: TestClient) -> dict[str, str]:
    case = sample_cases.ROUTINE_CASE
    response = api_client.post(
        "/v1/triage",
        json={"subject": case.subject, "text": case.text},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert response.status_code == 200, response.text
    return dict(response.headers)


def test_a_deterministic_answer_names_no_model(api_client: TestClient) -> None:
    """Nothing noted, nothing sent: the pill never invents a model the engine did not call."""
    headers = _triage(api_client)
    assert ANSWERED_BY not in headers
    assert SEARCH_USED not in headers
    entitlement = api_client.post(
        "/v1/entitlement",
        json={
            "employee_ref": "EMP-4021 (FICTIONAL)",
            "jurisdiction": "SG",
            "employment_type": "full_time",
            "months_of_service": 40,
            "leave_taken_days": 3.0,
            "termination_linked": False,
        },
        headers={"X-Dev-Persona": "auditor"},
    )
    assert entitlement.status_code == 200, entitlement.text
    assert ANSWERED_BY not in entitlement.headers
    assert SEARCH_USED not in entitlement.headers


class _AnsweringService(TriageService):
    """The real engine, plus what a model adapter that searched would note while it called."""

    def triage(self, case: TriageInput, *, actor: str) -> TriageResult:
        provenance.note_model("fake-answering-model")
        provenance.note_search()
        return super().triage(case, actor=actor)


def test_the_route_names_the_model_that_answered_and_that_it_searched(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "TriageService", _AnsweringService)
    headers = _triage(api_client)
    assert headers[ANSWERED_BY] == "fake-answering-model"
    assert headers[SEARCH_USED] == "true"
    # The next request is a fresh record: an answer never leaks into a later response.
    monkeypatch.setattr(app_module, "TriageService", TriageService)
    assert ANSWERED_BY not in _triage(api_client)


def test_the_pill_starts_from_no_model_because_nothing_here_calls_one() -> None:
    settings = config.Settings.load(REPO_ROOT / "config" / "settings.yaml")
    assert settings.generator_model == "no-model"


def test_generator_model_is_the_setting_the_adapter_reads_and_no_flag_swaps_it() -> None:
    """The latent false banner: a flag that moved the pill but not the model that answered.

    A resolver once named ``models.hard_reasoning`` when ``models.use_hard_reasoning`` was set,
    while no adapter ever read the flag. The pill would then have named a model that never
    answered. The flag is gone; a stray one in a settings object must change nothing.
    """
    models = SimpleNamespace(
        reasoning="the-model-the-adapter-calls",
        hard_reasoning="a-model-nobody-calls",
        use_hard_reasoning=True,
    )
    named = config._model_from_settings(SimpleNamespace(models=models), "models.reasoning")
    assert named == "the-model-the-adapter-calls"


def test_the_hard_reasoning_flag_does_not_exist() -> None:
    settings_file = (REPO_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert "use_hard_reasoning" not in settings_file
    for source in sorted((REPO_ROOT / "src").rglob("*.py")):
        assert "use_hard_reasoning" not in source.read_text(encoding="utf-8"), source
