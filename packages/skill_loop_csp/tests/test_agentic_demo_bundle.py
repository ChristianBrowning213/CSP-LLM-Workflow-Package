from __future__ import annotations

import ast
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.demo_bundle import write_demo_showcase_bundle


@contextmanager
def _local_test_dir(name: str):
    root = Path.cwd() / "test_workdir" / "agentic_demo_bundle_tests"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_demo_bundle_writer_creates_layout_and_zip() -> None:
    with _local_test_dir("bundle") as root:
        source = root / "source"
        source.mkdir()
        planner_trace_json = source / "agentic_llm_trace_planner.json"
        report_json = source / "execution_loop_report.json"
        report_md = source / "execution_loop_report.md"
        workflow_eval_json = source / "workflow_evaluation.json"
        workflow_eval_md = source / "workflow_evaluation.md"
        trace_md = source / "llm_and_tool_trace.md"
        execution_run_json = source / "execution_run.json"
        execution_step_log_jsonl = source / "execution_step_log.jsonl"
        generated_cif = source / "solution.cif"

        _write_json(
            planner_trace_json,
            {
                "schema_version": "agentic.trace.v1",
                "messages": [],
                "raw_output": {"content": "{}"},
                "parsed_output": {"schema_version": "agentic_csp.run_plan.v1"},
            },
        )
        report_md.write_text("# Agentic Execution Loop Report\n", encoding="utf-8")
        workflow_eval_md.write_text("# Workflow Evaluation Report\n", encoding="utf-8")
        _write_json(workflow_eval_json, {"schema_version": "agentic_csp.workflow_evaluation.v1"})
        trace_md.write_text("# Agentic LLM + Tool Trace\n", encoding="utf-8")
        generated_cif.write_text("data_demo\n", encoding="utf-8")
        _write_json(
            report_json,
            {
                "schema_version": "agentic_csp.execution_loop_report.v1",
                "llm_planner_reply": {
                    "trace_json_path": str(planner_trace_json),
                    "trace_markdown_path": "",
                },
                "artifact_index": [
                    {"label": "LLM trace JSON", "path": str(planner_trace_json)},
                    {"label": "qlip.solve solution_cif_path", "path": str(generated_cif)},
                ],
            },
        )
        _write_json(execution_run_json, {"schema_version": "agentic_csp.execution_run.v1"})
        execution_step_log_jsonl.write_text("{}", encoding="utf-8")

        result = write_demo_showcase_bundle(
            {
                "plan_source": "deterministic_showcase",
                "material_system": "CoAs2",
                "mcp_backend": "fake",
                "crystal_export_mode": "safe",
                "crystal_demo_export_enabled": False,
                "artifact_paths": {
                    "planner_trace_json": str(planner_trace_json),
                    "execution_loop_report_json": str(report_json),
                    "execution_loop_report_md": str(report_md),
                    "workflow_evaluation_json": str(workflow_eval_json),
                    "workflow_evaluation_md": str(workflow_eval_md),
                    "llm_and_tool_trace_md": str(trace_md),
                    "execution_run_json": str(execution_run_json),
                    "execution_step_log_jsonl": str(execution_step_log_jsonl),
                }
            },
            root / "bundle",
            zip_bundle=True,
        )

        bundle_root = Path(result["bundle_root"])
        assert result["schema_version"] == "agentic_csp.demo_showcase_bundle.v1"
        assert (bundle_root / "README.md").exists()
        assert (bundle_root / "bundle_manifest.json").exists()
        assert (bundle_root / "report" / "execution_loop_report.md").exists()
        assert (bundle_root / "report" / "execution_loop_report.json").exists()
        assert (bundle_root / "report" / "workflow_evaluation.md").exists()
        assert (bundle_root / "report" / "workflow_evaluation.json").exists()
        assert (bundle_root / "report" / "llm_and_tool_trace.md").exists()
        assert (bundle_root / "llm" / "agentic_llm_trace_planner.json").exists()
        assert (bundle_root / "llm" / "agentic_llm_trace_planner.md").exists()
        assert (bundle_root / "execution" / "execution_run.json").exists()
        assert (bundle_root / "execution" / "execution_step_log.jsonl").exists()
        assert (bundle_root / "artifacts" / "artifact_index.json").exists()
        assert result["zip_path"] is not None
        assert Path(result["zip_path"]).exists()

        artifact_index = json.loads((bundle_root / "artifacts" / "artifact_index.json").read_text(encoding="utf-8"))
        manifest = json.loads((bundle_root / "bundle_manifest.json").read_text(encoding="utf-8"))
        assert artifact_index == [{"label": "qlip.solve solution_cif_path", "path": str(generated_cif)}]
        assert result["artifact_count"] == 1
        assert manifest["plan_source"] == "deterministic_showcase"
        assert manifest["material_system"] == "CoAs2"
        assert manifest["mcp_backend"] == "fake"
        assert manifest["crystal_export_mode"] == "safe"
        assert manifest["crystal_demo_export_enabled"] is False
        assert manifest["zip_created"] is True
        assert manifest["report_markdown_path"].endswith("report\\workflow_evaluation.md")
        assert manifest["execution_loop_report_markdown_path"].endswith("report\\execution_loop_report.md")
        assert manifest["workflow_evaluation_markdown_path"].endswith("report\\workflow_evaluation.md")
        assert "report/workflow_evaluation.md" in (bundle_root / "README.md").read_text(encoding="utf-8")
        assert manifest["execution_run_path"].endswith("execution\\execution_run.json")
        assert manifest["execution_step_log_path"].endswith("execution\\execution_step_log.jsonl")


def test_demo_bundle_has_no_pipeline_or_sqlite_dependency() -> None:
    module_path = Path("src/sok_llm_orchestrator/agentic/demo_bundle.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    assert all("sqlite" not in name for name in imports)
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in imports
