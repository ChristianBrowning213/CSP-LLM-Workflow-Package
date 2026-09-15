from __future__ import annotations

from pathlib import Path


def load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_prompt_pack(prompt_dir: Path) -> dict[str, str]:
    names = ["system_orchestrator.md", "tool_use_policy.md", "skills_index.md"]
    return {name: load_prompt(prompt_dir / name) for name in names}


def load_prompt_pack_v2(prompt_dir: Path) -> dict[str, str]:
    names = [
        "system_orchestrator_v2.md",
        "tool_use_policy.md",
        "skills_index.md",
        "clarification_examples.md",
        "planning_examples.md",
    ]
    return {name: load_prompt(prompt_dir / name) for name in names}


def load_optimization_prompt_pack(prompt_dir: Path) -> dict[str, str]:
    names = [
        "optimization_system.md",
        "optimization_clarification_examples.md",
        "optimization_midloop_examples.md",
    ]
    return {name: load_prompt(prompt_dir / name) for name in names}
