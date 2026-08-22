"""Entitlement rule packs as data: the versioned, cited policy the engine computes from.

A pack is CONFIGURATION, not code. Each file under ``config/packs/<jurisdiction>/`` is a small,
falsifiable rule set (jurisdiction, employment type, accrual parameters, effective window,
citation to the source clause). The loader is strict on purpose: an UNKNOWN field, a missing
required field or a malformed value REFUSES at load rather than being ignored, because a rule pack
that silently drops a field it did not recognise is a policy nobody reviewed. This is the wave's
pack convention (H2 lands it, H3 mirrors it): the shape is shared, the engines are not.

Pure stdlib plus ``yaml`` (itself stdlib-only at runtime); no web framework, no cloud SDK. A rule
carries its own :class:`~.kernel.Citation` so every number the engine derives from it is
traceable to a clause.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .kernel import Citation

#: The default location packs are read from, relative to the process working directory (the repo
#: root under ``make`` targets and ``/app`` in the image). Overridable by passing an explicit path
#: to :func:`load_pack_set`; never read from the environment here (a two-state env read is exactly
#: what the repo's own gate forbids), so the caller owns any override.
DEFAULT_PACKS_DIR = Path("config") / "packs"

#: Every field a rule mapping may carry. Anything else refuses at load.
_ALLOWED_RULE_FIELDS = frozenset(
    {
        "rule_id",
        "entitlement",
        "employment_type",
        "min_months_service",
        "base_days",
        "increment_days_per_year",
        "max_days",
        "citation_clause",
        "effective_from",
        "effective_to",
    }
)

#: Every field a pack mapping may carry at the top level.
_ALLOWED_PACK_FIELDS = frozenset({"jurisdiction", "version", "source_id", "source_title", "rules"})

_REQUIRED_RULE_FIELDS = frozenset(
    {
        "rule_id",
        "entitlement",
        "employment_type",
        "min_months_service",
        "base_days",
        "increment_days_per_year",
        "max_days",
        "citation_clause",
    }
)


class PackError(ValueError):
    """A rule pack is malformed, carries an unknown field, or fails a schema rule."""


@dataclass(frozen=True, slots=True)
class EntitlementRule:
    """One machine rule: an accrual schedule for one (jurisdiction, entitlement, employment type).

    ``base_days`` accrue once the employee passes ``min_months_service``;
    ``increment_days_per_year`` are added for each COMPLETED year of service beyond the first, up
    to ``max_days``. The engine, not this dataclass, applies that formula; the rule only carries
    the parameters and the citation so the derived number is traceable.
    """

    rule_id: str
    jurisdiction: str
    entitlement: str
    employment_type: str
    min_months_service: int
    base_days: float
    increment_days_per_year: float
    max_days: float
    source_id: str
    source_title: str
    citation_clause: str
    effective_from: date | None
    effective_to: date | None

    def citation(self) -> Citation:
        """The provenance for any number derived from this rule (source + clause)."""
        return Citation(
            source_id=self.source_id,
            title=f"{self.source_title} {self.citation_clause}".strip(),
            snippet=self.rule_id,
        )

    def is_effective_on(self, as_of: date) -> bool:
        """True when ``as_of`` falls inside this rule's effective window (inclusive/half-open)."""
        after_start = self.effective_from is None or as_of >= self.effective_from
        before_end = self.effective_to is None or as_of < self.effective_to
        return after_start and before_end


@dataclass(frozen=True, slots=True)
class PackSet:
    """Every loaded rule, indexed for the engine's lookups. Immutable once built."""

    rules: tuple[EntitlementRule, ...]

    def jurisdictions(self) -> frozenset[str]:
        return frozenset(rule.jurisdiction for rule in self.rules)

    def match(
        self,
        *,
        jurisdiction: str,
        entitlement: str,
        employment_type: str,
        as_of: date,
    ) -> EntitlementRule | None:
        """The single effective rule for this key, or ``None`` when nothing matches.

        Fail closed: an unknown jurisdiction, an entitlement nobody packed, an employment type
        with no rule, or a date outside every effective window all return ``None``, and the engine
        turns that into a no-verdict escalation rather than a guess.
        """
        matches = [
            rule
            for rule in self.rules
            if rule.jurisdiction == jurisdiction
            and rule.entitlement == entitlement
            and rule.employment_type == employment_type
            and rule.is_effective_on(as_of)
        ]
        if not matches:
            return None
        if len(matches) > 1:
            raise PackError(
                f"ambiguous rule set: {len(matches)} rules match "
                f"{jurisdiction}/{entitlement}/{employment_type} effective on {as_of.isoformat()} "
                f"({', '.join(rule.rule_id for rule in matches)}); a key must resolve to one rule"
            )
        return matches[0]


