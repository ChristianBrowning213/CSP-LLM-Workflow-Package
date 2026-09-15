from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class BackendResult:
    backend_name: str
    ok: bool
    payload: dict[str, Any]


class SolverBackend(Protocol):
    name: str

    def validate(self, request: dict[str, Any]) -> BackendResult: ...

    def solve(self, request: dict[str, Any]) -> BackendResult: ...
