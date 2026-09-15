from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.execution_plan_adapter import (
    EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION,
    EXECUTABLE_PLAN_SCHEMA_VERSION,
    build_executable_plan_from_compile_result,
    build_executable_plan_report,
)
from sok_llm_orchestrator.agentic.plan_compile import compile_run_plan_to_tool_proposals
import sok_llm_orchestrator.agentic.execution_plan_adapter as adapter_module


def _compile_all_six() -> dict[str, object]:
    return compile_run_plan_to_tool_proposals(
        {
            "schema_version": "agentic_csp.run_plan.v1",
            "run_id": "run_001",
            "overall_goal": "TiO2",
            "stage": "wide_exploration",
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
        }
    )


def test_all_six_valid_proposals_build_ready_dry_run_executable_plan_preserving_order() -> None:
    compile_result = _compile_all_six()

    result = build_executable_plan_from_compile_result(compile_result)

    assert result["schema_version"] == EXECUTABLE_PLAN_SCHEMA_VERSION
    assert result["execution_mode"] == "dry_run"
    assert result["execution_allowed"] is False
    assert result["status"] == "ready_for_dry_run"
    assert result["tool_sequence"] == [
        "crystal.csp_pack",
        "spp.run_pipeline",
        "spp.package_for_qlip",
        "qlip.validate_request",
        "qlip.solve",
        "crystal.novelty_check",
    ]
    assert [step["tool_name"] for step in result["executable_steps"]] == result["tool_sequence"]
    assert [step["step_index"] for step in result["executable_steps"]] == [0, 1, 2, 3, 4, 5]
    assert all(step["execution_allowed"] is False for step in result["executable_steps"])
    assert all(step["execution_mode"] == "dry_run" for step in result["executable_steps"])
    assert all(step["status"] == "pending_dry_run" for step in result["executable_steps"])
    assert result["blocked_reasons"] == []


def test_placeholder_refs_are_detected_for_downstream_tools() -> None:
    compile_result = _compile_all_six()

    result = build_executable_plan_from_compile_result(compile_result)
    placeholder_refs_by_tool = {
        step["tool_name"]: step["audit"]["placeholder_refs"] for step in result["executable_steps"]
    }

    assert placeholder_refs_by_tool["crystal.csp_pack"] == []
    assert placeholder_refs_by_tool["crystal.novelty_check"] == []
    assert placeholder_refs_by_tool["spp.run_pipeline"] == ["corpus_ref"]
    assert placeholder_refs_by_tool["spp.package_for_qlip"] == ["spp_package_ref"]
    assert placeholder_refs_by_tool["qlip.validate_request"] == ["request_ref"]
    assert placeholder_refs_by_tool["qlip.solve"] == ["validated_request_ref"]


def test_no_proposals_blocks_with_blocked_no_proposals() -> None:
    result = build_executable_plan_from_compile_result(
        {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": [],
            "validation_results": [],
            "warnings": [],
        }
    )

    assert result["status"] == "blocked_no_proposals"
    assert result["execution_allowed"] is False
    assert result["executable_steps"] == []
    assert result["blocked_reasons"]


def test_invalid_proposal_blocks_when_require_all_valid_is_true() -> None:
    compile_result = _compile_all_six()
    compile_result["validation_results"][1]["valid"] = False
    compile_result["validation_results"][1]["errors"] = ["corpus_ref mismatch"]

    result = build_executable_plan_from_compile_result(compile_result)

    assert result["status"] == "blocked_invalid_proposals"
    assert result["execution_allowed"] is False
    assert result["executable_steps"] == []
    assert result["blocked_reasons"]


def test_report_summarizes_status_tool_sequence_and_placeholder_counts() -> None:
    plan = build_executable_plan_from_compile_result(_compile_all_six())

    report = build_executable_plan_report(plan)

    assert report == {
        "schema_version": EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION,
        "status": "ready_for_dry_run",
        "execution_mode": "dry_run",
        "execution_allowed": False,
        "step_count": 6,
        "tool_sequence": [
            "crystal.csp_pack",
            "spp.run_pipeline",
            "spp.package_for_qlip",
            "qlip.validate_request",
            "qlip.solve",
            "crystal.novelty_check",
        ],
        "placeholder_ref_count": 4,
        "warnings": [
            "Tool hint spp.run_pipeline uses proposal-time placeholder ref corpus_ref=pending_corpus_ref.",
            "Tool hint spp.package_for_qlip uses proposal-time placeholder ref spp_package_ref=pending_spp_package_ref.",
            "Tool hint qlip.validate_request uses proposal-time placeholder ref request_ref=pending_request_ref.",
            "Tool hint qlip.solve uses proposal-time placeholder ref validated_request_ref=pending_validated_request_ref.",
        ],
        "summary": "Executable dry-run plan is ready with 6 pending steps.",
    }


def test_executable_plan_adapter_is_deterministic_json_serializable_and_does_not_mutate_input() -> None:
    compile_result = _compile_all_six()
    before = deepcopy(compile_result)

    first = build_executable_plan_from_compile_result(compile_result)
    second = build_executable_plan_from_compile_result(compile_result)
    report = build_executable_plan_report(first)

    assert first == second
    assert json.loads(json.dumps(first))["schema_version"] == EXECUTABLE_PLAN_SCHEMA_VERSION
    assert json.loads(json.dumps(report))["schema_version"] == EXECUTABLE_PLAN_REPORT_SCHEMA_VERSION
    assert compile_result == before


def test_execution_plan_adapter_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(adapter_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules


def test_execution_plan_adapter_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = build_executable_plan_from_compile_result(
        {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": [],
            "validation_results": [],
            "warnings": [],
        }
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