def _as_int(value: Any, field: str, rule_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PackError(f"{rule_id}: field {field!r} must be an integer, got {value!r}")
    return value


def _as_number(value: Any, field: str, rule_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PackError(f"{rule_id}: field {field!r} must be a number, got {value!r}")
    return float(value)


def _as_date(value: Any, field: str, rule_id: str) -> date | None:
    """Parse an optional ISO date. Empty string / absent means the window is open on that side."""
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise PackError(f"{rule_id}: field {field!r} must be an ISO date string, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise PackError(f"{rule_id}: field {field!r} is not an ISO date: {value!r}") from exc


def _rule_from(
    raw: Any, *, source_id: str, source_title: str, jurisdiction: str
) -> EntitlementRule:
    if not isinstance(raw, dict):
        raise PackError(f"{jurisdiction}: each rule must be a mapping, got {type(raw).__name__}")
    rule_id = str(raw.get("rule_id") or "").strip()
    if not rule_id:
        raise PackError(f"{jurisdiction}: a rule is missing its rule_id")
    unknown = set(raw) - _ALLOWED_RULE_FIELDS
    if unknown:
        raise PackError(
            f"{rule_id}: unknown rule field(s) {sorted(unknown)}; a pack that carried a field the "
            "engine does not read would be a policy nobody reviewed"
        )
    missing = _REQUIRED_RULE_FIELDS - set(raw)
    if missing:
        raise PackError(f"{rule_id}: missing required field(s) {sorted(missing)}")
    min_months = _as_int(raw["min_months_service"], "min_months_service", rule_id)
    if min_months < 0:
        raise PackError(f"{rule_id}: min_months_service must not be negative")
    base_days = _as_number(raw["base_days"], "base_days", rule_id)
    increment = _as_number(raw["increment_days_per_year"], "increment_days_per_year", rule_id)
    max_days = _as_number(raw["max_days"], "max_days", rule_id)
    if base_days < 0 or increment < 0 or max_days < 0:
        raise PackError(f"{rule_id}: day counts must not be negative")
    if max_days < base_days:
        raise PackError(f"{rule_id}: max_days ({max_days}) is below base_days ({base_days})")
    return EntitlementRule(
        rule_id=rule_id,
        jurisdiction=jurisdiction,
        entitlement=str(raw["entitlement"]).strip(),
        employment_type=str(raw["employment_type"]).strip(),
        min_months_service=min_months,
        base_days=base_days,
        increment_days_per_year=increment,
        max_days=max_days,
        source_id=source_id,
        source_title=source_title,
        citation_clause=str(raw["citation_clause"]).strip(),
        effective_from=_as_date(raw.get("effective_from"), "effective_from", rule_id),
        effective_to=_as_date(raw.get("effective_to"), "effective_to", rule_id),
    )


def _rules_from_document(data: Any, *, source_path: Path) -> Iterable[EntitlementRule]:
    if not isinstance(data, dict):
        raise PackError(f"{source_path}: a pack file must contain a mapping at the top level")
    unknown = set(data) - _ALLOWED_PACK_FIELDS
    if unknown:
        raise PackError(f"{source_path}: unknown pack field(s) {sorted(unknown)}")
    jurisdiction = str(data.get("jurisdiction") or "").strip()
    source_id = str(data.get("source_id") or "").strip()
    source_title = str(data.get("source_title") or "").strip()
    if not (jurisdiction and source_id and source_title):
        raise PackError(f"{source_path}: jurisdiction, source_id and source_title are all required")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise PackError(f"{source_path}: 'rules' must be a non-empty list")
    return [
        _rule_from(raw, source_id=source_id, source_title=source_title, jurisdiction=jurisdiction)
        for raw in raw_rules
    ]


def load_pack_set(packs_dir: Path | None = None) -> PackSet:
    """Load and validate every ``*.yaml`` pack under ``packs_dir`` into one immutable set.

    An explicit directory that does not exist RAISES: somebody named a location and running on an
    empty rule set instead is how an engine ends up computing on no policy at all. Rule ids must be
    globally unique so a citation is unambiguous.
    """
    root = packs_dir if packs_dir is not None else DEFAULT_PACKS_DIR
    if not root.exists():
        raise PackError(f"packs directory {root} does not exist")
    rules: list[EntitlementRule] = []
    seen: set[str] = set()
    for path in sorted(root.rglob("*.yaml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        for rule in _rules_from_document(loaded, source_path=path):
            if rule.rule_id in seen:
                raise PackError(f"duplicate rule_id {rule.rule_id!r} (from {path})")
            seen.add(rule.rule_id)
            rules.append(rule)
    if not rules:
        raise PackError(f"no rule packs were found under {root}")
    return PackSet(rules=tuple(rules))
