import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

POLICY_FILE = str(Path(__file__).resolve().parent / "configs" / "policies.yaml")


@dataclass(frozen=True)
class SourcePolicy:
    name: str
    allow_cif_store: bool
    allow_cif_return: bool
    allow_derivatives: bool
    allow_export: bool
    license_notes: str


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "1")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _load_yaml_simple(path: str) -> Dict[str, Dict[str, str]]:
    policies: Dict[str, Dict[str, str]] = {}
    current = None
    in_policies = False

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            if raw.startswith("\ufeff"):
                raw = raw.replace("\ufeff", "", 1)
            line = raw.rstrip()
            if not line or line.strip().startswith("#"):
                continue
            if line.startswith("policies:"):
                in_policies = True
                continue
            if not in_policies:
                continue
            if line.startswith("  ") and line.strip().endswith(":") and line.count(":") == 1:
                current = line.strip()[:-1]
                policies[current] = {}
                continue
            if current and line.startswith("    ") and ":" in line:
                key, value = line.strip().split(":", 1)
                policies[current][key.strip()] = _strip_quotes(value.strip())

    return policies


def load_policies(path: Optional[str] = None) -> Dict[str, SourcePolicy]:
    path = path or POLICY_FILE
    if not os.path.exists(path):
        raise FileNotFoundError(f"Policy file not found: {path}")

    raw = _load_yaml_simple(path)
    policies: Dict[str, SourcePolicy] = {}
    for name, values in raw.items():
        policies[name] = SourcePolicy(
            name=name,
            allow_cif_store=_parse_bool(values.get("allow_cif_store", "false")),
            allow_cif_return=_parse_bool(values.get("allow_cif_return", "false")),
            allow_derivatives=_parse_bool(values.get("allow_derivatives", "false")),
            allow_export=_parse_bool(values.get("allow_export", "false")),
            license_notes=values.get("license_notes", ""),
        )
    return policies


def get_policy(policy_name: str, path: Optional[str] = None) -> SourcePolicy:
    policies = load_policies(path)
    if policy_name in policies:
        return policies[policy_name]
    if "default" in policies:
        return policies["default"]
    raise KeyError(f"Policy not found: {policy_name}")
