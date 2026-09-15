"""Structured semantic predicates for the paper-diversity benchmark."""

from __future__ import annotations

import json
from typing import Any, Mapping


REQUIRED_SUBSTITUTION_FIELDS = (
    "from_species",
    "to_species",
    "target_orbit",
    "charge_compensation_policy",
)


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def substitution_operation(task: Mapping[str, Any]) -> dict[str, str] | None:
    """Return a complete structured substitution operation, or ``None``.

    Natural-language text is deliberately ignored.  A task counts only when
    the substitution-site intent axis is true and every operation field is
    explicitly populated.
    """

    axes = _object(task.get("intent_axes"))
    operation = _object(task.get("substitution"))
    if axes.get("substitution_site") is not True:
        return None
    if any(not str(operation.get(field) or "").strip() for field in REQUIRED_SUBSTITUTION_FIELDS):
        return None
    old = str(operation["from_species"]).strip()
    new = str(operation["to_species"]).strip()
    if old == new:
        return None
    return {field: str(operation[field]).strip() for field in REQUIRED_SUBSTITUTION_FIELDS}


def is_substitution_sensitive(task: Mapping[str, Any]) -> bool:
    return substitution_operation(task) is not None

