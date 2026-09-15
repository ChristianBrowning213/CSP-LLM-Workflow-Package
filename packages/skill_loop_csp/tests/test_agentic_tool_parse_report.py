from __future__ import annotations

import ast
import inspect
import json
import sys

from sok_llm_orchestrator.agentic.plan_compile import (
    TOOL_PARSE_REPORT_SCHEMA_VERSION,
    build_tool_parse_report,
)
import sok_llm_orchestrator.agentic.plan_compile as plan_compile_module


def test_build_tool_parse_report_counts_and_preserves_tool_order() -> None:
    compile_result = {
        "schema_version": "agentic_csp.plan_compile.v1",
        "proposals": [
            {"tool_name": "crystal.csp_pack"},
            {"tool_name": "spp.run_pipeline"},
            {"tool_name": "qlip.solve"},
        ],
        "validation_results": [
            {"tool_name": "crystal.csp_pack", "valid": True},
            {"tool_name": "spp.run_pipeline", "valid": True},
            {"tool_name": "qlip.solve", "valid": False},
        ],
        "warnings": ["pending refs present"],
    }

    result = build_tool_parse_report(compile_result, route_mode="live_ab_parse")

    assert result == {
        "schema_version": TOOL_PARSE_REPORT_SCHEMA_VERSION,
        "proposal_count": 3,
        "valid_count": 2,
        "invalid_count": 1,
        "tool_sequence": [
            "crystal.csp_pack",
            "spp.run_pipeline",
            "qlip.solve",
        ],
        "warnings": ["pending refs present"],
        "route_mode": "live_ab_parse",
    }


def test_build_tool_parse_report_is_json_serializable() -> None:
    result = build_tool_parse_report(
        {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": [],
            "validation_results": [],
            "warnings": [],
        }
    )

    assert json.loads(json.dumps(result))["schema_version"] == TOOL_PARSE_REPORT_SCHEMA_VERSION


def test_tool_parse_report_has_no_sqlite_or_pipeline_dependency() -> None:
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


def test_tool_parse_report_does_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = build_tool_parse_report(
        {
            "schema_version": "agentic_csp.plan_compile.v1",
            "proposals": [],
            "validation_results": [],
            "warnings": [],
        }
    )
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
