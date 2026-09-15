from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.llm.client import LLMClient

from .demo_bundle import write_demo_showcase_bundle
from .execution_plan_adapter import (
    build_executable_plan_from_compile_result,
    build_executable_plan_report,
)
from .execution_report import (
    build_execution_loop_report,
    write_execution_loop_report,
)
from .evaluator import build_workflow_evaluation, write_workflow_evaluation
from .failure_handling import handle_inspection_failures
from .gated_executor import execute_executable_plan
from .llm_runtime import AgentLLMRuntime
from .partial_success import build_continuation_summary, build_partial_success_evaluation
from .plan_compile import build_tool_parse_report, compile_run_plan_to_tool_proposals
from .planner_runtime import run_live_planner_and_compile
from .qlip_recovery import build_corrected_qlip_request_from_spp
from .result_inspection import inspect_step_results
from .schemas import assert_json_serializable, to_json_dict
from .tool_execution_adapters import get_default_tool_execution_adapters
from .trace_render import render_agentic_llm_trace_markdown

DEMO_EXECUTION_LOOP_SCHEMA_VERSION = "agentic_csp.demo_execution_loop.v1"
SHOWCASE_DEFAULT_GOAL = (
    "Find and evaluate candidate structures for CoAs2 using retrieved structural analogues, "
    "SPP packaging, QLIP validation/solve, and novelty checking."
)
DEFAULT_DEMO_ALLOWED_TOOLS = [
    "crystal.csp_pack",
    "crystal.novelty_check",
    "spp.run_pipeline",
    "qlip.validate_request",
    "qlip.solve",
]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_json_dict(payload), sort_keys=True) + "\n")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return to_json_dict(payload) if isinstance(payload, Mapping) else None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if isinstance(payload, Mapping):
            rows.append(to_json_dict(payload))
    return rows


