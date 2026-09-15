from __future__ import annotations

from copy import deepcopy
from typing import Any


CRYSTAL_TOOLS = [
    "crystal.text_search",
    "crystal.agent",
    "crystal.novelty_check",
    "crystal.csp_pack",
    "crystal.bench_retrieval",
]


def apply_crystal_policy_defaults(arguments: dict[str, Any], policy_mode: str) -> tuple[dict[str, Any], list[str]]:
    args = deepcopy(arguments)
    notes: list[str] = []
    if "redacted" not in args:
        args["redacted"] = True
        notes.append("set_default:redacted=true")

    demo_export = bool(args.get("demo_export", False))
    if policy_mode != "demo" and demo_export:
        args["demo_export"] = False
        notes.append("forced:demo_export=false(policy_mode!=demo)")
    elif "demo_export" not in args:
        args["demo_export"] = False
        notes.append("set_default:demo_export=false")
    return args, notes
