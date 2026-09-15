from __future__ import annotations

import ast
import inspect
import json
import sys
from copy import deepcopy

from sok_llm_orchestrator.agentic.result_inspection import (
    RESULT_INSPECTION_SCHEMA_VERSION,
    inspect_step_results,
)
import sok_llm_orchestrator.agentic.result_inspection as result_inspection_module


def _noop_clear() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.noop_step_execution.v1",
        "execution_performed": False,
        "status": "completed",
        "step_results": [
            {
                "step_index": 0,
                "tool_name": "crystal.csp_pack",
                "status": "would_execute",
                "result_summary": "noop dry run only",
            }
        ],
        "blocked_reasons": [],
        "warnings": [],
    }


def _noop_blocked() -> dict[str, object]:
    return {
        "schema_version": "agentic_csp.noop_step_execution.v1",
        "execution_performed": False,
        "status": "blocked",
        "step_results": [],
        "blocked_reasons": ["Execution handoff is not ready for a future executor."],
        "warnings": [],
    }


def _synthetic_result(summary: str = "noop dry run only", metadata: dict[str, object] | None = None) -> dict[str, object]:
    result = _noop_clear()
    result["step_results"][0]["result_summary"] = summary
    if metadata is not None:
        result["step_results"][0]["metadata"] = metadata
    return result


def test_inspect_step_results_clear_noop_result_continues() -> None:
    execution = _noop_clear()
    before = deepcopy(execution)

    result = inspect_step_results(execution)

    assert execution == before
    assert result["schema_version"] == RESULT_INSPECTION_SCHEMA_VERSION
    assert result["status"] == "clear"
    assert result["inspected_steps"][0]["tool_name"] == "crystal.csp_pack"
    assert result["inspected_steps"][0]["inspection_status"] == "clear"
    assert result["inspected_steps"][0]["recommended_action"] == "continue"
    assert result["inspected_steps"][0]["detected_issue"] is None


def test_inspect_step_results_blocked_noop_execution_stays_blocked() -> None:
    result = inspect_step_results(_noop_blocked())

    assert result["status"] == "blocked"
    assert result["inspected_steps"] == []
    assert result["blocked_reasons"] == [
        "Execution handoff is not ready for a future executor."
    ]


def test_inspect_step_results_zero_cif_blocks_next_stage() -> None:
    result = inspect_step_results(_synthetic_result(metadata={"cif_count": 0}))

    assert result["status"] == "blocked"
    assert result["inspected_steps"][0]["inspection_status"] == "blocked"
    assert result["inspected_steps"][0]["detected_issue"] == "zero_cifs"
    assert result["inspected_steps"][0]["recommended_action"] == "block_next_stage"


