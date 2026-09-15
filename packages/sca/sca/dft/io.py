"""DFT configuration and record I/O helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_mapping(path: str | Path) -> dict[str, Any]:
    """Read JSON or a deliberately small, flat YAML subset without hidden defaults."""

    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore[import-not-found]

            value = yaml.safe_load(text)
        except ImportError:
            value = _minimal_yaml(text)
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a mapping: {source}")
    return value


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _minimal_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if stripped.startswith(("-", " ")) or ":" not in stripped:
            raise ValueError("Install PyYAML for nested YAML configuration")
        key, raw = (part.strip() for part in stripped.split(":", 1))
        lowered = raw.lower()
        if lowered in {"true", "false"}:
            value: Any = lowered == "true"
        elif lowered in {"null", "~", ""}:
            value = None
        else:
            try:
                value = float(raw) if "." in raw or "e" in lowered else int(raw)
            except ValueError:
                value = raw.strip("'\"")
        result[key] = value
    return result
