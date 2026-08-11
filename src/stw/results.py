"""PackageResult lives on its own (not inside adapters/base.py or orchestrator.py)
so both can import it without a circular dependency."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["ok", "failed", "skipped", "missing_requirements", "incompatible"]


@dataclass
class PackageResult:
    package: str
    k: int
    seed: int
    status: Status
    predictions: Path | None = None
    labels: dict[str, int] | None = None
    class_averages: dict[int, Path] = field(default_factory=dict)
    class_average_panel: Path | None = None
    n_per_class: dict[int, int] = field(default_factory=dict)
    elapsed_sec: float | None = None
    log: Path | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "package": self.package,
            "k": self.k,
            "seed": self.seed,
            "status": self.status,
            "predictions": str(self.predictions) if self.predictions else None,
            "class_averages": {str(k): str(v) for k, v in self.class_averages.items()},
            "class_average_panel": str(self.class_average_panel) if self.class_average_panel else None,
            "n_per_class": self.n_per_class,
            "elapsed_sec": self.elapsed_sec,
            "log": str(self.log) if self.log else None,
            "error": self.error,
            "warnings": self.warnings,
            "provenance": self.provenance,
        }
