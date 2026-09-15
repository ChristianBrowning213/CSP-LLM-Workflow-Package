from __future__ import annotations

from sok_llm_orchestrator.agentic.sequence_diagram import build_demo_loop_mermaid_sequence


def test_live_sequence_diagram_contains_required_actors_and_blocks() -> None:
    diagram = build_demo_loop_mermaid_sequence(
        run_plan={"plan_as_text": "tool_hint: crystal.csp_pack"},
        compile_result={"tool_sequence": ["crystal.csp_pack"]},
        executable_plan={"executable_steps": [{"step_index": 0, "tool_name": "crystal.csp_pack"}]},
        execution_run={"status": "completed"},
        tool_parse_report={"tool_sequence": ["crystal.csp_pack"]},
    )

    assert diagram.startswith("```mermaid\nsequenceDiagram\n")
    assert "Researcher/User" in diagram
    assert "LLM Planner" in diagram
    assert "Prompt/Schema Runtime" in diagram
    assert "Tool Parser" in diagram
    assert "Executable Plan Adapter" in diagram
    assert "Gated Executor" in diagram
    assert "Tool Adapter" in diagram
    assert "MCP/Tool Server" in diagram
    assert "Report Writer" in diagram
    assert "loop Each parsed executable step" in diagram
    assert "alt tool succeeds" in diagram
    assert "else tool blocked/fails" in diagram
    assert "No old hardcoded pipeline control loop is used. Parsed executable_plan drives execution." in diagram


def test_showcase_sequence_diagram_uses_showcase_builder_path() -> None:
    diagram = build_demo_loop_mermaid_sequence(
        run_plan={
            "plan_as_text": "\n".join(
                [
                    "tool_hint: crystal.csp_pack",
                    "tool_hint: spp.run_pipeline",
                    "tool_hint: spp.package_for_qlip",
                    "tool_hint: qlip.validate_request",
                    "tool_hint: qlip.solve",
                    "tool_hint: crystal.novelty_check",
                ]
            ),
            "metadata": {"plan_source": "deterministic_showcase"},
        },
        compile_result={"tool_sequence": ["crystal.csp_pack", "spp.run_pipeline"]},
        executable_plan={"executable_steps": [{"step_index": 0, "tool_name": "crystal.csp_pack"}]},
        execution_run={"status": "completed"},
        tool_parse_report={"tool_sequence": ["crystal.csp_pack", "spp.run_pipeline"]},
    )

    assert "Showcase Plan Builder" in diagram
    assert "Researcher/User" in diagram
    assert "Showcase->>Parser: deterministic RunPlan with six tool_hint lines" in diagram
    assert "LLM Planner" not in diagram
