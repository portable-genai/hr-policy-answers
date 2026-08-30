"""The config boundary for entitlement rule packs: the only place a pack file is parsed.

A pack is the client's policy, so validating one is domain logic and lives in
:mod:`hr_policy_answers.domain.packs`. What lives HERE is the part that touches the world
outside the hexagon: where the shipped packs sit, reading those bytes, and turning YAML into
plain Python mappings. That split is what lets the core import nothing but the standard
library : the engine is handed data, never a parser.

It is also what lets a pack arrive from somewhere that is not a file. Anything able to produce
``(source, mapping)`` pairs : a config map, a mounted secret, a fixture : feeds
:func:`~hr_policy_answers.domain.packs.build_pack_set` directly, with no YAML involved.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .domain.entitlement_engine import EntitlementEngine
from .domain.packs import PackError, PackSet, build_pack_set

__all__ = [
    "DEFAULT_PACKS_DIR",
    "default_engine",
    "default_pack_set",
    "load_pack_set",
    "read_pack_documents",
]

#: The default location packs are read from, relative to the process working directory (the repo
#: root under ``make`` targets and ``/app`` in the image). Overridable by passing an explicit path
#: to :func:`load_pack_set`; never read from the environment here (a two-state env read is exactly
#: what the repo's own gate forbids), so the caller owns any override.
DEFAULT_PACKS_DIR = Path("config") / "packs"


def read_pack_documents(root: Path) -> list[tuple[str, Any]]:
    """Parse every ``*.yaml`` pack under ``root`` into ``(source, parsed)`` pairs.

    Sorted, so the order a refusal reports is the order on disk. Nothing is validated here: a
    document that is not a mapping is passed on exactly as parsed, because judging that is the
    core's job and this function must not grow a second opinion about it.
    """
    return [
        (str(path), yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(root.rglob("*.yaml"))
    ]


def load_pack_set(packs_dir: Path | None = None) -> PackSet:
    """Read and validate every ``*.yaml`` pack under ``packs_dir`` into one immutable set.

    An explicit directory that does not exist RAISES: somebody named a location, and running on
    an empty rule set instead is how an engine ends up computing on no policy at all. That
    refusal belongs here rather than in the core, because whether a directory exists is a fact
    about a filesystem and the core has no filesystem.
    """
    root = packs_dir if packs_dir is not None else DEFAULT_PACKS_DIR
    if not root.exists():
        raise PackError(f"packs directory {root} does not exist")
    return build_pack_set(read_pack_documents(root), origin=str(root))


@lru_cache(maxsize=1)
def default_pack_set() -> PackSet:
    """The packs shipped under ``config/packs``, loaded once. Callers may inject their own."""
    return load_pack_set()


def default_engine() -> EntitlementEngine:
    """An engine bound to the shipped packs (the offline default the surfaces build)."""
    return EntitlementEngine(default_pack_set())
