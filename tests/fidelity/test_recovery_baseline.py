"""Guards for the source-faithful recovery baseline."""

from __future__ import annotations

import importlib.util
import ast
from pathlib import Path

import llm_csp


ABANDONED_EXPORTS = ("Planner", "AgentPlan", "AgentRunState")
ABANDONED_TOOLS = ("search_crystal_db", "run_csp", "validate_candidate", "inspect_run")


def test_abandoned_agentic_package_is_not_installed() -> None:
    assert importlib.util.find_spec("llm_csp.agentic") is None
    for name in ABANDONED_EXPORTS:
        assert not hasattr(llm_csp, name)


def test_abandoned_tools_are_absent_from_active_runtime() -> None:
    package_root = Path(llm_csp.__file__).resolve().parent
    names: set[str] = set()
    string_constants: set[str] = set()
    for path in package_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names.update(
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        string_constants.update(
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    for tool_name in ABANDONED_TOOLS:
        assert tool_name not in names
        assert tool_name not in string_constants


def test_authoritative_source_manifest_is_packaging_neutral() -> None:
    project_root = Path(__file__).resolve().parents[2]
    manifest = project_root / "docs" / "fidelity" / "SOURCE_SYSTEMS.json"
    assert manifest.is_file()
