"""The rule-pack loader is STRICT: a pack nobody reviewed must not load silently.

A pack is configuration, and the whole point of loading it strictly is that an unknown field, a
missing required field or a malformed value REFUSES rather than being dropped. These tests write
minimal packs to a temp dir and assert each refusal, plus the happy path over the shipped packs.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hr_policy_answers.domain.packs import PackError
from hr_policy_answers.packs import load_pack_set

from tests import REPO_ROOT

_SHIPPED = REPO_ROOT / "config" / "packs"

_VALID = """\
jurisdiction: XX
version: "1.0"
source_id: xx-src
source_title: "Illustrative Act (XX)"
rules:
  - rule_id: xx-al-ft
    entitlement: annual_leave
    employment_type: full_time
    min_months_service: 0
    base_days: 10
    increment_days_per_year: 1
    max_days: 20
    citation_clause: "s1"
    effective_from: "2020-01-01"
    effective_to: ""
"""


def _write(tmp_path: Path, body: str) -> Path:
    pack_dir = tmp_path / "packs" / "xx"
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "pack.yaml").write_text(body, encoding="utf-8")
    return tmp_path / "packs"


def test_the_shipped_packs_load_and_cover_three_markets() -> None:
    packs = load_pack_set(_SHIPPED)
    assert packs.jurisdictions() == {"SG", "AU", "JP"}


def test_a_valid_pack_round_trips_its_fields(tmp_path: Path) -> None:
    packs = load_pack_set(_write(tmp_path, _VALID))
    rule = packs.match(
        jurisdiction="XX",
        entitlement="annual_leave",
        employment_type="full_time",
        as_of=date(2024, 1, 1),
    )
    assert rule is not None
    assert rule.base_days == 10
    assert rule.citation().source_id == "xx-src"


def test_an_unknown_rule_field_refuses(tmp_path: Path) -> None:
    body = _VALID.replace(
        '    citation_clause: "s1"\n', '    citation_clause: "s1"\n    bonus: 5\n'
    )
    with pytest.raises(PackError, match="unknown rule field"):
        load_pack_set(_write(tmp_path, body))


def test_a_missing_required_field_refuses(tmp_path: Path) -> None:
    body = _VALID.replace("    max_days: 20\n", "")
    with pytest.raises(PackError, match="missing required field"):
        load_pack_set(_write(tmp_path, body))


def test_max_below_base_refuses(tmp_path: Path) -> None:
    body = _VALID.replace("    max_days: 20\n", "    max_days: 5\n")
    with pytest.raises(PackError, match="below base_days"):
        load_pack_set(_write(tmp_path, body))


def test_a_non_integer_min_service_refuses(tmp_path: Path) -> None:
    body = _VALID.replace("    min_months_service: 0\n", "    min_months_service: 1.5\n")
    with pytest.raises(PackError, match="must be an integer"):
        load_pack_set(_write(tmp_path, body))


def test_a_duplicate_rule_id_refuses(tmp_path: Path) -> None:
    root = _write(tmp_path, _VALID)
    other = root / "yy"
    other.mkdir(parents=True, exist_ok=True)
    (other / "pack.yaml").write_text(
        _VALID.replace("jurisdiction: XX", "jurisdiction: YY"), "utf-8"
    )
    with pytest.raises(PackError, match="duplicate rule_id"):
        load_pack_set(root)


def test_a_missing_directory_refuses(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="does not exist"):
        load_pack_set(tmp_path / "nope")


def test_an_effective_window_is_honoured(tmp_path: Path) -> None:
    body = _VALID.replace('    effective_from: "2020-01-01"', '    effective_from: "2025-01-01"')
    packs = load_pack_set(_write(tmp_path, body))
    assert (
        packs.match(
            jurisdiction="XX",
            entitlement="annual_leave",
            employment_type="full_time",
            as_of=date(2024, 1, 1),
        )
        is None
    )
    assert (
        packs.match(
            jurisdiction="XX",
            entitlement="annual_leave",
            employment_type="full_time",
            as_of=date(2025, 6, 1),
        )
        is not None
    )
