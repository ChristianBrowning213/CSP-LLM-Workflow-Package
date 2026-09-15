# qlip/experimental/guidance/properties/base.py
from __future__ import annotations
import abc
from typing import Any

class Property(abc.ABC):
    name: str

    @abc.abstractmethod
    def expr(self, allocation: Any):
        """Return a Pyomo linear expression over allocation.m (X/Y/M)."""
        ...
