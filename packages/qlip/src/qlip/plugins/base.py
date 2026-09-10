from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class GuidanceContribution:
    """Container for optional guidance effects on the model."""

    kind: str
    data: Dict[str, Any]


class ConstraintPlugin:
    id: str = ""
    title: str = ""
    description: str = ""
    tags: List[str] = []
    params_schema: Dict[str, Any] = {}
    capabilities: Dict[str, Any] = {}
    version: str = "1.0"

    @classmethod
    def apply(cls, allocation, params: Dict[str, Any]) -> None:
        raise NotImplementedError


class GuidancePlugin:
    id: str = ""
    title: str = ""
    description: str = ""
    tags: List[str] = []
    params_schema: Dict[str, Any] = {}
    capabilities: Dict[str, Any] = {}
    version: str = "1.0"

    @classmethod
    def apply(cls, allocation, invocation: Dict[str, Any], guidance_mode: str) -> List[GuidanceContribution]:
        return []
