"""Base interfaces for crystal evaluators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from pymatgen.core import Structure

from sca.schemas import EvaluatorResult


class CrystalEvaluator(ABC):
    """Interface implemented by all SCA structure evaluators."""

    name: str
    model_name: str

    @abstractmethod
    def evaluate(self, structure: Structure, input_path: str) -> EvaluatorResult:
        """Evaluate a parsed structure and return a structured result."""


class StructurePredictor(Protocol):
    """Callable used by tests or adapters to predict a scalar property."""

    def __call__(self, structure: Structure, input_path: str) -> float:
        ...
