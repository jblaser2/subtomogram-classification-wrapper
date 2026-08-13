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
    from stw.adapters.dynamo import DynamoAdapter
    from stw.adapters.eman2 import EMAN2Adapter
    from stw.adapters.hac import HACBaselineAdapter
    from stw.adapters.peet import PEETAdapter
    from stw.adapters.preview.dynamo_py import DynamoPreviewAdapter
    from stw.adapters.preview.protomo_py import ProtomoPreviewAdapter
    from stw.adapters.preview.pytom_py import PyTomPreviewAdapter
    from stw.adapters.protomo import ProTomoAdapter
    from stw.adapters.pytom import PyTomAdapter
    from stw.adapters.relion import RELIONAdapter

    _BUILTIN["hac"] = HACBaselineAdapter
    _BUILTIN["dynamo-preview"] = DynamoPreviewAdapter
    _BUILTIN["pytom-preview"] = PyTomPreviewAdapter
    _BUILTIN["protomo-preview"] = ProtomoPreviewAdapter
    _BUILTIN["eman2"] = EMAN2Adapter
    _BUILTIN["pytom"] = PyTomAdapter
    _BUILTIN["relion"] = RELIONAdapter
    _BUILTIN["peet"] = PEETAdapter
    _BUILTIN["protomo"] = ProTomoAdapter
    _BUILTIN["dynamo"] = DynamoAdapter


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


def get_adapter_for_mode(name: str, mode: str) -> type[Adapter]:
    """Resolves a package name against the requested run mode.

    `mode="preview"` prefers a `<name>-preview` adapter when one is
    registered (falling back to the bare name if not — e.g. HAC Baseline has
    no separate preview variant, it's already fast). `mode="native"` always
    uses the bare name, so once a real native adapter for "dynamo"/"pytom"/
    "protomo" lands (later milestones), `mode="native"` keeps resolving to
    it — the `-preview` suffix never collides with a native adapter's name.
    """
    reg = registry()
    if mode == "preview":
        preview_name = f"{name}-preview"
        if preview_name in reg:
            return reg[preview_name]
    if name in reg:
        return reg[name]
    available = ", ".join(sorted(reg)) or "(none registered)"
    raise KeyError(f"unknown package {name!r} for mode={mode!r}. Available: {available}")
