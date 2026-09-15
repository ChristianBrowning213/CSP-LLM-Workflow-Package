from __future__ import annotations

import json

from sok_llm_orchestrator.agentic.prompting import (
    load_agent_prompt,
    prompt_dir,
    prompt_path_for_agent,
    render_agent_prompt,
)


def test_prompt_path_and_load_for_known_agent() -> None:
    path = prompt_path_for_agent("planner")
    assert path.parent == prompt_dir()
    assert path.name == "planner.system.md"
    content = load_agent_prompt("planner")
    assert "Planner agent" in content or "Planner Agent" in content


def test_render_agent_prompt_is_deterministic_and_json_friendly() -> None:
    context = {
        "expected_schema_name": "run_plan",
        "expected_schema_version": "agentic_csp.run_plan.v1",
        "agent_name": "planner",
    }
    rendered = render_agent_prompt("planner", context)
    assert "Runtime Context:" in rendered
    assert '"agent_name": "planner"' in rendered
    assert '"expected_schema_version": "agentic_csp.run_plan.v1"' in rendered
    assert json.loads(json.dumps({"prompt": rendered}))["prompt"] == rendered


def test_unknown_agent_prompt_raises_key_error() -> None:
    try:
        _ = load_agent_prompt("unknown")
    except KeyError as exc:
        assert "Unknown agent prompt" in str(exc)
    else:
        raise AssertionError("Expected KeyError for unknown agent prompt")
