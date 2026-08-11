"""
Adapter registry. Built-in adapters are registered explicitly (`_BUILTIN`);
third-party adapters are discovered via the `stw.adapters` entry-point group,
so a new package's support doesn't require a PR to this repo.
"""
from __future__ import annotations

from importlib.metadata import entry_points

from stw.adapters.base import Adapter

_BUILTIN: dict[str, type[Adapter]] = {}


def _load_builtins() -> None:
    if _BUILTIN:
        return
    from stw.adapters.hac import HACBaselineAdapter

    _BUILTIN["hac"] = HACBaselineAdapter


def registry() -> dict[str, type[Adapter]]:
    _load_builtins()
    result = dict(_BUILTIN)
    for ep in entry_points(group="stw.adapters"):
        try:
            result[ep.name] = ep.load()
        except Exception:
            continue  # a broken third-party adapter must never break `stw list`
    return result


def get_adapter(name: str) -> type[Adapter]:
    reg = registry()
    if name not in reg:
        available = ", ".join(sorted(reg)) or "(none registered)"
        raise KeyError(f"unknown package {name!r}. Available: {available}")
    return reg[name]
