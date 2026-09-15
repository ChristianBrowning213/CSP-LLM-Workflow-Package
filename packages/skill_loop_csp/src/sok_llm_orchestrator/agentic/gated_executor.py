from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict
from .tool_execution_adapters import get_default_tool_execution_adapters

EXECUTION_RUN_SCHEMA_VERSION = "agentic_csp.execution_run.v1"


def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(to_json_dict(payload), sort_keys=True) + "\n")


def _artifact_ref_value(artifact_ref: Mapping[str, Any]) -> str | None:
    value = artifact_ref.get("value")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _explain_unresolved_refs(
    unresolved: list[str],
    prior_step_results: list[Mapping[str, Any]],
) -> tuple[str, str]:
    if "request_ref" in unresolved:
        for step_result in reversed(prior_step_results):
            if _safe_string(step_result, "tool_name") != "spp.run_pipeline":
                continue
            output_summary = step_result.get("output_summary") if isinstance(step_result.get("output_summary"), Mapping) else {}
            qlip_status = _safe_string(output_summary, "qlip_package_status")
            qlip_compatible = output_summary.get("qlip_solve_compatible")
            missing_pairs = output_summary.get("qlip_package_missing_pairs")
            missing = output_summary.get("qlip_package_missing")
            errors = output_summary.get("qlip_package_errors")
            reason = "SPP did not emit a solve-compatible QLIP request_ref."
            details: list[str] = []
            if qlip_status:
                details.append(f"qlip_package_status={qlip_status}")
            if qlip_compatible is not None:
                details.append(f"qlip_solve_compatible={str(bool(qlip_compatible)).lower()}")
            if isinstance(missing_pairs, list) and missing_pairs:
                details.append("missing_pairs=" + ", ".join(str(item) for item in missing_pairs))
            if isinstance(missing, list) and missing:
                details.append("missing=" + ", ".join(str(item) for item in missing))
            if isinstance(errors, list) and errors:
                first = errors[0]
                if isinstance(first, Mapping):
                    code = _safe_string(first, "code")
                    message = _safe_string(first, "message")
                    if code or message:
                        details.append(f"first_error={code or 'error'}: {message}")
            if details:
                reason = reason + " " + "; ".join(details)
            return "spp_request_ref_unavailable", reason

    if "corpus_ref" not in unresolved:
        return "unresolved_placeholder_ref", f"Unresolved proposal-time refs remain: {', '.join(unresolved)}"

    for step_result in reversed(prior_step_results):
        if _safe_string(step_result, "tool_name") != "crystal.csp_pack":
            continue
        output_summary = step_result.get("output_summary") if isinstance(step_result.get("output_summary"), Mapping) else {}
        exported_cif_count = output_summary.get("exported_cif_count")
        block_reasons = output_summary.get("export_block_reasons") if isinstance(output_summary.get("export_block_reasons"), list) else []
        if exported_cif_count == 0:
            reason_text = "; ".join(str(item) for item in block_reasons if isinstance(item, str) and item.strip())
            if reason_text:
                return "corpus_export_blocked", f"crystal.csp_pack produced no exportable CIFs; corpus_ref unavailable: {reason_text}"
            return "corpus_ref_unavailable", "crystal.csp_pack produced no exportable CIFs, so corpus_ref is unavailable for spp.run_pipeline."

    return "unresolved_placeholder_ref", f"Unresolved proposal-time refs remain: {', '.join(unresolved)}"


def _blocked_by_invalid_qlip_validation(
    tool_name: str,
    prior_step_results: list[Mapping[str, Any]],
) -> tuple[str, str] | None:
    if tool_name != "qlip.solve":
        return None
    for step_result in reversed(prior_step_results):
        if _safe_string(step_result, "tool_name") != "qlip.validate_request":
            continue
        output_summary = step_result.get("output_summary") if isinstance(step_result.get("output_summary"), Mapping) else {}
        if output_summary.get("valid") is not False:
            return None
        validation_errors = output_summary.get("validation_errors") if isinstance(output_summary.get("validation_errors"), list) else []
        diagnostics: list[str] = []
        for item in validation_errors[:3]:
            if not isinstance(item, Mapping):
                continue
            code = _safe_string(item, "code")
            message = _safe_string(item, "message")
            path = _safe_string(item, "path")
            detail = code or "validation_error"
            if path:
                detail = f"{detail} at {path}"
            if message:
                detail = f"{detail}: {message}"
            diagnostics.append(detail)
        if diagnostics:
            return "qlip_request_invalid", "qlip.validate_request returned valid=false; qlip.solve blocked. " + "; ".join(diagnostics)
        return "qlip_request_invalid", "qlip.validate_request returned valid=false; qlip.solve blocked."
    return None