def test_inspect_step_results_qlip_infeasible_recommends_recompile() -> None:
    result = inspect_step_results(_synthetic_result(metadata={"qlip_infeasible": True}))

    assert result["status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["inspection_status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["detected_issue"] == "qlip_infeasible"
    assert result["inspected_steps"][0]["recommended_action"] == "recompile_request"


def test_inspect_step_results_no_exportable_structures_recommends_fallback() -> None:
    result = inspect_step_results(
        _synthetic_result(metadata={"no_exportable_structures": True})
    )

    assert result["status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["inspection_status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["detected_issue"] == "no_exportable_structures"
    assert result["inspected_steps"][0]["recommended_action"] == "fallback_retrieval"


def test_inspect_step_results_spp_blocked_recommends_skip_optional_stage() -> None:
    result = inspect_step_results(_synthetic_result(metadata={"spp_blocked": True}))

    assert result["status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["inspection_status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["detected_issue"] == "spp_blocked"
    assert result["inspected_steps"][0]["recommended_action"] == "skip_optional_stage"


def test_inspect_step_results_invalid_qlip_validation_recommends_repackage() -> None:
    execution = {
        "schema_version": "agentic_csp.execution_run.v1",
        "status": "partial",
        "step_results": [
            {
                "step_index": 0,
                "tool_name": "qlip.validate_request",
                "status": "succeeded",
                "output_summary": {
                    "valid": False,
                    "validation_errors": [
                        {
                            "code": "pot_root_missing",
                            "message": "missing potential root",
                            "path": "/context/pot_root",
                        },
                        {
                            "code": "invalid_guidance_params",
                            "message": "unexpected params",
                            "path": "/guidance/0/params",
                        },
                    ],
                },
            }
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    result = inspect_step_results(execution)

    assert result["status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["inspection_status"] == "recovery_recommended"
    assert result["inspected_steps"][0]["detected_issue"] == "pot_root_missing"
    assert result["inspected_steps"][0]["recommended_action"] == "repackage_qlip_request"
    assert result["inspected_steps"][0]["recovery_reason"] == "missing_or_invalid_qlip_packaging_inputs"


def test_unresolved_request_ref_after_incompatible_spp_becomes_spp_request_ref_unavailable() -> None:
    execution = {
        "schema_version": "agentic_csp.execution_run.v1",
        "status": "partial",
        "step_results": [
            {
                "step_index": 0,
                "tool_name": "spp.run_pipeline",
                "status": "succeeded",
                "raw_result_ref": "raw_spp.json",
                "output_summary": {
                    "request_ref": None,
                    "qlip_package_status": "partial",
                    "qlip_solve_compatible": False,
                    "qlip_package_missing_pairs": ["A-A", "A-B"],
                },
            },
            {
                "step_index": 1,
                "tool_name": "qlip.validate_request",
                "status": "blocked",
                "error": {
                    "code": "unresolved_placeholder_ref",
                    "message": "Unresolved proposal-time refs remain: request_ref",
                },
            },
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    result = inspect_step_results(execution)

    step = result["inspected_steps"][1]
    assert step["detected_issue"] == "spp_request_ref_unavailable"
    assert step["recovery_reason"] == "spp_no_request_ref"
    assert step["recommended_action"] == "repair_spp_qlip_package"
    assert "A-A" in step["next_step_hint"]
    assert step["recovery_plan"]["requires_new_data"] is True


def test_qlip_solve_non_solution_infeasible_classifies_qlip_infeasible() -> None:
    execution = {
        "schema_version": "agentic_csp.execution_run.v1",
        "status": "partial",
        "step_results": [
            {
                "step_index": 0,
                "tool_name": "qlip.solve",
                "status": "failed",
                "raw_result_ref": "raw_solve.json",
                "raw_result_summary": {"status": "INFEASIBLE"},
                "error": {"code": "non_solution_status", "message": "qlip.solve returned status=INFEASIBLE"},
            }
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    result = inspect_step_results(execution)

    step = result["inspected_steps"][0]
    assert step["detected_issue"] == "qlip_infeasible"
    assert step["recommended_action"] == "revise_qlip_formulation"
    assert step["recovery_plan"]["requires_formulation_change"] is True


def test_qlip_solve_non_solution_error_classifies_qlip_error() -> None:
    execution = {
        "schema_version": "agentic_csp.execution_run.v1",
        "status": "partial",
        "step_results": [
            {
                "step_index": 0,
                "tool_name": "qlip.solve",
                "status": "failed",
                "raw_result_ref": "raw_solve.json",
                "raw_result_summary": {"status": "ERROR"},
                "error": {"code": "non_solution_status", "message": "qlip.solve returned status=ERROR"},
            }
        ],
        "blocked_reasons": [],
        "warnings": [],
    }

    result = inspect_step_results(execution)

    step = result["inspected_steps"][0]
    assert step["detected_issue"] == "qlip_error"
    assert step["recommended_action"] == "revise_qlip_formulation"


def test_result_inspection_is_json_serializable() -> None:
    result = inspect_step_results(_noop_clear())
    assert json.loads(json.dumps(result))["status"] == "clear"


def test_result_inspection_has_no_sqlite_or_pipeline_dependency() -> None:
    source = inspect.getsource(result_inspection_module)
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


def test_result_inspection_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    assert "sok_llm_orchestrator.pipeline" not in sys.modules
