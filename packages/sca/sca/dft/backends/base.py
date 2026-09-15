"""Generic external DFT-engine adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from sca.dft.schema import DFTCalculationSpec, DFTResult


class DFTBackend(ABC):
    name: str

    @abstractmethod
    def prepare(self, spec: DFTCalculationSpec, out_dir: str | Path) -> Path:
        """Create a reproducible calculation directory without running the engine."""

    @abstractmethod
    def validate_inputs(self, calculation_dir: str | Path) -> list[str]:
        """Return input problems; an empty list means structurally ready."""

    @abstractmethod
    def parse(self, calculation_dir: str | Path) -> DFTResult:
        """Parse engine output without silently repairing it."""

    @abstractmethod
    def validate_outputs(self, calculation_dir: str | Path) -> list[str]:
        """Return output problems; an empty list means required outputs exist."""

    @abstractmethod
    def executable_available(self, executable: str | None = None) -> bool:
        """Return whether the external engine command is resolvable."""

    @abstractmethod
    def version(self, executable: str | None = None) -> str | None:
        """Return external engine version when safely discoverable."""

