from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic import PlannerAgent
from sok_llm_orchestrator.agentic.plan_compile import (
    PLAN_COMPILE_SCHEMA_VERSION,
    compile_run_plan_to_tool_proposals,
)
from sok_llm_orchestrator.agentic.tools import TOOL_VALIDATION_SCHEMA_VERSION
import sok_llm_orchestrator.agentic.plan_compile as plan_compile_module


def test_known_crystal_csp_pack_tool_hint_compiles_to_valid_proposal() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "stage": "wide_exploration",
        "plan_as_text": "tool_hint: crystal.csp_pack",
    }

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert result["schema_version"] == PLAN_COMPILE_SCHEMA_VERSION
    assert len(result["proposals"]) == 1
    assert result["proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["proposals"][0]["arguments"] == {
        "case_id": "run-plan-compile",
        "objective_family": "TiO2",
    }
    assert result["validation_results"] == [
        {
            "schema_version": TOOL_VALIDATION_SCHEMA_VERSION,
            "valid": True,
            "tool_name": "crystal.csp_pack",
            "errors": [],
            "warnings": [],
        }
    ]
    assert result["warnings"] == []


def test_planner_agent_default_output_compiles_to_valid_crystal_csp_pack_proposal() -> None:
    run_plan = PlannerAgent().run(
        {
            "overall_goal": "TiO2",
            "run_goal": "retrieve candidates",
            "stage": "wide_exploration",
        }
    )

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert "tool_hint: crystal.csp_pack" in run_plan["plan_as_text"]
    assert len(result["proposals"]) >= 1
    assert result["proposals"][0]["tool_name"] == "crystal.csp_pack"
    assert result["validation_results"][0]["valid"] is True
    assert result["validation_results"][0]["tool_name"] == "crystal.csp_pack"


def test_multiple_ordered_tool_hints_compile_to_valid_ordered_proposals_for_all_six_tools() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "run_id": "run_001",
        "overall_goal": "TiO2",
        "run_goal": "full future csp workflow",
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

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert result["schema_version"] == PLAN_COMPILE_SCHEMA_VERSION
    assert [item["tool_name"] for item in result["proposals"]] == [
        "crystal.csp_pack",
        "spp.run_pipeline",
        "spp.package_for_qlip",
        "qlip.validate_request",
        "qlip.solve",
        "crystal.novelty_check",
    ]
    assert all(item["valid"] is True for item in result["validation_results"])
    assert result["proposals"][0]["arguments"] == {
        "case_id": "run_001",
        "objective_family": "TiO2",
    }
    assert result["proposals"][1]["arguments"] == {
        "case_id": "run_001",
        "corpus_ref": "pending_corpus_ref",
    }
    assert result["proposals"][2]["arguments"] == {
        "case_id": "run_001",
        "spp_package_ref": "pending_spp_package_ref",
    }
    assert result["proposals"][3]["arguments"] == {
        "case_id": "run_001",
        "request_ref": "pending_request_ref",
    }
    assert result["proposals"][4]["arguments"] == {
        "case_id": "run_001",
        "validated_request_ref": "pending_validated_request_ref",
    }
    assert result["proposals"][5]["arguments"] == {
        "case_id": "run_001",
    }
    assert result["warnings"] == [
        "Tool hint spp.run_pipeline uses proposal-time placeholder ref corpus_ref=pending_corpus_ref.",
        "Tool hint spp.package_for_qlip uses proposal-time placeholder ref spp_package_ref=pending_spp_package_ref.",
        "Tool hint qlip.validate_request uses proposal-time placeholder ref request_ref=pending_request_ref.",
        "Tool hint qlip.solve uses proposal-time placeholder ref validated_request_ref=pending_validated_request_ref.",
    ]


def test_spp_tool_hints_compile_with_material_system_metadata() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "run_id": "run_001",
        "overall_goal": "Generate a binary sulfide.",
        "metadata": {"material_system": "ZnS"},
        "plan_as_text": "\n".join(
            [
                "tool_hint: crystal.csp_pack",
                "tool_hint: spp.run_pipeline",
                "tool_hint: spp.package_for_qlip",
            ]
        ),
    }

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert result["proposals"][0]["arguments"]["material_system"] == "ZnS"
    assert result["proposals"][1]["arguments"]["material_system"] == "ZnS"
    assert result["proposals"][2]["arguments"]["material_system"] == "ZnS"


def test_compiler_uses_objective_family_and_run_id_when_present() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "run_id": "case_123",
        "objective_family": "feasibility",
        "overall_goal": "TiO2",
        "plan_as_text": "tool_hint: crystal.csp_pack",
    }

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert result["proposals"][0]["arguments"] == {
        "case_id": "case_123",
        "objective_family": "feasibility",
    }


def test_unknown_tool_hint_is_reported_truthfully() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "tool_hint": "unknown.tool",
    }

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert result["schema_version"] == PLAN_COMPILE_SCHEMA_VERSION
    assert result["proposals"] == []
    assert result["warnings"] == ["Unknown tool_hint: unknown.tool"]
    assert result["validation_results"][0]["schema_version"] == TOOL_VALIDATION_SCHEMA_VERSION
    assert result["validation_results"][0]["valid"] is False
    assert result["validation_results"][0]["tool_name"] == "unknown.tool"
    assert "Unknown tool name" in " ".join(result["validation_results"][0]["errors"])


def test_no_tool_hint_produces_no_proposals() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "plan_as_text": "Review prior artifacts and summarize findings.",
    }

    result = compile_run_plan_to_tool_proposals(run_plan)

    assert result == {
        "schema_version": PLAN_COMPILE_SCHEMA_VERSION,
        "proposals": [],
        "validation_results": [],
        "warnings": [],
    }


def test_compile_run_plan_is_deterministic_json_serializable_and_does_not_mutate_input() -> None:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "overall_goal": "TiO2",
        "run_goal": "retrieve candidates",
        "tool_hint": [
            "crystal.csp_pack",
            "spp.run_pipeline",
            "unknown.tool",
        ],
        "nested": {"alpha": 1},
    }
    run_plan_before = deepcopy(run_plan)

    first = compile_run_plan_to_tool_proposals(run_plan)
    second = compile_run_plan_to_tool_proposals(run_plan)

    assert first == second
    assert json.loads(json.dumps(first))["schema_version"] == PLAN_COMPILE_SCHEMA_VERSION
    assert run_plan == run_plan_before


def test_plan_compile_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(plan_compile_module)
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


def test_plan_compile_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = compile_run_plan_to_tool_proposals({"tool_hint": "unknown.tool"})
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
