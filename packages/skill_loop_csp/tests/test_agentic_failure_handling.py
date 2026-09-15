from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.failure_handling import (
    FAILURE_HANDLING_SCHEMA_VERSION,
    handle_inspection_failures,
)
import sok_llm_orchestrator.agentic.failure_handling as failure_handling_module


def _inspection_clear() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.result_inspection.v1",
        "status": "clear",
        "inspected_steps": [
            {
                "step_index": 0,
                "tool_name": "crystal.csp_pack",
                "input_status": "would_execute",
                "inspection_status": "clear",
                "detected_issue": None,
                "recommended_action": "continue",
            }
        ],
        "blocked_reasons": [],
        "recovery_recommendations": [],
        "warnings": [],
    }


def _inspection_blocked_noop() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.result_inspection.v1",
        "status": "blocked",
        "inspected_steps": [],
        "blocked_reasons": ["Execution handoff is not ready for a future executor."],
        "recovery_recommendations": [],
        "warnings": [],
    }


def _inspection_step(issue: str, action: str, status: str) -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.result_inspection.v1",
        "status": status,
        "inspected_steps": [
            {
                "step_index": 0,
                "tool_name": "crystal.csp_pack",
                "input_status": "would_execute",
                "inspection_status": status if status != "recovery_recommended" else "recovery_recommended",
                "detected_issue": issue,
                "recommended_action": action,
            }
        ],
        "blocked_reasons": ["Result inspection blocked the next stage."] if action == "block_next_stage" else [],
        "recovery_recommendations": [f"crystal.csp_pack: {action}"] if status == "recovery_recommended" else [],
        "warnings": [],
    }


def test_handle_inspection_failures_clear_results_in_no_action_required() -> None:
    inspection = _inspection_clear()
    before = deepcopy(inspection)

    result = handle_inspection_failures(inspection)

    assert inspection == before
    assert result["schema_version"] == FAILURE_HANDLING_SCHEMA_VERSION
    assert result["status"] == "no_action_required"
    assert result["actions"][0]["action_type"] == "continue"
    assert result["actions"][0]["detected_issue"] is None


def test_handle_inspection_failures_blocked_noop_execution_stays_blocked() -> None:
    result = handle_inspection_failures(_inspection_blocked_noop())

    assert result["status"] == "blocked"
    assert result["actions"] == []
    assert result["blocked_reasons"] == [
        "Execution handoff is not ready for a future executor."
    ]


def test_handle_inspection_failures_zero_cifs_blocks_next_stage() -> None:
    result = handle_inspection_failures(
        _inspection_step("zero_cifs", "block_next_stage", "blocked")
    )

    assert result["status"] == "blocked"
    assert result["actions"][0]["action_type"] == "block_next_stage"


def test_handle_inspection_failures_qlip_infeasible_recompile_request() -> None:
    result = handle_inspection_failures(
        _inspection_step("qlip_infeasible", "recompile_request", "recovery_recommended")
    )

    assert result["status"] == "recovery_planned"
    assert result["actions"][0]["action_type"] == "recompile_request"


def test_handle_inspection_failures_no_exportable_structures_fallback_retrieval() -> None:
    result = handle_inspection_failures(
        _inspection_step(
            "no_exportable_structures",
            "fallback_retrieval",
            "recovery_recommended",
        )
    )

    assert result["status"] == "recovery_planned"
    assert result["actions"][0]["action_type"] == "fallback_retrieval"


def test_handle_inspection_failures_spp_blocked_skip_optional_stage() -> None:
    result = handle_inspection_failures(
        _inspection_step("spp_blocked", "skip_optional_stage", "recovery_recommended")
    )

    assert result["status"] == "recovery_planned"
    assert result["actions"][0]["action_type"] == "skip_optional_stage"


def test_handle_inspection_failures_qlip_packaging_invalid_repackage_request() -> None:
    inspection = _inspection_step(
        "pot_root_missing",
        "repackage_qlip_request",
        "recovery_recommended",
    )
    inspection["inspected_steps"][0]["recovery_reason"] = "missing_or_invalid_qlip_packaging_inputs"

    result = handle_inspection_failures(inspection)

    assert result["status"] == "recovery_planned"
    assert result["actions"][0]["action_type"] == "repackage_qlip_request"
    assert result["actions"][0]["recovery_reason"] == "missing_or_invalid_qlip_packaging_inputs"
    assert (
        result["actions"][0]["next_step_hint"]
        == "Rebuild QLIP request from SPP bundle with valid pot_root/guidance params before solving."
    )


def test_handle_inspection_failures_adds_bounded_recovery_plan_for_qlip_error() -> None:
    inspection = _inspection_step(
        "qlip_error",
        "revise_qlip_formulation",
        "recovery_recommended",
    )
    inspection["inspected_steps"][0]["tool_name"] = "qlip.solve"
    inspection["inspected_steps"][0]["next_step_hint"] = "Revise the QLIP formulation before retrying solve."
    inspection["inspected_steps"][0]["recovery_plan"] = {
        "recovery_recommended": True,
        "action": "revise_qlip_formulation",
        "can_auto_retry": False,
        "requires_new_data": False,
        "requires_formulation_change": True,
        "hint": "Revise the QLIP formulation before retrying solve.",
        "evidence_path": "raw_solve.json",
    }

    result = handle_inspection_failures(inspection)

    assert result["status"] == "recovery_planned"
    assert result["actions"][0]["action_type"] == "revise_qlip_formulation"
    assert result["actions"][0]["recovery_plan"]["can_auto_retry"] is False
    assert result["actions"][0]["recovery_plan"]["requires_formulation_change"] is True


def test_failure_handling_is_json_serializable() -> None:
    result = handle_inspection_failures(_inspection_clear())
    assert json.loads(json.dumps(result))["status"] == "no_action_required"


def test_failure_handling_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(failure_handling_module)
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


def test_failure_handling_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
