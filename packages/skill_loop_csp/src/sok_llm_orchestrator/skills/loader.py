from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def schema_path() -> Path:
    return Path(__file__).resolve().parent / "schema.skillcard.v1.json"


def load_schema() -> dict[str, Any]:
    return json.loads(schema_path().read_text(encoding="utf-8"))


def load_skillcards(skills_dir: Path) -> list[dict[str, Any]]:
    cards = []
    for path in sorted(skills_dir.glob("*.skillcard.json")):
        cards.append(json.loads(path.read_text(encoding="utf-8")))
    return cards


def validate_skillcards(skills_dir: Path) -> list[str]:
    schema = load_schema()
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for path in sorted(skills_dir.glob("*.skillcard.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        file_errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        for err in file_errors:
            pointer = "/" + "/".join(str(part) for part in err.absolute_path)
            errors.append(f"{path.name}{pointer}: {err.message}")
    return errors


def render_skills_index(cards: list[dict[str, Any]]) -> str:
    lines = ["# Skills Index", ""]
    for card in sorted(cards, key=lambda c: c["id"]):
        lines.append(f"- `{card['id']}`: `{card['tool_name']}` - {card['purpose']}")
    lines.append("")
    return "\n".join(lines)
