from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schemas import assert_json_serializable

PROMPT_FILE_BY_AGENT = {
    "planner": "planner.system.md",
    "run_manager": "run_manager.system.md",
    "evaluator": "evaluator.system.md",
    "orchestrator": "orchestrator.system.md",
}


def prompt_dir() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def prompt_path_for_agent(agent_name: str, *, base_dir: Path | None = None) -> Path:
    try:
        filename = PROMPT_FILE_BY_AGENT[agent_name]
    except KeyError as exc:
        msg = f"Unknown agent prompt: {agent_name}"
        raise KeyError(msg) from exc
    return (base_dir or prompt_dir()) / filename


def load_agent_prompt(agent_name: str, *, base_dir: Path | None = None) -> str:
    return prompt_path_for_agent(agent_name, base_dir=base_dir).read_text(encoding="utf-8")


def render_agent_prompt(
    agent_name: str,
    context: Mapping[str, Any],
    *,
    base_dir: Path | None = None,
) -> str:
    if not isinstance(context, Mapping):
        msg = "context must be a mapping"
        raise TypeError(msg)

    plain_context = dict(context)
    assert_json_serializable(plain_context)
    template = load_agent_prompt(agent_name, base_dir=base_dir).rstrip()
    context_json = json.dumps(plain_context, indent=2, sort_keys=True)
    return f"{template}\n\nRuntime Context:\n{context_json}\n"


__all__ = [
    "PROMPT_FILE_BY_AGENT",
    "prompt_dir",
    "prompt_path_for_agent",
    "load_agent_prompt",
    "render_agent_prompt",
]
