from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict
from .trace_render import render_agentic_llm_trace_markdown

DEMO_SHOWCASE_BUNDLE_SCHEMA_VERSION = "agentic_csp.demo_showcase_bundle.v1"

_CANONICAL_ARTIFACT_LABELS = {
    "LLM trace JSON",
    "LLM trace Markdown",
    "Tool parse report JSON",
    "Executable plan JSON",
    "Executable plan report JSON",
    "Execution run JSON",
    "Execution step log JSONL",
    "Execution loop report JSON",
    "Execution loop report Markdown",
    "Workflow evaluation JSON",
    "Workflow evaluation Markdown",
    "LLM + tool trace Markdown",
}


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str):
        return value
    return default


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _copy_if_exists(source: str | Path | None, target: Path, warnings: list[str]) -> str | None:
    if source is None:
        return None
    src_path = Path(source)
    if not src_path.exists():
        warnings.append(f"Missing bundle source artifact: {src_path}")
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, target)
    return str(target)


def _load_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return to_json_dict(payload) if isinstance(payload, Mapping) else {}


def _planner_trace_markdown(
    planner_trace_json_path: str | None,
    planner_trace_markdown_path: str | None,
    target_path: Path,
    warnings: list[str],
) -> str | None:
    if planner_trace_markdown_path:
        copied = _copy_if_exists(planner_trace_markdown_path, target_path, warnings)
        if copied:
            return copied
    if not planner_trace_json_path:
        warnings.append("Planner trace JSON was not available for Markdown rendering.")
        return None
    json_path = Path(planner_trace_json_path)
    if not json_path.exists():
        warnings.append(f"Planner trace JSON path does not exist: {json_path}")
        return None
    payload = _load_json(json_path)
    _write_text(target_path, render_agentic_llm_trace_markdown(payload, "planner"))
    return str(target_path)


def _artifact_index_from_report(report_payload: Mapping[str, Any]) -> list[dict[str, str]]:
    artifact_index = _mapping_list(report_payload, "artifact_index")
    filtered: list[dict[str, str]] = []
    for item in artifact_index:
        label = _safe_string(item, "label")
        path = _safe_string(item, "path")
        if not label or not path or label in _CANONICAL_ARTIFACT_LABELS:
            continue
        filtered.append({"label": label, "path": path})
    return filtered


def _readme_text(bundle_manifest_path: Path, workflow_report_path: Path, execution_report_path: Path) -> str:
    return "\n".join(
        [
            "# Agentic Demo Showcase Bundle",
            "",
            "Open the main presentation artifact first:",
            f"- `{workflow_report_path.as_posix()}`",
            "",
            "Trace appendix:",
            f"- `{execution_report_path.as_posix()}`",
            "",
            "Bundle manifest:",
            f"- `{bundle_manifest_path.as_posix()}`",
            "",
            "This bundle demonstrates the live planner -> parsed tools -> executable plan -> gated executor route.",
            "No old hardcoded pipeline control loop is used.",
            "",
        ]
    )