def _string_list(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_demo_config_path() -> Path | None:
    candidate = _repo_root() / "my_live_config.yaml"
    if candidate.exists():
        return candidate
    return None


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _latest_step_result(execution_run: Mapping[str, Any], tool_name: str) -> dict[str, Any] | None:
    for step in reversed(_mapping_list(execution_run, "step_results")):
        if _safe_string(step, "tool_name") == tool_name:
            return step
    return None


def _artifact_ref_map(step_result: Mapping[str, Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for item in _mapping_list(step_result, "artifact_refs"):
        ref_name = _safe_string(item, "ref_name")
        ref_value = _safe_string(item, "value")
        if ref_name and ref_value:
            refs[ref_name] = ref_value
    return refs


def _copy_if_exists(source: str | None, destination: Path) -> str | None:
    if not isinstance(source, str) or not source.strip():
        return None
    source_path = Path(source)
    if not source_path.exists():
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source_path.read_bytes())
    return str(destination)


def _recovery_log_row(
    *,
    stage: str,
    step_result: Mapping[str, Any],
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "stage": stage,
        "tool_name": _safe_string(step_result, "tool_name"),
        "arguments": to_json_dict(arguments),
        "execution_performed": bool(step_result.get("execution_performed")),
        "status": _safe_string(step_result, "status"),
        "output_summary": to_json_dict(step_result.get("output_summary", {}))
        if isinstance(step_result.get("output_summary"), Mapping)
        else {},
        "artifact_refs": _mapping_list(step_result, "artifact_refs"),
        "error": to_json_dict(step_result.get("error"))
        if isinstance(step_result.get("error"), Mapping)
        else None,
    }
    return None


def build_showcase_six_tool_run_plan(
    *,
    goal: str = SHOWCASE_DEFAULT_GOAL,
    run_id: str = "showcase_run_001",
    material_system: str = "CoAs2",
    crystal_export_mode: str = "safe",
    crystal_demo_export_enabled: bool = False,
) -> dict[str, Any]:
    run_plan = {
        "schema_version": "agentic_csp.run_plan.v1",
        "run_id": run_id,
        "overall_goal": goal,
        "run_goal": (
            f"Demonstrate the full six-tool CSP showcase path for {material_system} from retrieval "
            f"through novelty review using a deterministic presentation-stable plan."
        ),
        "stage": "wide_exploration",
        "detailed_description": (
            f"This deterministic showcase plan is designed for a stable demo of the parsed executable "
            f"tool route for {material_system}. It was not generated by the live planner. The plan deliberately "
            f"uses unified SPP output so the showcase can demonstrate retrieval, SPP packaging, QLIP "
            f"validation/solve, and novelty review through the same parser and gated executor path."
        ),
        "hoping_to_find": (
            f"A complete, inspectable demo loop for {material_system} that produces candidate structures, "
            f"downstream packaging artifacts, a QLIP request/solution path, and a novelty result when available."
        ),
        "plan_as_text": "\n".join(
            [
                f"1. Retrieve candidate analogue structures for {material_system}.",
                "tool_hint: crystal.csp_pack",
                "2. Prepare the retrieved candidates for SPP scoring and emit the QLIP package.",
                "tool_hint: spp.run_pipeline",
                "3. Validate the SPP-emitted QLIP request before solving.",
                "tool_hint: qlip.validate_request",
                "4. Solve the validated QLIP request to obtain a candidate structure.",
                "tool_hint: qlip.solve",
                "5. Check the solved candidate for novelty against known structures.",
                "tool_hint: crystal.novelty_check",
            ]
        ),
        "what_we_tried_previously_that_is_related": (
            "This is a deterministic showcase mode for presentation, not a live planner hypothesis."
        ),
        "success_criteria": [
            "All five tool_hint lines are parsed and compiled into a valid executable plan.",
            "The demo report clearly distinguishes deterministic showcase mode from live LLM planning.",
            "Execution captures real outputs or truthful blocked/failure states with no pipeline shortcut.",
        ],
        "stop_conditions_for_this_run": [
            "Stop if a tool adapter fails or blocks and the gated executor decides not to continue.",
        ],
        "metadata": {
            "plan_source": "deterministic_showcase",
            "material_system": material_system,
            "live_llm_used": False,
            "deterministic_showcase": True,
            "crystal_export_mode": crystal_export_mode,
            "crystal_demo_export_enabled": crystal_demo_export_enabled,
            "warning": "This RunPlan was constructed deterministically for presentation and was not generated by a live LLM planner.",
        },
    }
    assert_json_serializable(run_plan)
    return run_plan


def _build_planner_compile_run_from_run_plan(
    run_plan: Mapping[str, Any],
    *,
    plan_source: str,
    material_system: str,
    mcp_backend: str,
    crystal_export_mode: str,
    crystal_demo_export_enabled: bool,
) -> dict[str, Any]:
    run_plan_dict = to_json_dict(run_plan)
    compile_result = compile_run_plan_to_tool_proposals(run_plan_dict)
    result = {
        "schema_version": "agentic_csp.planner_compile_run.v1",
        "run_id": str(run_plan_dict.get("run_id", "")),
        "run_plan": run_plan_dict,
        "compile_result": compile_result,
        "proposal_count": len(compile_result["proposals"]),
        "valid_proposal_count": sum(
            1 for item in compile_result["validation_results"] if item["valid"] is True
        ),
        "invalid_proposal_count": sum(
            1 for item in compile_result["validation_results"] if item["valid"] is False
        ),
        "warnings": list(compile_result["warnings"]),
        "plan_source": plan_source,
        "material_system": material_system,
        "mcp_backend": mcp_backend,
        "live_llm_used": plan_source == "live_llm",
        "crystal_export_mode": crystal_export_mode,
        "crystal_demo_export_enabled": crystal_demo_export_enabled,
    }
    assert_json_serializable(result)
    return result


def build_demo_mcp_settings(
    out_dir: str | Path,
    backend: str,
    *,
    config_path: str | Path | None = None,
    allow_crystal_demo_export: bool = False,
) -> Settings:
    workdir = Path(out_dir)
    resolved_config_path: Path | None
    if config_path is None:
        resolved_config_path = _default_demo_config_path() if backend == "configured" else None
    else:
        resolved_config_path = Path(config_path).resolve()
    base = Settings.from_sources(resolved_config_path)
    base.workspace_root = workdir
    if backend == "configured":
        if allow_crystal_demo_export:
            base.crystaldb_policy_mode = "demo"
        return base
    if backend != "fake":
        msg = f"Unsupported MCP backend: {backend}"
        raise ValueError(msg)
    root = _repo_root()
    base.crystaldb_mcp_cmd = [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")]
    base.spp_mcp_cmd = [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_spp_server.py")]
    base.qlip_mcp_cmd = [sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_qlip_server.py")]
    base.crystaldb_mcp_cwd = str(root)
    base.spp_mcp_cwd = str(root)
    base.qlip_mcp_cwd = str(root)
    base.crystaldb_policy_mode = "demo"
    base.max_runtime_seconds = 30
    return base


def build_demo_runtime_from_settings(settings: Settings) -> AgentLLMRuntime:
    settings.validate_llm()
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model or "",
        timeout_s=settings.llm_timeout_s,
        max_retries=1,
    )
    return AgentLLMRuntime(client=client, max_attempts=2)


def _ensure_planner_trace_markdown(
    planner_trace_json_path: str | None,
    planner_trace: Mapping[str, Any] | None,
) -> str | None:
    if not planner_trace_json_path or not isinstance(planner_trace, Mapping):
        return None
    trace_json_path = Path(planner_trace_json_path)
    trace_md_path = trace_json_path.with_suffix(".md")
    if not trace_md_path.exists():
        _write_text(trace_md_path, render_agentic_llm_trace_markdown(planner_trace, "planner"))
    return str(trace_md_path)


def _maybe_attempt_qlip_recovery(
    *,
    root: Path,
    execution_run: Mapping[str, Any],
    failure_handling: Mapping[str, Any],
    adapters: Mapping[str, Any],
) -> dict[str, Any] | None:
    actions = _mapping_list(failure_handling, "actions")
    if not any(_safe_string(action, "action_type") == "repackage_qlip_request" for action in actions):
        return None

    package_step = _latest_step_result(execution_run, "spp.package_for_qlip") or _latest_step_result(execution_run, "spp.run_pipeline")
    validate_step = _latest_step_result(execution_run, "qlip.validate_request")
    solve_step = _latest_step_result(execution_run, "qlip.solve")
    spp_step = _latest_step_result(execution_run, "spp.run_pipeline")
    if not all(isinstance(item, Mapping) for item in (package_step, validate_step, solve_step, spp_step)):
        return None
    if not (
        isinstance(validate_step, Mapping)
        and isinstance(validate_step.get("output_summary"), Mapping)
        and validate_step["output_summary"].get("valid") is False
    ):
        return None
    if not (
        isinstance(solve_step, Mapping)
        and _safe_string(solve_step, "status") == "blocked"
        and _safe_string(solve_step.get("error", {}), "code") == "qlip_request_invalid"
    ):
        return None

    package_refs = _artifact_ref_map(package_step)
    request_ref = package_refs.get("request_ref") or _safe_string(validate_step.get("arguments", {}), "request_ref")
    if not request_ref:
        return None
    request_path = Path(request_ref)
    if not request_path.exists():
        return None

    recovery_root = root / "execution" / "recovery_qlip_repackage"
    recovery_root.mkdir(parents=True, exist_ok=True)
    recovery_log_path = recovery_root / "recovery_step_log.jsonl"
    if recovery_log_path.exists():
        recovery_log_path.unlink()
    recovery_log_path.write_text("", encoding="utf-8")

    invalid_request = json.loads(request_path.read_text(encoding="utf-8"))
    correction = build_corrected_qlip_request_from_spp(
        invalid_request=invalid_request,
        spp_step_result=spp_step,
        package_step_result=package_step,
        out_dir=recovery_root,
    )

    original_validation_errors = (
        [
            to_json_dict(item)
            for item in validate_step.get("output_summary", {}).get("validation_errors", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(validate_step.get("output_summary"), Mapping)
        and isinstance(validate_step.get("output_summary", {}).get("validation_errors"), list)
        else []
    )
    recovery_attempt: dict[str, Any] = {
        "schema_version": "agentic_csp.qlip_recovery_attempt.v1",
        "action": "repackage_qlip_request",
        "status": correction["status"],
        "original_validation_errors": original_validation_errors,
        "corrected_request_path": correction.get("corrected_request_path"),
        "pot_root": correction.get("pot_root"),
        "removed_guidance_params": list(correction.get("removed_guidance_params", []))
        if isinstance(correction.get("removed_guidance_params"), list)
        else [],
        "warnings": list(correction.get("warnings", []))
        if isinstance(correction.get("warnings"), list)
        else [],
        "blocked_reason": correction.get("blocked_reason"),
        "retry_validation": {
            "attempted": False,
            "status": "not_attempted",
            "valid": None,
            "validation_errors": [],
            "validated_request_ref": None,
            "raw_validation_response_ref": None,
        },
        "solve": {
            "attempted": False,
            "status": "not_attempted",
            "solution_cif_path": None,
            "raw_solve_response_ref": None,
            "error": None,
        },
        "novelty": {
            "attempted": False,
            "status": "not_attempted",
            "is_novel": None,
            "raw_novelty_response_ref": None,
            "error": None,
        },
        "recovery_step_log_path": str(recovery_log_path),
        "final_status": "blocked" if correction.get("status") != "corrected" else "retry_pending",
    }

    if correction.get("status") != "corrected":
        assert_json_serializable(recovery_attempt)
        return recovery_attempt

    case_id = _safe_string(package_step.get("arguments", {}), "case_id", "run_001")
    validate_args = {
        "case_id": case_id,
        "request_ref": str(correction["corrected_request_path"]),
    }
    retry_validate_result = to_json_dict(
        adapters["qlip.validate_request"](
            {"step_index": 0, "tool_name": "qlip.validate_request"},
            arguments=validate_args,
            prior_step_results=_mapping_list(execution_run, "step_results"),
            step_dir=recovery_root / "retry_validate_request",
        )
    )
    _append_jsonl(
        recovery_log_path,
        _recovery_log_row(stage="retry_validate_request", step_result=retry_validate_result, arguments=validate_args),
    )
    retry_validation_ref = _copy_if_exists(
        _safe_string(retry_validate_result, "raw_result_ref"),
        recovery_root / "retry_raw_validation_response.json",
    )
    validated_request_ref = _artifact_ref_map(retry_validate_result).get("validated_request_ref")
    copied_validated_request_ref = _copy_if_exists(
        validated_request_ref,
        recovery_root / "retry_validated_request.json",
    ) or validated_request_ref
    retry_validation_errors = (
        [
            to_json_dict(item)
            for item in retry_validate_result.get("output_summary", {}).get("validation_errors", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(retry_validate_result.get("output_summary"), Mapping)
        and isinstance(retry_validate_result.get("output_summary", {}).get("validation_errors"), list)
        else []
    )
    retry_valid = (
        retry_validate_result.get("output_summary", {}).get("valid")
        if isinstance(retry_validate_result.get("output_summary"), Mapping)
        else None
    )
    recovery_attempt["retry_validation"] = {
        "attempted": True,
        "status": _safe_string(retry_validate_result, "status"),
        "valid": retry_valid,
        "validation_errors": retry_validation_errors,
        "validated_request_ref": copied_validated_request_ref,
        "raw_validation_response_ref": retry_validation_ref,
    }

    if retry_valid is not True:
        recovery_attempt["final_status"] = "retry_invalid"
        recovery_attempt["status"] = "retry_invalid"
        assert_json_serializable(recovery_attempt)
        return recovery_attempt

    solve_args = {
        "case_id": case_id,
        "validated_request_ref": copied_validated_request_ref,
    }
    retry_solve_result = to_json_dict(
        adapters["qlip.solve"](
            {"step_index": 1, "tool_name": "qlip.solve"},
            arguments=solve_args,
            prior_step_results=_mapping_list(execution_run, "step_results") + [retry_validate_result],
            step_dir=recovery_root / "retry_solve",
        )
    )
    _append_jsonl(
        recovery_log_path,
        _recovery_log_row(stage="retry_solve", step_result=retry_solve_result, arguments=solve_args),
    )
    retry_solve_ref = _copy_if_exists(
        _safe_string(retry_solve_result, "raw_result_ref"),
        recovery_root / "retry_raw_solve_response.json",
    )
    recovery_attempt["solve"] = {
        "attempted": True,
        "status": _safe_string(retry_solve_result, "status"),
        "solution_cif_path": _artifact_ref_map(retry_solve_result).get("solution_cif_path"),
        "raw_solve_response_ref": retry_solve_ref,
        "error": to_json_dict(retry_solve_result.get("error"))
        if isinstance(retry_solve_result.get("error"), Mapping)
        else None,
    }
    if _safe_string(retry_solve_result, "status") != "succeeded":
        recovery_attempt["final_status"] = "solve_failed"
        recovery_attempt["status"] = "solve_failed"
        assert_json_serializable(recovery_attempt)
        return recovery_attempt

    novelty_args = {"case_id": case_id}
    retry_novelty_result = to_json_dict(
        adapters["crystal.novelty_check"](
            {"step_index": 2, "tool_name": "crystal.novelty_check"},
            arguments=novelty_args,
            prior_step_results=_mapping_list(execution_run, "step_results")
            + [retry_validate_result, retry_solve_result],
            step_dir=recovery_root / "retry_novelty_check",
        )
    )
    _append_jsonl(
        recovery_log_path,
        _recovery_log_row(stage="retry_novelty_check", step_result=retry_novelty_result, arguments=novelty_args),
    )
    retry_novelty_ref = _copy_if_exists(
        _safe_string(retry_novelty_result, "raw_result_ref"),
        recovery_root / "retry_raw_novelty_response.json",
    )
    novelty_summary = (
        to_json_dict(retry_novelty_result.get("output_summary", {}))
        if isinstance(retry_novelty_result.get("output_summary"), Mapping)
        else {}
    )
    recovery_attempt["novelty"] = {
        "attempted": True,
        "status": _safe_string(retry_novelty_result, "status"),
        "is_novel": novelty_summary.get("is_novel"),
        "raw_novelty_response_ref": retry_novelty_ref,
        "error": to_json_dict(retry_novelty_result.get("error"))
        if isinstance(retry_novelty_result.get("error"), Mapping)
        else None,
    }
    recovery_attempt["final_status"] = (
        "completed" if _safe_string(retry_novelty_result, "status") == "succeeded" else "novelty_failed"
    )
    recovery_attempt["status"] = recovery_attempt["final_status"]
    assert_json_serializable(recovery_attempt)
    return recovery_attempt


def run_demo_execution_loop(
    *,
    out_dir: str | Path,
    planner_compile_run: Mapping[str, Any] | None = None,
    llm_runtime: Any | None = None,
    planner_input: Mapping[str, Any] | None = None,
    allow_real_execution: bool = False,
    allowed_tools: list[str] | None = None,
    adapters: dict[str, Any] | None = None,
    plan_source: str | None = None,
    mcp_backend: str | None = None,
    material_system: str | None = None,
    crystal_export_mode: str | None = None,
    crystal_demo_export_enabled: bool = False,
) -> dict[str, Any]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    if planner_compile_run is None:
        if llm_runtime is None or not isinstance(planner_input, Mapping):
            msg = "Provide planner_compile_run or both llm_runtime and planner_input."
            raise ValueError(msg)
        planner_result = run_live_planner_and_compile(
            llm_runtime,
            planner_input,
            out_dir=root / "planner",
            archive_trace=True,
            require_proposals=True,
        )
        run_id = planner_input.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            planner_result["run_id"] = run_id
        planner_result["plan_source"] = plan_source or "live_llm"
        planner_result["live_llm_used"] = True
        if isinstance(mcp_backend, str) and mcp_backend.strip():
            planner_result["mcp_backend"] = mcp_backend
        if isinstance(material_system, str) and material_system.strip():
            planner_result["material_system"] = material_system
        if isinstance(crystal_export_mode, str) and crystal_export_mode.strip():
            planner_result["crystal_export_mode"] = crystal_export_mode
        planner_result["crystal_demo_export_enabled"] = bool(crystal_demo_export_enabled)
    else:
        planner_result = to_json_dict(planner_compile_run)

    compile_result: dict[str, Any] | None = None
    if isinstance(planner_result.get("compile_result"), Mapping):
        compile_result = to_json_dict(planner_result["compile_result"])
    elif isinstance(planner_result.get("run_plan"), Mapping):
        compile_result = compile_run_plan_to_tool_proposals(
            to_json_dict(planner_result["run_plan"])
        )
        planner_result["compile_result"] = compile_result
    if compile_result is None:
        msg = "planner_compile_run must include compile_result."
        raise ValueError(msg)

    parse_report = build_tool_parse_report(compile_result, route_mode="demo_execution_loop")
    executable_plan = build_executable_plan_from_compile_result(compile_result)
    executable_plan_report = build_executable_plan_report(executable_plan)

    plan_dir = root / "plan"
    plan_dir.mkdir(parents=True, exist_ok=True)
    parse_report_path = plan_dir / "tool_parse_report.json"
    executable_plan_path = plan_dir / "executable_plan.json"
    executable_plan_report_path = plan_dir / "executable_plan_report.json"
    _write_json(parse_report_path, parse_report)
    _write_json(executable_plan_path, executable_plan)
    _write_json(executable_plan_report_path, executable_plan_report)
    active_adapters = adapters if adapters is not None else get_default_tool_execution_adapters()

    execution_run = execute_executable_plan(
        executable_plan,
        allow_real_execution=allow_real_execution,
        allowed_tools=allowed_tools,
        adapters=active_adapters,
        out_dir=root / "execution",
    )
    execution_artifact_paths = (
        to_json_dict(execution_run["artifact_paths"])
        if isinstance(execution_run.get("artifact_paths"), Mapping)
        else {}
    )
    execution_run_path = Path(
        str(
            execution_artifact_paths.get(
                "execution_run_json",
                root / "execution" / "execution_run.json",
            )
        )
    )
    step_log_path = Path(
        str(
            execution_artifact_paths.get(
                "execution_step_log_jsonl",
                root / "execution" / "execution_step_log.jsonl",
            )
        )
    )
    step_log_rows = _read_jsonl(step_log_path)
    result_inspection = inspect_step_results(execution_run)
    failure_handling = handle_inspection_failures(result_inspection)
    partial_success = build_partial_success_evaluation(
        {
            "route_mode": "demo_execution_loop",
            "source_run_id": str(planner_result.get("run_id", "")),
            "failure_handling": failure_handling,
        }
    )
    continuation_summary = build_continuation_summary(partial_success)
    recovery_attempt = _maybe_attempt_qlip_recovery(
        root=root,
        execution_run=execution_run,
        failure_handling=failure_handling,
        adapters=active_adapters,
    )
    if isinstance(recovery_attempt, Mapping):
        execution_run = dict(execution_run)
        execution_run["recovery_attempt"] = to_json_dict(recovery_attempt)
        _write_json(execution_run_path, execution_run)

    planner_trace: dict[str, Any] | None = None
    planner_trace_markdown_path: str | None = None
    trace_write = planner_result.get("trace_write")
    if isinstance(trace_write, Mapping):
        planner_trace_json = Path(str(trace_write.get("trace_json_path", "")))
        if planner_trace_json.exists():
            planner_trace = _read_json(planner_trace_json)
            planner_trace_markdown_path = _ensure_planner_trace_markdown(
                str(planner_trace_json),
                planner_trace,
            )

    report = build_execution_loop_report(
        planner_compile_run=planner_result,
        parse_report=parse_report,
        executable_plan=executable_plan,
        executable_plan_report=executable_plan_report,
        execution_run=execution_run,
        tool_execution_rows=step_log_rows,
        result_inspection=result_inspection,
        failure_handling=failure_handling,
        partial_success=partial_success,
        continuation_summary=continuation_summary,
        recovery_attempt=recovery_attempt,
        parse_report_path=str(parse_report_path),
        executable_plan_path=str(executable_plan_path),
        executable_plan_report_path=str(executable_plan_report_path),
        planner_trace_markdown_path=planner_trace_markdown_path,
    )
    report_write = write_execution_loop_report(
        report,
        root / "report",
        planner_trace=planner_trace,
    )
    workflow_evaluation = build_workflow_evaluation(
        report,
        execution_loop_report_path=report_write["report_markdown_path"],
    )
    workflow_evaluation_write = write_workflow_evaluation(
        workflow_evaluation,
        root / "report",
    )

    result = {
        "schema_version": DEMO_EXECUTION_LOOP_SCHEMA_VERSION,
        "status": str(execution_run.get("status", "")),
        "plan_source": str(planner_result.get("plan_source", plan_source or "live_llm")),
        "material_system": str(planner_result.get("material_system", material_system or "")),
        "mcp_backend": str(planner_result.get("mcp_backend", mcp_backend or "")),
        "live_llm_used": bool(planner_result.get("live_llm_used", (plan_source or "live_llm") == "live_llm")),
        "crystal_export_mode": str(planner_result.get("crystal_export_mode", "")),
        "crystal_demo_export_enabled": bool(planner_result.get("crystal_demo_export_enabled", False)),
        "artifact_paths": {
            "tool_parse_report_json": str(parse_report_path),
            "executable_plan_json": str(executable_plan_path),
            "executable_plan_report_json": str(executable_plan_report_path),
            "execution_run_json": str(execution_run_path),
            "execution_step_log_jsonl": str(step_log_path),
            "execution_loop_report_json": report_write["report_json_path"],
            "execution_loop_report_md": report_write["report_markdown_path"],
            "workflow_evaluation_json": workflow_evaluation_write["evaluation_json_path"],
            "workflow_evaluation_md": workflow_evaluation_write["evaluation_markdown_path"],
            "llm_and_tool_trace_md": report_write["llm_and_tool_trace_markdown_path"],
            **(
                {"planner_trace_json": str(trace_write["trace_json_path"])}
                if isinstance(trace_write, Mapping) and isinstance(trace_write.get("trace_json_path"), str)
                else {}
            ),
            **({"planner_trace_md": planner_trace_markdown_path} if planner_trace_markdown_path else {}),
            **(
                {
                    "recovery_step_log_jsonl": _safe_string(recovery_attempt, "recovery_step_log_path"),
                    "corrected_qlip_request_json": _safe_string(recovery_attempt, "corrected_request_path"),
                    "retry_validated_request_json": _safe_string(recovery_attempt.get("retry_validation", {}), "validated_request_ref")
                    if isinstance(recovery_attempt, Mapping)
                    else "",
                    "retry_raw_validation_response_json": _safe_string(recovery_attempt.get("retry_validation", {}), "raw_validation_response_ref")
                    if isinstance(recovery_attempt, Mapping)
                    else "",
                    "retry_raw_solve_response_json": _safe_string(recovery_attempt.get("solve", {}), "raw_solve_response_ref")
                    if isinstance(recovery_attempt, Mapping)
                    else "",
                }
                if isinstance(recovery_attempt, Mapping)
                else {}
            ),
        },
        "tool_sequence": _string_list(parse_report, "tool_sequence"),
        "executed_tool_sequence": _string_list(execution_run, "executed_tool_sequence"),
        "blocked_tool_sequence": _string_list(execution_run, "blocked_tool_sequence"),
        "report_markdown_path": report_write["report_markdown_path"],
        "workflow_evaluation_markdown_path": workflow_evaluation_write["evaluation_markdown_path"],
        "workflow_evaluation_json_path": workflow_evaluation_write["evaluation_json_path"],
        "execution_run_path": str(execution_run_path),
        "step_log_path": str(step_log_path),
        **({"recovery_attempt": to_json_dict(recovery_attempt)} if isinstance(recovery_attempt, Mapping) else {}),
    }
    assert_json_serializable(result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the agentic demo execution loop and write a showcase bundle.")
    parser.add_argument("--config", default=None, help="Optional YAML config path for configured backend mode.")
    parser.add_argument("--goal", required=True, help="Scientific goal to send to the planner.")
    parser.add_argument("--out-dir", required=True, help="Output directory for the demo showcase bundle.")
    parser.add_argument(
        "--material-system",
        default="CoAs2",
        help="Material system label to carry through the deterministic showcase report.",
    )
    parser.add_argument(
        "--plan-source",
        choices=("live", "showcase"),
        default=None,
        help="Use the live planner or a deterministic six-tool showcase plan.",
    )
    parser.add_argument(
        "--mcp-backend",
        required=True,
        choices=("fake", "configured"),
        help="Use repo fake MCP servers or the configured MCP commands.",
    )
    parser.add_argument(
        "--allow-crystal-demo-export",
        action="store_true",
        help="Enable Crystal-DB demo export mode for this showcase run by forcing configured Crystal-DB policy mode to demo.",
    )
    parser.add_argument("--zip", action="store_true", help="Also produce demo_showcase_bundle.zip.")
    parser.add_argument("--run-id", default="run_001", help="Run identifier to include in the demo.")
    parser.add_argument("--stage", default="wide_exploration", help="Planner stage to run.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    raw_run_dir = out_dir / "_raw_run"
    settings = build_demo_mcp_settings(
        raw_run_dir,
        args.mcp_backend,
        config_path=args.config,
        allow_crystal_demo_export=bool(args.allow_crystal_demo_export),
    )
    resolved_plan_source = args.plan_source or ("showcase" if args.mcp_backend == "fake" else "live")
    crystal_demo_export_enabled = bool(args.allow_crystal_demo_export)
    crystal_export_mode = "demo" if settings.crystaldb_policy_mode == "demo" else "safe"
    if resolved_plan_source == "showcase":
        run_plan = build_showcase_six_tool_run_plan(
            goal=args.goal,
            run_id=args.run_id,
            material_system=args.material_system,
            crystal_export_mode=crystal_export_mode,
            crystal_demo_export_enabled=crystal_demo_export_enabled,
        )
        planner_compile_run = _build_planner_compile_run_from_run_plan(
            run_plan,
            plan_source="deterministic_showcase",
            material_system=args.material_system,
            mcp_backend=args.mcp_backend,
            crystal_export_mode=crystal_export_mode,
            crystal_demo_export_enabled=crystal_demo_export_enabled,
        )
        demo_result = run_demo_execution_loop(
            out_dir=raw_run_dir,
            planner_compile_run=planner_compile_run,
            allow_real_execution=True,
            allowed_tools=list(DEFAULT_DEMO_ALLOWED_TOOLS),
            adapters=get_default_tool_execution_adapters(settings),
            plan_source="deterministic_showcase",
            mcp_backend=args.mcp_backend,
            material_system=args.material_system,
            crystal_export_mode=crystal_export_mode,
            crystal_demo_export_enabled=crystal_demo_export_enabled,
        )
    else:
        runtime = build_demo_runtime_from_settings(settings)
        demo_result = run_demo_execution_loop(
            out_dir=raw_run_dir,
            llm_runtime=runtime,
            planner_input={
                "run_id": args.run_id,
                "overall_goal": args.goal,
                "material_system": args.material_system,
                "run_goal": (
                    f"propose and execute a future csp workflow sequence from retrieval through novelty review "
                    f"for {args.material_system} using crystal.csp_pack, spp, qlip, and novelty steps"
                ),
                "stage": args.stage,
            },
            allow_real_execution=True,
            allowed_tools=list(DEFAULT_DEMO_ALLOWED_TOOLS),
            adapters=get_default_tool_execution_adapters(settings),
            plan_source="live_llm",
            mcp_backend=args.mcp_backend,
            material_system=args.material_system,
            crystal_export_mode=crystal_export_mode,
            crystal_demo_export_enabled=crystal_demo_export_enabled,
        )
    bundle_result = write_demo_showcase_bundle(
        demo_result,
        out_dir,
        zip_bundle=bool(args.zip),
    )

    print(f"AGENTIC_DEMO_BUNDLE_ROOT={bundle_result['bundle_root']}")
    print(f"AGENTIC_DEMO_REPORT_MD={bundle_result['report_markdown_path']}")
    print("AGENTIC_DEMO_SEQUENCE_DIAGRAM=execution_loop_report.md#sequence-diagram")
    print(f"AGENTIC_DEMO_ZIP={bundle_result['zip_path'] or 'NONE'}")
    return 0


__all__ = [
    "DEMO_EXECUTION_LOOP_SCHEMA_VERSION",
    "SHOWCASE_DEFAULT_GOAL",
    "DEFAULT_DEMO_ALLOWED_TOOLS",
    "build_showcase_six_tool_run_plan",
    "build_demo_mcp_settings",
    "build_demo_runtime_from_settings",
    "run_demo_execution_loop",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