def resolve_step_placeholders(
    next_step_arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(next_step_arguments, Mapping):
        msg = "next_step_arguments must be a mapping"
        raise TypeError(msg)

    resolved = to_json_dict(next_step_arguments)
    available_refs: dict[str, str] = {}
    for step_result in prior_step_results:
        artifact_refs = step_result.get("artifact_refs")
        if not isinstance(artifact_refs, list):
            continue
        for item in artifact_refs:
            if not isinstance(item, Mapping):
                continue
            ref_name = _safe_string(item, "ref_name")
            ref_value = _artifact_ref_value(item)
            if ref_name and ref_value:
                available_refs[ref_name] = ref_value

    for key, value in list(resolved.items()):
        if not (isinstance(value, str) and value.startswith("pending_")):
            continue
        if key in available_refs:
            resolved[key] = available_refs[key]
    return resolved


def _blocked_step_result(
    *,
    step: Mapping[str, Any],
    arguments: Mapping[str, Any],
    code: str,
    message: str,
) -> dict[str, Any]:
    result = {
        "schema_version": "agentic_csp.tool_execution_result.v1",
        "tool_name": _safe_string(step, "tool_name"),
        "execution_performed": False,
        "status": "blocked",
        "output_summary": {},
        "artifact_refs": [],
        "raw_result_ref": None,
        "raw_result_summary": {},
        "error": {"code": code, "message": message},
        "warnings": [],
        "step_index": int(step.get("step_index", 0)),
        "arguments": to_json_dict(arguments),
    }
    assert_json_serializable(result)
    return result


def execute_executable_plan(
    executable_plan: Mapping[str, Any],
    *,
    allow_real_execution: bool = False,
    allowed_tools: list[str] | None = None,
    adapters: dict[str, Any] | None = None,
    stop_on_failure: bool = True,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    if not isinstance(executable_plan, Mapping):
        msg = "executable_plan must be a mapping"
        raise TypeError(msg)

    plan_dict = to_json_dict(executable_plan)
    step_list = _mapping_list(plan_dict, "executable_steps")
    allowed_tool_set = {item for item in (allowed_tools or []) if isinstance(item, str) and item.strip()}
    active_adapters = adapters if adapters is not None else get_default_tool_execution_adapters()

    root = Path(out_dir) if out_dir is not None else (Path.cwd() / "agentic_execution_run")
    root.mkdir(parents=True, exist_ok=True)
    execution_run_path = root / "execution_run.json"
    step_log_path = root / "execution_step_log.jsonl"
    if step_log_path.exists():
        step_log_path.unlink()

    step_results: list[dict[str, Any]] = []
    executed_tool_sequence: list[str] = []
    blocked_tool_sequence: list[str] = []
    warnings = [
        str(item) for item in plan_dict.get("warnings", []) if isinstance(item, str) and item.strip()
    ] if isinstance(plan_dict.get("warnings"), list) else []
    stopped_reason: str | None = None

    for step in step_list:
        step_index = int(step.get("step_index", len(step_results)))
        tool_name = _safe_string(step, "tool_name")
        resolved_arguments = resolve_step_placeholders(
            to_json_dict(step.get("arguments", {})),
            step_results,
        )

        unresolved = [
            key
            for key, value in resolved_arguments.items()
            if isinstance(value, str) and value.startswith("pending_")
        ]
        if not allow_real_execution:
            step_result = _blocked_step_result(
                step=step,
                arguments=resolved_arguments,
                code="execution_not_allowed",
                message="allow_real_execution is false.",
            )
            blocked_tool_sequence.append(tool_name)
            stopped_reason = "execution_not_allowed"
        elif not allowed_tool_set:
            step_result = _blocked_step_result(
                step=step,
                arguments=resolved_arguments,
                code="no_allowed_tools",
                message="No tools were allowlisted for execution.",
            )
            blocked_tool_sequence.append(tool_name)
            stopped_reason = "no_allowed_tools"
        elif tool_name not in allowed_tool_set:
            step_result = _blocked_step_result(
                step=step,
                arguments=resolved_arguments,
                code="tool_not_allowed",
                message=f"{tool_name} is not allowlisted for execution.",
            )
            blocked_tool_sequence.append(tool_name)
            stopped_reason = "tool_not_allowed"
        elif unresolved:
            block_code, block_message = _explain_unresolved_refs(unresolved, step_results)
            step_result = _blocked_step_result(
                step=step,
                arguments=resolved_arguments,
                code=block_code,
                message=block_message,
            )
            blocked_tool_sequence.append(tool_name)
            stopped_reason = block_code
        elif _blocked_by_invalid_qlip_validation(tool_name, step_results) is not None:
            block_code, block_message = _blocked_by_invalid_qlip_validation(tool_name, step_results) or (
                "qlip_request_invalid",
                "qlip.validate_request returned valid=false; qlip.solve blocked.",
            )
            step_result = _blocked_step_result(
                step=step,
                arguments=resolved_arguments,
                code=block_code,
                message=block_message,
            )
            blocked_tool_sequence.append(tool_name)
            stopped_reason = block_code
        elif tool_name not in active_adapters:
            step_result = _blocked_step_result(
                step=step,
                arguments=resolved_arguments,
                code="unsupported_tool_adapter",
                message=f"No execution adapter is registered for {tool_name}.",
            )
            blocked_tool_sequence.append(tool_name)
            stopped_reason = "unsupported_tool_adapter"
        else:
            step_dir = root / f"step_{step_index:03d}_{tool_name.replace('.', '_')}"
            step_dir.mkdir(parents=True, exist_ok=True)
            adapter_result = active_adapters[tool_name](
                step,
                arguments=resolved_arguments,
                prior_step_results=step_results,
                step_dir=step_dir,
            )
            step_result = to_json_dict(adapter_result)
            step_result["step_index"] = step_index
            step_result["arguments"] = resolved_arguments
            if step_result.get("execution_performed") is True:
                executed_tool_sequence.append(tool_name)
            if step_result.get("status") == "blocked":
                blocked_tool_sequence.append(tool_name)
                stopped_reason = _safe_string(
                    step_result.get("error", {}) if isinstance(step_result.get("error"), Mapping) else {},
                    "code",
                    "blocked",
                )
            elif step_result.get("status") == "failed":
                stopped_reason = _safe_string(
                    step_result.get("error", {}) if isinstance(step_result.get("error"), Mapping) else {},
                    "code",
                    "failed",
                )

        if step_result.get("status") == "succeeded":
            decision = "continue"
        elif step_result.get("status") == "failed":
            decision = "stop_on_failure" if stop_on_failure else "continue_after_failure"
        else:
            decision = "blocked"

        log_row = {
            "step_index": step_index,
            "tool_name": tool_name,
            "arguments": resolved_arguments,
            "execution_performed": bool(step_result.get("execution_performed")),
            "status": step_result.get("status"),
            "output_summary": step_result.get("output_summary", {}),
            "artifact_refs": step_result.get("artifact_refs", []),
            "error": step_result.get("error"),
            "decision": decision,
        }
        _append_jsonl(step_log_path, log_row)
        step_results.append(step_result)

        if step_result.get("status") in {"blocked", "failed"} and stop_on_failure:
            break

    execution_performed = any(item.get("execution_performed") is True for item in step_results)
    statuses = [str(item.get("status")) for item in step_results]
    if not step_results:
        final_status = "blocked"
        stopped_reason = stopped_reason or "no_steps"
    elif all(status == "succeeded" for status in statuses) and len(step_results) == len(step_list):
        final_status = "completed"
        stopped_reason = None
    elif not execution_performed and any(status == "blocked" for status in statuses):
        final_status = "blocked"
    elif any(status == "failed" for status in statuses):
        final_status = "partial" if executed_tool_sequence else "failed"
    elif any(status == "blocked" for status in statuses):
        final_status = "partial" if executed_tool_sequence else "blocked"
    else:
        final_status = "partial"

    result = {
        "schema_version": EXECUTION_RUN_SCHEMA_VERSION,
        "status": final_status,
        "execution_performed": execution_performed,
        "executed_tool_sequence": executed_tool_sequence,
        "blocked_tool_sequence": blocked_tool_sequence,
        "step_results": step_results,
        "stopped_reason": stopped_reason,
        "artifact_paths": {
            "execution_run_json": str(execution_run_path),
            "execution_step_log_jsonl": str(step_log_path),
        },
        "warnings": warnings,
    }
    _write_json(execution_run_path, result)
    assert_json_serializable(result)
    return result


__all__ = [
    "EXECUTION_RUN_SCHEMA_VERSION",
    "execute_executable_plan",
    "resolve_step_placeholders",
]
