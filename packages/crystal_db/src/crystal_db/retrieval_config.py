import json
import os
from typing import Any, Dict, Optional


DEFAULT_RETRIEVAL_DEFAULTS: Dict[str, Any] = {
    "k": 10,
    "engine": "auto",
    "model": None,
    "model_version": None,
    "text_engine": "caption",
    "text_view": "caption",
    "hybrid": True,
    "w_text": 0.7,
    "w_fp": 0.3,
    "redacted": True,
    "text_sim_threshold": 0.8,
    "fp_sim_threshold": 0.95,
}


def load_retrieval_defaults(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    if not os.path.exists(path):
        raise ValueError(f"config file not found: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("retrieval config must be a JSON object")
    return payload


def resolve_retrieval_value(
    *,
    field: str,
    explicit_value: Any,
    config: Dict[str, Any],
    fallback_defaults: Dict[str, Any],
) -> Any:
    if explicit_value is not None:
        return explicit_value
    if field in config:
        return config[field]
    return fallback_defaults.get(field)
