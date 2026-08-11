"""
What an adapter can actually be asked to do. Compared against a RunConfig at
preflight — before any package launches — so a mismatch (e.g. "unaligned"
input given to a package that only ever applies existing poses) is a clear
error immediately, not a silently wrong result 30 minutes later.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from stw.spec import AlignmentState, MaskKind, WedgeKind


@dataclass(frozen=True)
class Capabilities:
    mask_kinds: frozenset[MaskKind] = frozenset({MaskKind.NONE, MaskKind.SPHERE, MaskKind.CYLINDER})
    mask_is_geometric_only: bool = False  # e.g. ProTomo's native primitives, not a volume file
    wedge: frozenset[WedgeKind] = frozenset({WedgeKind.NONE})
    alignment_states: frozenset[AlignmentState] = frozenset({AlignmentState.FINE})
    does_own_alignment: bool = False
    variable_k: bool = True
    k_range: tuple[int, int | None] = (2, None)
    deterministic: bool = False
    seed_semantics: Literal["true_seed", "run_index", "none"] = "true_seed"
    gpu: Literal["required", "optional", "unused"] = "unused"
    emits_native_class_averages: bool = False
    parallelism: Literal["none", "threads", "mpi", "matlab_parpool"] = "none"
    min_particles: int = 8


@dataclass(frozen=True)
class Incompatibility:
    package: str
    severity: Literal["error", "warning"]
    field: str
    message: str
    suggestion: str | None = None


def validate_job(
    package: str, caps: Capabilities, *, k: int, mask_kind: MaskKind, wedge_kind: WedgeKind,
    alignment_state: AlignmentState, n_particles: int,
) -> list[Incompatibility]:
    """Default capability-vs-config check every adapter gets for free; override
    only when a package needs a subtler rule than these."""
    problems: list[Incompatibility] = []

    if alignment_state not in caps.alignment_states:
        if alignment_state == AlignmentState.UNALIGNED:
            problems.append(Incompatibility(
                package, "error", "alignment_state",
                f"{package} assumes pre-aligned input; it applies existing poses rather than "
                "searching for them.",
                suggestion="Align particles first (a dedicated `stw align` step is planned "
                "post-v0.1), or drop this package from the run.",
            ))
        else:
            problems.append(Incompatibility(
                package, "warning", "alignment_state",
                f"{package} was only validated on {sorted(s.value for s in caps.alignment_states)} "
                f"input, not {alignment_state.value!r}.",
            ))

    if mask_kind not in caps.mask_kinds and mask_kind != MaskKind.AUTO:
        problems.append(Incompatibility(
            package, "error", "mask.kind",
            f"{package} does not support mask kind {mask_kind.value!r} "
            f"(supports: {sorted(m.value for m in caps.mask_kinds)}).",
        ))

    if wedge_kind not in caps.wedge and wedge_kind != WedgeKind.NONE:
        problems.append(Incompatibility(
            package, "warning", "wedge.kind",
            f"{package} ignores {wedge_kind.value} wedge info — it runs with wedge weighting off "
            "or a fixed model that this input doesn't reach.",
            suggestion="This is recorded in the run report; the comparison figure caption will "
            "flag it so results stay honestly interpretable.",
        ))

    if not caps.variable_k:
        problems.append(Incompatibility(
            package, "warning", "k", f"{package} may not honor an arbitrary k value.",
        ))
    else:
        lo, hi = caps.k_range
        if k < lo or (hi is not None and k > hi):
            problems.append(Incompatibility(
                package, "error", "k", f"{package} supports k in [{lo}, {hi or 'inf'}], got k={k}.",
            ))

    if n_particles < caps.min_particles:
        problems.append(Incompatibility(
            package, "error", "particles",
            f"{package} needs at least {caps.min_particles} particles, got {n_particles}.",
        ))

    return problems