def write_demo_showcase_bundle(
    demo_result: Mapping[str, Any],
    out_dir: str | Path,
    *,
    zip_bundle: bool = False,
) -> dict[str, Any]:
    demo_dict = to_json_dict(demo_result)
    artifact_paths = (
        to_json_dict(demo_dict.get("artifact_paths", {}))
        if isinstance(demo_dict.get("artifact_paths"), Mapping)
        else {}
    )

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    report_dir = root / "report"
    llm_dir = root / "llm"
    execution_dir = root / "execution"
    artifacts_dir = root / "artifacts"
    for path in (report_dir, llm_dir, execution_dir, artifacts_dir):
        path.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    plan_source = _safe_string(demo_dict, "plan_source")
    material_system = _safe_string(demo_dict, "material_system")
    mcp_backend = _safe_string(demo_dict, "mcp_backend")
    crystal_export_mode = _safe_string(demo_dict, "crystal_export_mode", "safe")
    crystal_demo_export_enabled = bool(demo_dict.get("crystal_demo_export_enabled"))
    report_json_source = artifact_paths.get("execution_loop_report_json")
    report_md_source = artifact_paths.get("execution_loop_report_md") or demo_dict.get("report_markdown_path")
    workflow_eval_json_source = artifact_paths.get("workflow_evaluation_json") or demo_dict.get("workflow_evaluation_json_path")
    workflow_eval_md_source = artifact_paths.get("workflow_evaluation_md") or demo_dict.get("workflow_evaluation_markdown_path")
    llm_tool_trace_source = artifact_paths.get("llm_and_tool_trace_md")
    planner_trace_json_source = artifact_paths.get("planner_trace_json")
    execution_run_source = artifact_paths.get("execution_run_json") or demo_dict.get("execution_run_path")
    step_log_source = artifact_paths.get("execution_step_log_jsonl") or demo_dict.get("step_log_path")

    report_json_path = _copy_if_exists(report_json_source, report_dir / "execution_loop_report.json", warnings)
    report_markdown_path = _copy_if_exists(report_md_source, report_dir / "execution_loop_report.md", warnings)
    workflow_eval_json_path = _copy_if_exists(workflow_eval_json_source, report_dir / "workflow_evaluation.json", warnings)
    workflow_eval_markdown_path = _copy_if_exists(workflow_eval_md_source, report_dir / "workflow_evaluation.md", warnings)
    llm_tool_trace_path = _copy_if_exists(llm_tool_trace_source, report_dir / "llm_and_tool_trace.md", warnings)
    planner_trace_json_path = _copy_if_exists(planner_trace_json_source, llm_dir / "agentic_llm_trace_planner.json", warnings)

    planner_trace_markdown_source: str | None = None
    report_payload: dict[str, Any] = {}
    if report_json_source and Path(report_json_source).exists():
        report_payload = _load_json(report_json_source)
        planner_reply = (
            to_json_dict(report_payload.get("llm_planner_reply", {}))
            if isinstance(report_payload.get("llm_planner_reply"), Mapping)
            else {}
        )
        planner_trace_markdown_source = _safe_string(planner_reply, "trace_markdown_path") or None

    planner_trace_markdown_path = _planner_trace_markdown(
        planner_trace_json_source if isinstance(planner_trace_json_source, str) else None,
        planner_trace_markdown_source,
        llm_dir / "agentic_llm_trace_planner.md",
        warnings,
    )
    execution_run_path = _copy_if_exists(execution_run_source, execution_dir / "execution_run.json", warnings)
    step_log_path = _copy_if_exists(step_log_source, execution_dir / "execution_step_log.jsonl", warnings)

    artifact_index = _artifact_index_from_report(report_payload)
    artifact_index_path = artifacts_dir / "artifact_index.json"
    _write_json(artifact_index_path, artifact_index)

    manifest_path = root / "bundle_manifest.json"
    readme_path = root / "README.md"

    manifest = {
        "schema_version": DEMO_SHOWCASE_BUNDLE_SCHEMA_VERSION,
        "bundle_root": str(root),
        "plan_source": plan_source,
        "material_system": material_system,
        "mcp_backend": mcp_backend,
        "crystal_export_mode": crystal_export_mode,
        "crystal_demo_export_enabled": crystal_demo_export_enabled,
        "zip_created": bool(zip_bundle),
        "report_markdown_path": str(report_dir / "workflow_evaluation.md"),
        "workflow_evaluation_markdown_path": workflow_eval_markdown_path,
        "workflow_evaluation_json_path": workflow_eval_json_path,
        "execution_loop_report_markdown_path": str(report_dir / "execution_loop_report.md"),
        "report_json_path": str(report_dir / "execution_loop_report.json"),
        "llm_and_tool_trace_markdown_path": str(report_dir / "llm_and_tool_trace.md"),
        "planner_trace_json_path": planner_trace_json_path,
        "planner_trace_markdown_path": planner_trace_markdown_path,
        "execution_run_path": execution_run_path,
        "execution_step_log_path": step_log_path,
        "execution_run_json_path": execution_run_path,
        "execution_step_log_jsonl_path": step_log_path,
        "artifact_index_json_path": str(artifact_index_path),
        "artifact_count": len(artifact_index),
        "warnings": warnings,
    }
    _write_json(manifest_path, manifest)
    _write_text(
        readme_path,
        _readme_text(
            manifest_path.relative_to(root),
            (report_dir / "workflow_evaluation.md").relative_to(root),
            (report_dir / "execution_loop_report.md").relative_to(root),
        ),
    )

    zip_path: str | None = None
    if zip_bundle:
        archive_base = root / "demo_showcase_bundle"
        zip_path = shutil.make_archive(str(archive_base), "zip", root_dir=root)

    result = {
        "schema_version": DEMO_SHOWCASE_BUNDLE_SCHEMA_VERSION,
        "bundle_root": str(root),
        "readme_path": str(readme_path),
        "report_markdown_path": str(report_dir / "workflow_evaluation.md"),
        "manifest_path": str(manifest_path),
        "zip_path": zip_path,
        "artifact_count": len(artifact_index),
        "warnings": warnings,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "DEMO_SHOWCASE_BUNDLE_SCHEMA_VERSION",
    "write_demo_showcase_bundle",
]
