from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "baseline_sanity": {
        "checks": ["schema", "stoichiometry", "symmetry"],
        "novelty_sensitive": False,
    },
    "rediscovery_check": {
        "checks": ["schema", "symmetry", "analogue_distance"],
        "novelty_sensitive": False,
    },
    "analogue_comparison": {
        "checks": ["schema", "analogue_distance", "space_group_match"],
        "novelty_sensitive": False,
    },
    "novelty_sensitive": {
        "checks": ["schema", "duplicate_check", "novelty"],
        "novelty_sensitive": True,
    },
    "benchmark": {
        "checks": ["schema", "stoichiometry", "analogue_distance", "reproducibility"],
        "novelty_sensitive": False,
    },
}


def get_verification_preset(name: str) -> dict[str, Any]:
    if name not in PRESETS:
        raise KeyError(f"Unknown verification preset: {name}")
    return PRESETS[name]
