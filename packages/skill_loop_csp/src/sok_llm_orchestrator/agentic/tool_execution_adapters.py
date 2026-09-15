from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.crystaldb import apply_crystal_policy_defaults
from sok_llm_orchestrator.contracts.qlip_builders import (
    MaterialSystemError,
    build_solve_request,
    resolve_formula,
)
from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_solve_request
from sok_llm_orchestrator.contracts.spp_normalize import normalize_spp_arguments
from sok_llm_orchestrator.mcp.stdio_client import MCPClientError, StdioMCPClient

from .schemas import assert_json_serializable, to_json_dict

TOOL_EXECUTION_RESULT_SCHEMA_VERSION = "agentic_csp.tool_execution_result.v1"


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _result(
    *,
    tool_name: str,
    execution_performed: bool,
    status: str,
    output_summary: dict[str, Any] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    raw_result_ref: str | None = None,
    raw_result_summary: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": TOOL_EXECUTION_RESULT_SCHEMA_VERSION,
        "tool_name": tool_name,
        "execution_performed": bool(execution_performed),
        "status": status,
        "output_summary": output_summary if isinstance(output_summary, dict) else {},
        "artifact_refs": artifact_refs if isinstance(artifact_refs, list) else [],
        "raw_result_ref": raw_result_ref,
        "raw_result_summary": raw_result_summary if isinstance(raw_result_summary, dict) else {},
        "error": error if isinstance(error, dict) else None,
        "warnings": warnings if isinstance(warnings, list) else [],
    }
    assert_json_serializable(result)
    return result


def _blocked(tool_name: str, code: str, message: str, *, warnings: list[str] | None = None) -> dict[str, Any]:
    return _result(
        tool_name=tool_name,
        execution_performed=False,
        status="blocked",
        error={"code": code, "message": message},
        warnings=warnings,
    )


def _failed(
    tool_name: str,
    code: str,
    message: str,
    *,
    execution_performed: bool,
    raw_result_ref: str | None = None,
    raw_result_summary: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return _result(
        tool_name=tool_name,
        execution_performed=execution_performed,
        status="failed",
        raw_result_ref=raw_result_ref,
        raw_result_summary=raw_result_summary,
        error={"code": code, "message": message},
        warnings=warnings,
    )


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _command_text(command: str | list[str]) -> str:
    if isinstance(command, list):
        return " ".join(str(item) for item in command)
    return str(command)


def _spp_server_env(settings: Settings, extra_env: dict[str, str] | None = None) -> dict[str, str]:
    merged_env = dict(extra_env or {})
    if not settings.spp_mcp_cwd:
        return merged_env
    cwd = Path(settings.spp_mcp_cwd)
    resolved_cwd = cwd.resolve()
    src_path = resolved_cwd / "src"
    if not src_path.exists():
        return merged_env
    existing = merged_env.get("PYTHONPATH", os.environ.get("PYTHONPATH", ""))
    parts = [str(src_path)]
    if existing:
        parts.append(existing)
    merged_env["PYTHONPATH"] = os.pathsep.join(parts)
    return merged_env


def _spp_configured_server_identity(settings: Settings) -> dict[str, Any]:
    cwd = Path(settings.spp_mcp_cwd).resolve() if settings.spp_mcp_cwd else None
    src_path = cwd / "src" if cwd is not None else None
    return {
        "mcp_server_cmd": _command_text(settings.spp_mcp_cmd),
        "mcp_server_cwd": str(cwd) if cwd is not None else None,
        "mcp_server_src": str(src_path) if src_path is not None and src_path.exists() else None,
    }


def _spp_path_env(*, read_roots: list[Path] | None = None, write_roots: list[Path] | None = None) -> dict[str, str]:
    env: dict[str, str] = {}
    if read_roots:
        env["SPP_MCP_ALLOWED_READ_ROOTS"] = os.pathsep.join(str(path.resolve()) for path in read_roots)
    if write_roots:
        env["SPP_MCP_ALLOWED_WRITE_ROOTS"] = os.pathsep.join(str(path.resolve()) for path in write_roots)
    return env


def _is_fake_spp_command(command: str | list[str]) -> bool:
    return "mcp_spp_server.py" in _command_text(command)


def _uses_real_spp_maker_mcp(settings: Settings) -> bool:
    return "spp_maker_mcp.server" in _command_text(settings.spp_mcp_cmd)


def _mcp_call_arguments(tool_name: str, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
    if tool_name.startswith("spp.") and _uses_real_spp_maker_mcp(settings):
        return {"arguments": arguments}
    return arguments


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _formula_elements(formula: str) -> list[str]:
    elements: list[str] = []
    for match in re.finditer(r"([A-Z][a-z]?)(?:\d*)", formula):
        symbol = match.group(1)
        if symbol not in elements:
            elements.append(symbol)
    return elements


def _formula_counts(formula: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in re.finditer(r"([A-Z][a-z]?)(\d*)", formula):
        symbol = match.group(1)
        amount = int(match.group(2) or "1")
        counts[symbol] = counts.get(symbol, 0) + amount
    return counts


def _is_abo3_like(formula: str) -> bool:
    counts = _formula_counts(formula)
    if counts.get("O") != 3:
        return False
    non_oxygen = [symbol for symbol in counts if symbol != "O"]
    return len(non_oxygen) == 2 and all(counts[symbol] == 1 for symbol in non_oxygen)


def _required_pairs_for_formula(formula: str) -> list[str]:
    elements = sorted(_formula_elements(formula), key=lambda item: item.lower())
    pairs: list[str] = []
    for left_index, left in enumerate(elements):
        for right in elements[left_index:]:
            pairs.append(f"{left}-{right}")
    return pairs


def _pair_key(pair: str) -> str:
    parts = [part.strip() for part in pair.replace("_", "-").split("-") if part.strip()]
    if len(parts) != 2:
        return pair.strip()
    return "-".join(sorted(parts, key=lambda item: item.lower()))


def _pair_aliases(pair: str) -> list[str]:
    parts = [part.strip() for part in pair.replace("_", "-").split("-") if part.strip()]
    if len(parts) != 2:
        return [pair.strip()] if pair.strip() else []
    left, right = parts
    aliases = [f"{left}-{right}"]
    reverse = f"{right}-{left}"
    if reverse not in aliases:
        aliases.append(reverse)
    canonical = _pair_key(pair)
    if canonical not in aliases:
        aliases.append(canonical)
    return aliases


def _pot_path_for_pair(pot_root: str, pair: str) -> str | None:
    root = Path(pot_root)
    if not pot_root or not root.exists():
        return None
    candidates: list[Path] = []
    for alias in _pair_aliases(pair):
        candidates.extend(
            [
                root / alias / f"{alias}.POT",
                root / alias / f"{alias}.pot",
                root / f"{alias}.POT",
                root / f"{alias}.pot",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    alias_keys = {_pair_key(alias) for alias in _pair_aliases(pair)}
    for path in root.rglob("*.POT"):
        if _pair_key(path.stem.replace("_", "-")) in alias_keys:
            return str(path)
    for path in root.rglob("*.pot"):
        if _pair_key(path.stem.replace("_", "-")) in alias_keys:
            return str(path)
    return None


def _pairs_from_pot_root(pot_root: str) -> list[str]:
    root = Path(pot_root)
    if not pot_root or not root.exists():
        return []
    pairs: list[str] = []
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        manifest_pairs = manifest.get("pairs") if isinstance(manifest, Mapping) else None
        if isinstance(manifest_pairs, list):
            for item in manifest_pairs:
                if isinstance(item, str) and item.strip():
                    pairs.append(item.strip())
                elif isinstance(item, Mapping):
                    pair = _safe_string(item, "pair") or _safe_string(item, "name")
                    if pair:
                        pairs.append(pair)
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".pot", ".json"}:
            continue
        stem = path.stem.replace("_", "-")
        if "-" in stem:
            pairs.append(stem)
    return sorted(dict.fromkeys(pairs))


def _missing_pot_pairs(required_pairs: list[str], pot_root: str) -> tuple[list[str], list[str]]:
    available_pairs = _pairs_from_pot_root(pot_root)
    available_keys = {_pair_key(pair) for pair in available_pairs}
    missing = [pair for pair in required_pairs if _pair_key(pair) not in available_keys]
    return available_pairs, missing


def _pot_root_material_mismatch(formula: str, pot_root: str) -> str | None:
    if not formula or not pot_root:
        return None
    root = Path(pot_root)
    context_parts = [str(root)]
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        if isinstance(manifest, Mapping):
            for key in ("cif_dir", "material_system", "formula", "name", "run_name"):
                value = manifest.get(key)
                if isinstance(value, str) and value.strip():
                    context_parts.append(value)
    context = " ".join(context_parts)
    if "ABO3" in context and not _is_abo3_like(formula):
        return "ABO3"
    return None


def _request_formula_and_pot(request_payload: Mapping[str, Any]) -> tuple[str, str, list[str], list[str]]:
    problem = request_payload.get("problem") if isinstance(request_payload.get("problem"), Mapping) else {}
    chemistry = problem.get("chemistry") if isinstance(problem.get("chemistry"), Mapping) else {}
    context = request_payload.get("context") if isinstance(request_payload.get("context"), Mapping) else {}
    formula = _safe_string(chemistry, "formula")
    pot_root = _safe_string(context, "pot_root")
    required_pairs = _required_pairs_for_formula(formula) if formula else []
    available_pairs, missing_pairs = _missing_pot_pairs(required_pairs, pot_root) if pot_root else ([], required_pairs)
    _ = available_pairs
    return formula, pot_root, required_pairs, missing_pairs


def _qlip_request_path_env(settings: Settings, request_payload: Mapping[str, Any]) -> dict[str, str]:
    roots = [Path(root).resolve() for root in settings.qlip_allowed_path_roots]
    context = request_payload.get("context") if isinstance(request_payload.get("context"), Mapping) else {}
    pot_root = _safe_string(context, "pot_root")
    if pot_root:
        roots.append(Path(pot_root).resolve())
    guidance_items = request_payload.get("guidance")
    if isinstance(guidance_items, list):
        for guidance in guidance_items:
            if not isinstance(guidance, Mapping):
                continue
            params = guidance.get("params") if isinstance(guidance.get("params"), Mapping) else {}
            raw_weight = params.get("regularisation_weight", params.get("regularization_weight", 0.0))
            try:
                regularisation_weight = float(raw_weight or 0.0)
            except (TypeError, ValueError):
                regularisation_weight = 0.0
            if regularisation_weight <= 0.0:
                continue
            for key in ("regularisation_spp_dir", "regularization_spp_dir"):
                value = params.get(key)
                if not isinstance(value, str) or not value.strip():
                    continue
                regularisation_root = Path(value).resolve()
                if regularisation_root.exists():
                    roots.append(regularisation_root)
    if not roots:
        return {}
    return {"QLIP_ALLOWED_PATH_ROOTS": os.pathsep.join(str(root) for root in dict.fromkeys(roots))}


def _unwrap_mcp_payload(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    result = response.get("result", response)
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, Mapping):
                    continue
                if item.get("type") == "json" and isinstance(item.get("json"), Mapping):
                    return to_json_dict(item["json"])
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    text = str(item["text"]).strip()
                    if text.startswith("{") and text.endswith("}"):
                        try:
                            parsed = json.loads(text)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(parsed, Mapping):
                            return to_json_dict(parsed)
    structured = response.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    return response


def _write_raw_response(step_dir: Path, response: dict[str, Any]) -> str:
    raw_path = step_dir / "raw_tool_response.json"
    _write_json(raw_path, response)
    return str(raw_path)


def _client_for_tool(tool_name: str, settings: Settings, *, extra_env: dict[str, str] | None = None) -> StdioMCPClient:
    merged_env = dict(extra_env or {})
    if tool_name.startswith("crystal."):
        merged_env["CRYSTALDB_POLICY_MODE"] = settings.crystaldb_policy_mode
        return StdioMCPClient(
            settings.crystaldb_mcp_cmd,
            timeout_s=max(30, int(settings.max_runtime_seconds)),
            cwd=settings.crystaldb_mcp_cwd,
            env=merged_env,
        )
    if tool_name.startswith("spp."):
        return StdioMCPClient(
            settings.spp_mcp_cmd,
            timeout_s=max(30, int(settings.max_runtime_seconds)),
            cwd=settings.spp_mcp_cwd,
            env=_spp_server_env(settings, merged_env),
        )
    if tool_name.startswith("qlip."):
        if settings.qlip_allowed_path_roots:
            merged_env.setdefault(
                "QLIP_ALLOWED_PATH_ROOTS",
                os.pathsep.join(str(Path(root).resolve()) for root in settings.qlip_allowed_path_roots),
            )
        return StdioMCPClient(
            settings.qlip_mcp_cmd,
            timeout_s=max(30, int(settings.max_runtime_seconds)),
            cwd=settings.qlip_mcp_cwd,
            env=merged_env,
        )
    msg = f"unsupported tool family: {tool_name}"
    raise KeyError(msg)


def _call_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    settings: Settings,
    step_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[dict[str, Any], str]:
    with _client_for_tool(tool_name, settings, extra_env=extra_env) as client:
        response = client.call_tool(tool_name, _mcp_call_arguments(tool_name, arguments, settings))
    return response, _write_raw_response(step_dir, response)


def _first_artifact_ref(prior_step_results: list[Mapping[str, Any]], ref_name: str) -> str | None:
    for step_result in reversed(prior_step_results):
        artifact_refs = step_result.get("artifact_refs")
        if not isinstance(artifact_refs, list):
            continue
        for item in artifact_refs:
            if not isinstance(item, Mapping):
                continue
            if item.get("ref_name") == ref_name and isinstance(item.get("value"), str) and str(item.get("value")).strip():
                return str(item.get("value"))
    return None


def _artifact_ref_candidates(prior_step_results: list[Mapping[str, Any]], ref_names: tuple[str, ...]) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for step_result in reversed(prior_step_results):
        artifact_refs = step_result.get("artifact_refs")
        if not isinstance(artifact_refs, list):
            continue
        for item in artifact_refs:
            if not isinstance(item, Mapping):
                continue
            ref_name = _safe_string(item, "ref_name")
            value = _safe_string(item, "value")
            if ref_name in ref_names and value:
                candidates.append({"ref_name": ref_name, "value": value})
    return candidates


def _first_prior_argument(prior_step_results: list[Mapping[str, Any]], tool_name: str, key: str) -> str | None:
    for step_result in reversed(prior_step_results):
        if step_result.get("tool_name") != tool_name:
            continue
        arguments = step_result.get("arguments")
        if isinstance(arguments, Mapping):
            value = arguments.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _first_prior_summary_value(prior_step_results: list[Mapping[str, Any]], tool_name: str, key: str) -> str | None:
    for step_result in reversed(prior_step_results):
        if step_result.get("tool_name") != tool_name:
            continue
        summary = step_result.get("output_summary")
        if isinstance(summary, Mapping):
            value = summary.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _crystal_csp_pack_adapter(
    step: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
    step_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    _ = prior_step_results
    query = _safe_string(arguments, "objective_family", _safe_string(arguments, "case_id"))
    if not query:
        return _blocked("crystal.csp_pack", "missing_query_seed", "objective_family or case_id is required for crystal.csp_pack.")

    out_dir = step_dir / "csp_pack"
    call_args = {
        "query": query,
        "out_dir": str(out_dir),
        "export_top": 1,
    }
    material_system = _safe_string(arguments, "material_system")
    if material_system:
        call_args["material_system"] = material_system
        call_args["semantic_min_threshold"] = float(arguments.get("semantic_min_threshold", 0.25) or 0.25)
    if settings.crystaldb_policy_mode == "demo":
        call_args["demo_export"] = True
    call_args, policy_notes = apply_crystal_policy_defaults(call_args, settings.crystaldb_policy_mode)
    try:
        response, raw_ref = _call_tool("crystal.csp_pack", call_args, settings=settings, step_dir=step_dir)
    except MCPClientError as exc:
        return _failed(
            "crystal.csp_pack",
            "mcp_call_failed",
            str(exc),
            execution_performed=False,
            raw_result_summary={"query": query},
            warnings=policy_notes,
        )

    payload = _unwrap_mcp_payload(response)
    status = _safe_string(payload, "status", "unknown")
    if status.lower() not in {"ok", "partial"}:
        error_payload = payload.get("errors") if isinstance(payload.get("errors"), Mapping) else {}
        return _failed(
            "crystal.csp_pack",
            _safe_string(error_payload, "code", "tool_failed"),
            _safe_string(error_payload, "message", f"crystal.csp_pack returned status={status}"),
            execution_performed=True,
            raw_result_ref=raw_ref,
            raw_result_summary={"status": status, "errors": to_json_dict(error_payload) if error_payload else {}},
            warnings=policy_notes,
        )

    export_bundle = payload.get("export") if isinstance(payload.get("export"), Mapping) else {}
    if not export_bundle:
        export_bundle = payload.get("exports") if isinstance(payload.get("exports"), Mapping) else {}

    cifs_dir_text = _safe_string(export_bundle, "cif_dir", _safe_string(export_bundle, "cifs_dir"))
    corpus_ref: str | None = None
    exported_cifs: list[str] = []
    if cifs_dir_text:
        cifs_dir = Path(cifs_dir_text)
        if cifs_dir.exists():
            exported_cifs = sorted(str(path) for path in cifs_dir.glob("*.cif"))
    if not exported_cifs:
        export_items = export_bundle.get("items") if isinstance(export_bundle.get("items"), list) else []
        for item in export_items:
            if not isinstance(item, Mapping):
                continue
            cif_path = _safe_string(item, "cif_path")
            if not cif_path:
                continue
            cif_file = Path(cif_path)
            if cif_file.exists():
                exported_cifs.append(str(cif_file))
    if exported_cifs:
        exported_cifs = sorted(dict.fromkeys(exported_cifs))
        corpus_ref = str(Path(exported_cifs[0]).parent)

    artifact_refs: list[dict[str, Any]] = []
    if corpus_ref:
        artifact_refs.append({"ref_name": "corpus_ref", "value": corpus_ref, "kind": "directory"})
    if exported_cifs:
        artifact_refs.append({"ref_name": "candidate_cif_path", "value": exported_cifs[0], "kind": "file"})
    for ref_name, key in (
        ("crystal_manifest_json", "manifest_path"),
        ("crystal_results_json", "results_path"),
    ):
        value = _safe_string(export_bundle, key)
        if value:
            artifact_refs.append({"ref_name": ref_name, "value": value, "kind": "file"})

    export_items = export_bundle.get("items") if isinstance(export_bundle.get("items"), list) else []
    export_block_reasons: list[str] = []
    export_status_counts: dict[str, int] = {}
    for item in export_items:
        if not isinstance(item, Mapping):
            continue
        status_name = _safe_string(item, "export_status", "unknown")
        export_status_counts[status_name] = export_status_counts.get(status_name, 0) + 1
        error_text = _safe_string(item, "error")
        if error_text:
            export_block_reasons.append(error_text)
    export_block_reasons = sorted(dict.fromkeys(export_block_reasons))

    warnings = list(policy_notes)
    if not exported_cifs and export_block_reasons:
        warnings.append(f"crystal_export_blocked:{'; '.join(export_block_reasons)}")

    neighbors = payload.get("neighbors") if isinstance(payload.get("neighbors"), list) else []
    corpus_selection = payload.get("corpus_selection") if isinstance(payload.get("corpus_selection"), Mapping) else {}
    if status.lower() == "partial":
        error_payload = payload.get("errors") if isinstance(payload.get("errors"), Mapping) else {}
        useful_partial = bool(corpus_selection.get("useful_partial_pair_evidence")) and len(exported_cifs) > 0
        if useful_partial:
            warnings = warnings + [
                json.dumps(
                    {
                        "code": _safe_string(error_payload, "code", "partial_pair_coverage"),
                        "message": _safe_string(
                            error_payload,
                            "message",
                            "Crystal-DB returned useful partial pair evidence, not complete SPP coverage.",
                        ),
                        "corpus_selection_status": corpus_selection.get("corpus_selection_status"),
                        "covered_required_pairs": corpus_selection.get("covered_required_pairs", []),
                        "missing_required_pairs": corpus_selection.get("missing_required_pairs", []),
                    },
                    sort_keys=True,
                )
            ]
            return _result(
                tool_name="crystal.csp_pack",
                execution_performed=True,
                status="succeeded",
                output_summary={
                    "query": query,
                    "material_system": material_system or None,
                    "neighbor_count": len([item for item in neighbors if isinstance(item, Mapping)]),
                    "exported_cif_count": len(exported_cifs),
                    "export_status_counts": export_status_counts,
                    "export_block_reasons": export_block_reasons,
                    "corpus_selection": to_json_dict(corpus_selection),
                    "corpus_selection_status": _safe_string(corpus_selection, "corpus_selection_status", "partial_pair_coverage"),
                    "covered_required_pairs": corpus_selection.get("covered_required_pairs", []),
                    "missing_required_pairs": corpus_selection.get("missing_required_pairs", []),
                    "useful_partial_pair_evidence": True,
                },
                artifact_refs=artifact_refs,
                raw_result_ref=raw_ref,
                raw_result_summary={"status": status, "errors": to_json_dict(error_payload) if error_payload else {}},
                warnings=warnings,
            )
        return _result(
            tool_name="crystal.csp_pack",
            execution_performed=True,
            status="blocked",
            output_summary={
                "query": query,
                "material_system": material_system or None,
                "neighbor_count": len([item for item in neighbors if isinstance(item, Mapping)]),
                "exported_cif_count": len(exported_cifs),
                "export_status_counts": export_status_counts,
                "export_block_reasons": export_block_reasons,
                "corpus_selection": to_json_dict(corpus_selection),
            },
            artifact_refs=artifact_refs,
            raw_result_ref=raw_ref,
            raw_result_summary={"status": status, "errors": to_json_dict(error_payload) if error_payload else {}},
            error={
                "code": _safe_string(error_payload, "code", "partial_corpus_selection"),
                "message": _safe_string(error_payload, "message", "crystal.csp_pack returned a partial corpus-selection result."),
            },
            warnings=warnings,
        )
    return _result(
        tool_name="crystal.csp_pack",
        execution_performed=True,
        status="succeeded",
        output_summary={
            "query": query,
            "material_system": material_system or None,
            "neighbor_count": len([item for item in neighbors if isinstance(item, Mapping)]),
            "exported_cif_count": len(exported_cifs),
            "export_status_counts": export_status_counts,
            "export_block_reasons": export_block_reasons,
            "corpus_selection": to_json_dict(corpus_selection),
        },
        artifact_refs=artifact_refs,
        raw_result_ref=raw_ref,
        warnings=warnings,
    )


def _spp_run_pipeline_adapter(
    step: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
    step_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    corpus_ref = _safe_string(arguments, "corpus_ref")
    if not corpus_ref:
        return _blocked("spp.run_pipeline", "missing_corpus_ref", "corpus_ref is required for spp.run_pipeline.")
    cif_dir = Path(corpus_ref)
    if not cif_dir.exists():
        return _blocked("spp.run_pipeline", "missing_corpus_path", f"corpus_ref path does not exist: {corpus_ref}")
    cif_count = len(list(cif_dir.glob("*.cif")))
    if cif_count == 0:
        return _blocked("spp.run_pipeline", "empty_corpus_ref", f"corpus_ref contains no CIF files: {corpus_ref}")

    material_query = (
        _first_prior_argument(prior_step_results, "crystal.csp_pack", "objective_family")
        or _first_prior_argument(prior_step_results, "crystal.csp_pack", "query")
        or _first_prior_summary_value(prior_step_results, "crystal.csp_pack", "query")
        or _safe_string(arguments, "case_id")
    )
    try:
        material_system = resolve_formula(
            material_query,
            material_system=_safe_string(arguments, "material_system"),
            formula=_safe_string(arguments, "formula"),
        )
    except MaterialSystemError as exc:
        return _blocked("spp.run_pipeline", exc.code, exc.message)
    raw_args = {
        "cif_dir": str(cif_dir.resolve()),
        "out_dir": str((step_dir / "spp_run").resolve()),
        "name": _safe_string(arguments, "case_id", f"spp_{step.get('step_index', 0)}"),
        "qlip_pair_mode": _safe_string(arguments, "qlip_pair_mode", "required_pairs"),
        "qlip_pair_cutoff": arguments.get("qlip_pair_cutoff", 6.0),
        "runtime_profile": _safe_string(
            arguments,
            "runtime_profile",
            "probe" if _safe_string(arguments, "case_id").startswith("probe") else "demo",
        ),
        "calibration": {"target": 1.0},
    }
    raw_args["material_system"] = material_system
    call_args, normalization_warnings = normalize_spp_arguments("spp.run_pipeline", raw_args)
    try:
        response, raw_ref = _call_tool(
            "spp.run_pipeline",
            call_args,
            settings=settings,
            step_dir=step_dir,
            extra_env=_spp_path_env(
                read_roots=[cif_dir, Path(settings.spp_mcp_cwd)] if settings.spp_mcp_cwd else [cif_dir],
                write_roots=[step_dir],
            ),
        )
    except MCPClientError as exc:
        code = "mcp_call_failed" if _is_fake_spp_command(settings.spp_mcp_cmd) else "configured_spp_mcp_unavailable"
        return _failed(
            "spp.run_pipeline",
            code,
            str(exc),
            execution_performed=False,
            raw_result_summary={"cif_dir": str(cif_dir), **_spp_configured_server_identity(settings)},
            warnings=[json.dumps(item, sort_keys=True) for item in normalization_warnings],
        )

    payload = _unwrap_mcp_payload(response)
    if payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
        return _failed(
            "spp.run_pipeline",
            _safe_string(error, "code", "tool_failed"),
            _safe_string(error, "message", "spp.run_pipeline returned a non-ok response."),
            execution_performed=True,
            raw_result_ref=raw_ref,
            raw_result_summary={"ok": payload.get("ok"), **_spp_configured_server_identity(settings)},
            warnings=[json.dumps(item, sort_keys=True) for item in normalization_warnings],
        )

    result_payload = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    paths = result_payload.get("paths") if isinstance(result_payload.get("paths"), Mapping) else {}
    qlip_package = result_payload.get("qlip_package") if isinstance(result_payload.get("qlip_package"), Mapping) else {}
    qlip_package_status = _safe_string(qlip_package, "status")
    qlip_package_errors = [
        to_json_dict(item)
        for item in qlip_package.get("errors", [])
        if isinstance(item, Mapping)
    ] if isinstance(qlip_package.get("errors"), list) else []
    qlip_package_missing = [
        str(item)
        for item in qlip_package.get("missing", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(qlip_package.get("missing"), list) else []
    qlip_required_pairs = [
        str(item)
        for item in qlip_package.get("required_pairs", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(qlip_package.get("required_pairs"), list) else []
    package_declared_required_pairs = list(qlip_required_pairs)
    qlip_missing_pairs = [
        str(item)
        for item in qlip_package.get("missing_pairs", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(qlip_package.get("missing_pairs"), list) else []
    package_declared_missing_pairs = list(qlip_missing_pairs)
    qlip_sparse_pairs = [
        str(item)
        for item in qlip_package.get("sparse_pairs", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(qlip_package.get("sparse_pairs"), list) else []
    qlip_package_warnings = [
        json.dumps(to_json_dict(item), sort_keys=True) if isinstance(item, Mapping) else str(item)
        for item in qlip_package.get("warnings", [])
        if (isinstance(item, Mapping) or (isinstance(item, str) and item.strip()))
    ] if isinstance(qlip_package.get("warnings"), list) else []
    qlip_context = qlip_package.get("context") if isinstance(qlip_package.get("context"), Mapping) else {}
    pot_root = _safe_string(qlip_context, "pot_root")
    qlip_artifact_refs = [
        to_json_dict(item)
        for item in qlip_package.get("artifact_refs", [])
        if isinstance(item, Mapping)
    ] if isinstance(qlip_package.get("artifact_refs"), list) else []
    compatibility = (
        to_json_dict(qlip_package.get("compatibility"))
        if isinstance(qlip_package.get("compatibility"), Mapping)
        else to_json_dict(result_payload.get("compatibility"))
        if isinstance(result_payload.get("compatibility"), Mapping)
        else {}
    )
    qlip_solve_compatible = (
        qlip_package.get("qlip_solve_compatible")
        if isinstance(qlip_package, Mapping) and "qlip_solve_compatible" in qlip_package
        else result_payload.get("qlip_solve_compatible")
    )
    formula = material_system
    formula_required_pairs = _required_pairs_for_formula(formula)
    required_pair_universe_source = "target_formula" if formula_required_pairs else "package"
    full_required_pairs = formula_required_pairs or list(qlip_required_pairs)
    if not qlip_required_pairs:
        qlip_required_pairs = list(full_required_pairs)
    available_pairs: list[str] = [
        str(item)
        for item in qlip_package.get("available_pairs", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(qlip_package.get("available_pairs"), list) else []
    supported_pairs: list[str] = [
        str(item)
        for item in qlip_package.get("supported_pairs", [])
        if isinstance(item, str) and item.strip()
    ] if isinstance(qlip_package.get("supported_pairs"), list) else []
    package_declared_supported_pairs = list(supported_pairs)
    dropped_supported_pairs_without_pot: list[str] = []
    partial_guidance_pot_root = (
        _safe_string(qlip_package, "partial_guidance_pot_root")
        or _safe_string(qlip_package, "partial_pot_root")
    )
    supported_pair_pot_paths = (
        qlip_package.get("supported_pair_pot_paths")
        if isinstance(qlip_package.get("supported_pair_pot_paths"), Mapping)
        else {}
    )
    if partial_guidance_pot_root:
        real_partial_pairs = _pairs_from_pot_root(partial_guidance_pot_root)
        real_partial_keys = {_pair_key(pair) for pair in real_partial_pairs}
        if real_partial_keys:
            pair_universe = full_required_pairs or qlip_required_pairs or supported_pairs
            supported_pairs = [
                pair for pair in pair_universe
                if _pair_key(pair) in real_partial_keys
            ]
            supported_keys = {_pair_key(supported) for supported in supported_pairs}
            qlip_missing_pairs = [
                pair for pair in pair_universe
                if _pair_key(pair) not in supported_keys
            ]
            qlip_required_pairs = list(pair_universe)
            dropped_supported_pairs_without_pot = [
                pair for pair in package_declared_supported_pairs
                if _pair_key(pair) not in supported_keys
            ]
            supported_pair_pot_paths = {
                pair: str(Path(path))
                for pair, path in supported_pair_pot_paths.items()
                if (
                    isinstance(pair, str)
                    and isinstance(path, str)
                    and Path(path).is_file()
                    and _pair_key(pair) in supported_keys
                )
            }
            for pair in supported_pairs:
                if pair not in supported_pair_pot_paths:
                    pot_path = _pot_path_for_pair(partial_guidance_pot_root, pair)
                    if pot_path:
                        supported_pair_pot_paths[pair] = pot_path
    qlip_partial_guidance_compatible = bool(
        qlip_package.get("qlip_partial_guidance_compatible")
        or qlip_package.get("can_use_as_partial_guidance")
    )
    selected_pot_root = pot_root or None
    if pot_root and qlip_solve_compatible is not False:
        available_pairs, local_missing_pairs = _missing_pot_pairs(qlip_required_pairs, pot_root)
        material_mismatch = _pot_root_material_mismatch(formula, pot_root)
        if material_mismatch:
            selected_pot_root = None
            qlip_solve_compatible = False
            if qlip_package_status in {"", "ready"}:
                qlip_package_status = "partial"
            if "pot_root_material_system_mismatch" not in qlip_package_missing:
                qlip_package_missing.append("pot_root_material_system_mismatch")
            qlip_package_errors.append(
                {
                    "code": "pot_root_material_system_mismatch",
                    "message": (
                        f"Returned POT root appears to be for {material_mismatch}, "
                        f"which is not compatible with material_system={formula}."
                    ),
                }
            )
        elif local_missing_pairs:
            selected_pot_root = None
            qlip_solve_compatible = False
            if qlip_package_status in {"", "ready"}:
                qlip_package_status = "partial"
            qlip_missing_pairs = sorted(dict.fromkeys(qlip_missing_pairs + local_missing_pairs))
            if "pot_pair_coverage" not in qlip_package_missing:
                qlip_package_missing.append("pot_pair_coverage")
            qlip_package_errors.append(
                {
                    "code": "pot_pair_coverage_missing",
                    "message": (
                        "Returned POT root does not cover all pairs required by "
                        f"{formula}: {', '.join(local_missing_pairs)}"
                    ),
                }
            )
    guidance_package_path = _safe_string(qlip_package, "guidance_package_path", _safe_string(result_payload, "guidance_package_path"))
    qlip_package_json_path = _safe_string(qlip_package, "package_json_path", _safe_string(result_payload, "package_json_path"))
    qlip_final_bundle_path = _safe_string(qlip_package, "final_bundle_path")
    spp_bundle_path = qlip_final_bundle_path or guidance_package_path or _safe_string(result_payload, "final_bundle")
    fresh_generation = (
        to_json_dict(qlip_package.get("fresh_generation"))
        if isinstance(qlip_package.get("fresh_generation"), Mapping)
        else {}
    )
    corpus_quality = (
        to_json_dict(fresh_generation.get("corpus_quality"))
        if isinstance(fresh_generation.get("corpus_quality"), Mapping)
        else {}
    )
    request_path: Path | None = None
    qlip_guidance_mode = "blocked"
    qlip_request_blocked_stage = ""
    qlip_request_blocked_reason = ""
    allow_qlip_without_spp = _truthy_env("SKILL_LOOP_ALLOW_QLIP_WITHOUT_SPP")
    allow_partial_spp_guidance = _truthy_env("SKILL_LOOP_ALLOW_PARTIAL_SPP_GUIDANCE")
    missing_pair_policy = os.environ.get("SKILL_LOOP_SPP_MISSING_PAIR_POLICY", "neutral").strip() or "neutral"
    try:
        spp_guidance_weight = float(os.environ.get("SKILL_LOOP_SPP_GUIDANCE_WEIGHT", "1.0"))
    except ValueError:
        spp_guidance_weight = 1.0
    spp_regularisation_dir = (
        os.environ.get("SKILL_LOOP_SPP_REGULARISATION_DIR")
        or os.environ.get("SKILL_LOOP_SPP_REGULARIZATION_DIR")
        or ""
    ).strip()
    raw_regularisation_weight = (
        os.environ.get("SKILL_LOOP_SPP_REGULARISATION_WEIGHT")
        or os.environ.get("SKILL_LOOP_SPP_REGULARIZATION_WEIGHT")
        or "0.0"
    )
    try:
        spp_regularisation_weight = float(raw_regularisation_weight)
    except ValueError:
        spp_regularisation_weight = 0.0
    can_build_spp_guided_request = qlip_package_status != "failed" and qlip_solve_compatible is not False and spp_bundle_path
    can_build_partial_spp_request = (
        qlip_package_status != "failed"
        and allow_partial_spp_guidance
        and qlip_partial_guidance_compatible
        and bool(partial_guidance_pot_root)
        and bool(supported_pairs)
    )
    can_build_no_spp_request = qlip_package_status != "failed" and allow_qlip_without_spp
    if can_build_spp_guided_request:
        query = _first_prior_argument(prior_step_results, "crystal.csp_pack", "objective_family") or _safe_string(arguments, "case_id")
        try:
            request_payload = build_solve_request(
                query,
                spp_bundle_path,
                pot_root=selected_pot_root,
                material_system=material_system,
                qlip_package=qlip_package,
                spp_guidance_weight=spp_guidance_weight,
                spp_regularisation_dir=spp_regularisation_dir or None,
                spp_regularisation_weight=spp_regularisation_weight,
            )
        except MaterialSystemError as exc:
            return _blocked("spp.run_pipeline", exc.code, exc.message)
        request_path = step_dir / "qlip_request.json"
        _write_json(request_path, request_payload)
        qlip_guidance_mode = "complete_spp"
    elif can_build_partial_spp_request:
        query = _first_prior_argument(prior_step_results, "crystal.csp_pack", "objective_family") or _safe_string(arguments, "case_id")
        try:
            request_payload = build_solve_request(
                query,
                None,
                pot_root=None,
                material_system=material_system,
                qlip_package=qlip_package,
                partial_spp_guidance={
                    "pot_root": partial_guidance_pot_root,
                    "supported_pairs": supported_pairs,
                    "missing_pairs": qlip_missing_pairs,
                    "missing_pair_policy": missing_pair_policy,
                    "missing_pair_penalty": 0.0,
                },
                spp_guidance_weight=spp_guidance_weight,
                spp_regularisation_dir=spp_regularisation_dir or None,
                spp_regularisation_weight=spp_regularisation_weight,
            )
        except MaterialSystemError as exc:
            return _blocked("spp.run_pipeline", exc.code, exc.message)
        request_path = step_dir / "qlip_request.json"
        _write_json(request_path, request_payload)
        qlip_guidance_mode = "partial_spp"
    elif can_build_no_spp_request:
        query = _first_prior_argument(prior_step_results, "crystal.csp_pack", "objective_family") or _safe_string(arguments, "case_id")
        try:
            request_payload = build_solve_request(
                query,
                None,
                pot_root=None,
                material_system=material_system,
                qlip_package=None,
                spp_guidance_weight=spp_guidance_weight,
            )
        except MaterialSystemError as exc:
            return _blocked("spp.run_pipeline", exc.code, exc.message)
        request_path = step_dir / "qlip_request.json"
        _write_json(request_path, request_payload)
        qlip_guidance_mode = "no_spp"
    else:
        if qlip_package_status == "failed":
            qlip_request_blocked_stage = "spp_generation"
            qlip_request_blocked_reason = "qlip_package_failed"
        elif qlip_solve_compatible is False:
            qlip_request_blocked_stage = "missing_required_guidance"
            qlip_request_blocked_reason = "qlip_package_not_solver_compatible"
        elif not spp_bundle_path:
            qlip_request_blocked_stage = "spp_generation"
            qlip_request_blocked_reason = "spp_bundle_path_missing"
        else:
            qlip_request_blocked_stage = "unknown"
            qlip_request_blocked_reason = "qlip_request_not_built"
    artifact_refs = [
        {"ref_name": "spp_package_ref", "value": _safe_string(result_payload, "run_root"), "kind": "directory"},
        {"ref_name": "spp_final_bundle_path", "value": _safe_string(result_payload, "final_bundle"), "kind": "directory"},
    ]
    if spp_bundle_path:
        artifact_refs.append({"ref_name": "spp_bundle_path", "value": spp_bundle_path, "kind": "directory"})
    if guidance_package_path:
        artifact_refs.append({"ref_name": "spp_guidance_package_path", "value": guidance_package_path, "kind": "directory"})
    if qlip_package_json_path:
        artifact_refs.append({"ref_name": "spp_qlip_package_json", "value": qlip_package_json_path, "kind": "file"})
    for item in qlip_artifact_refs:
        ref_name = _safe_string(item, "ref_name")
        value = _safe_string(item, "value")
        kind = _safe_string(item, "kind", "file")
        if ref_name and value:
            if ref_name in {"pot_root", "spp_pot_root"} and (
                qlip_solve_compatible is not True or selected_pot_root != value
            ):
                continue
            artifact_refs.append({"ref_name": ref_name, "value": value, "kind": kind})
            if ref_name == "pot_root":
                artifact_refs.append({"ref_name": "spp_pot_root", "value": value, "kind": "directory"})
    if selected_pot_root and not any(_safe_string(item, "ref_name") == "pot_root" for item in artifact_refs):
        artifact_refs.append({"ref_name": "pot_root", "value": selected_pot_root, "kind": "directory"})
        artifact_refs.append({"ref_name": "spp_pot_root", "value": selected_pot_root, "kind": "directory"})
    if request_path is not None:
        artifact_refs.append({"ref_name": "request_ref", "value": str(request_path), "kind": "file"})
    for ref_name, key, kind in (
        ("fit_spp_root", "fit_spp_root", "directory"),
        ("scaled_spp_root", "scaled_spp_root", "directory"),
        ("calibration_json", "calibration_json", "file"),
        ("spp_package_json", "package_json", "file"),
    ):
        value = _safe_string(paths, key)
        if value:
            artifact_refs.append({"ref_name": ref_name, "value": value, "kind": kind})
    return _result(
        tool_name="spp.run_pipeline",
        execution_performed=True,
        status="succeeded",
        output_summary={
            "cif_count": result_payload.get("cif_count"),
            "run_root": _safe_string(result_payload, "run_root"),
            "final_bundle": _safe_string(result_payload, "final_bundle"),
            "fit_spp_root": _safe_string(paths, "fit_spp_root"),
            "scaled_spp_root": _safe_string(paths, "scaled_spp_root"),
            "request_ref": str(request_path) if request_path is not None else None,
            "qlip_guidance_mode": qlip_guidance_mode,
            "qlip_request_attempted": request_path is not None,
            "qlip_request_blocked_stage": qlip_request_blocked_stage,
            "qlip_request_blocked_reason": qlip_request_blocked_reason,
            "spp_bundle_path": spp_bundle_path,
            "spp_guidance_package_path": guidance_package_path,
            "spp_qlip_package_json": qlip_package_json_path,
            "qlip_package_status": qlip_package_status,
            "qlip_solve_compatible": qlip_solve_compatible,
            "qlip_package_missing": qlip_package_missing,
            "qlip_package_required_pairs": qlip_required_pairs,
            "qlip_package_missing_pairs": qlip_missing_pairs,
            "required_pair_universe_source": required_pair_universe_source,
            "full_required_pairs": full_required_pairs,
            "package_declared_required_pairs": package_declared_required_pairs,
            "package_declared_missing_pairs": package_declared_missing_pairs,
            "file_truthful_supported_pairs": supported_pairs,
            "dropped_supported_pairs_without_pot": dropped_supported_pairs_without_pot,
            "qlip_package_sparse_pairs": qlip_sparse_pairs,
            "qlip_package_available_pairs": available_pairs,
            "qlip_package_supported_pairs": supported_pairs,
            "qlip_package_supported_pair_pot_paths": to_json_dict(supported_pair_pot_paths)
            if isinstance(supported_pair_pot_paths, Mapping)
            else {},
            "qlip_package_errors": qlip_package_errors,
            "qlip_package_compatibility": compatibility,
            "qlip_package_context": to_json_dict(qlip_context),
            "pot_root_source": _safe_string(qlip_package, "pot_root_source") or _safe_string(compatibility, "pot_root_source") or None,
            "extraction_mode": _safe_string(qlip_package, "extraction_mode") or _safe_string(compatibility, "extraction_mode") or None,
            "fresh_generation": fresh_generation,
            "corpus_quality": corpus_quality,
            "corpus_quality_status": _safe_string(corpus_quality, "corpus_quality_status") or None,
            "detected_formulas": corpus_quality.get("detected_formulas", []) if isinstance(corpus_quality.get("detected_formulas"), list) else [],
            "files_with_all_target_elements": corpus_quality.get("files_with_all_target_elements", []) if isinstance(corpus_quality.get("files_with_all_target_elements"), list) else [],
            "files_with_exact_or_reduced_formula_match": corpus_quality.get("files_with_exact_or_reduced_formula_match", []) if isinstance(corpus_quality.get("files_with_exact_or_reduced_formula_match"), list) else [],
            "files_with_target_cross_pairs": corpus_quality.get("files_with_target_cross_pairs", []) if isinstance(corpus_quality.get("files_with_target_cross_pairs"), list) else [],
            "geometric_pair_counts": corpus_quality.get("geometric_pair_counts", {}) if isinstance(corpus_quality.get("geometric_pair_counts"), Mapping) else {},
            "fallback_used": bool(qlip_package.get("fallback_used")) if "fallback_used" in qlip_package else bool(compatibility.get("fallback_used")),
            "fallback_reason": _safe_string(qlip_package, "fallback_reason") or _safe_string(compatibility, "fallback_reason") or None,
            "pot_root": pot_root or None,
            "selected_pot_root": selected_pot_root,
            "partial_guidance_pot_root": partial_guidance_pot_root or None,
            "qlip_partial_guidance_compatible": qlip_partial_guidance_compatible,
            "spp_missing_pair_policy": missing_pair_policy if qlip_guidance_mode == "partial_spp" else None,
            "spp_guidance_weight": spp_guidance_weight,
            "spp_regularisation_dir": spp_regularisation_dir or None,
            "spp_regularisation_weight": spp_regularisation_weight,
            "partial_pair_evidence_available": bool(supported_pairs and qlip_missing_pairs),
            "material_system": material_system or None,
            "formula": formula,
            **_spp_configured_server_identity(settings),
        },
        artifact_refs=[item for item in artifact_refs if _safe_string(item, "value")],
        raw_result_ref=raw_ref,
        warnings=[json.dumps(item, sort_keys=True) for item in normalization_warnings]
        + qlip_package_warnings
        + [
            json.dumps(item, sort_keys=True)
            for item in qlip_package_errors
        ],
    )


def _spp_package_for_qlip_adapter(
    step: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
    step_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    spp_package_ref = _safe_string(arguments, "spp_package_ref")
    if not spp_package_ref:
        return _blocked("spp.package_for_qlip", "missing_spp_package_ref", "spp_package_ref is required for spp.package_for_qlip.")
    run_root = Path(spp_package_ref)
    if not run_root.exists():
        return _blocked("spp.package_for_qlip", "missing_spp_run_root", f"spp_package_ref path does not exist: {spp_package_ref}")

    raw_args = {
        "run_root": str(run_root),
        "out_dir": str(step_dir / "spp_package"),
        "name": _safe_string(arguments, "case_id", f"spp_pkg_{step.get('step_index', 0)}"),
    }
    call_args, normalization_warnings = normalize_spp_arguments("spp.package_for_qlip", raw_args)
    try:
        response, raw_ref = _call_tool("spp.package_for_qlip", call_args, settings=settings, step_dir=step_dir)
    except MCPClientError as exc:
        return _failed(
            "spp.package_for_qlip",
            "mcp_call_failed",
            str(exc),
            execution_performed=False,
            raw_result_summary={"run_root": str(run_root)},
            warnings=[json.dumps(item, sort_keys=True) for item in normalization_warnings],
        )

    payload = _unwrap_mcp_payload(response)
    if payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
        return _failed(
            "spp.package_for_qlip",
            _safe_string(error, "code", "tool_failed"),
            _safe_string(error, "message", "spp.package_for_qlip returned a non-ok response."),
            execution_performed=True,
            raw_result_ref=raw_ref,
            raw_result_summary={"ok": payload.get("ok")},
            warnings=[json.dumps(item, sort_keys=True) for item in normalization_warnings],
        )

    result_payload = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    spp_bundle_path = _safe_string(result_payload, "final_bundle_path", _safe_string(result_payload, "package_json_path"))
    query = _first_prior_argument(prior_step_results, "crystal.csp_pack", "objective_family") or _safe_string(arguments, "case_id")
    try:
        try:
            spp_guidance_weight = float(os.environ.get("SKILL_LOOP_SPP_GUIDANCE_WEIGHT", "1.0"))
        except ValueError:
            spp_guidance_weight = 1.0
        spp_regularisation_dir = (
            os.environ.get("SKILL_LOOP_SPP_REGULARISATION_DIR")
            or os.environ.get("SKILL_LOOP_SPP_REGULARIZATION_DIR")
            or ""
        ).strip()
        raw_regularisation_weight = (
            os.environ.get("SKILL_LOOP_SPP_REGULARISATION_WEIGHT")
            or os.environ.get("SKILL_LOOP_SPP_REGULARIZATION_WEIGHT")
            or "0.0"
        )
        try:
            spp_regularisation_weight = float(raw_regularisation_weight)
        except ValueError:
            spp_regularisation_weight = 0.0
        material_system = resolve_formula(
            query,
            material_system=_safe_string(arguments, "material_system"),
            formula=_safe_string(arguments, "formula"),
        )
        request_payload = build_solve_request(
            query,
            spp_bundle_path or None,
            material_system=material_system,
            spp_guidance_weight=spp_guidance_weight,
            spp_regularisation_dir=spp_regularisation_dir or None,
            spp_regularisation_weight=spp_regularisation_weight,
        )
    except MaterialSystemError as exc:
        return _blocked("spp.package_for_qlip", exc.code, exc.message)
    request_path = step_dir / "qlip_request.json"
    _write_json(request_path, request_payload)

    artifact_refs = []
    if spp_bundle_path:
        artifact_refs.append({"ref_name": "spp_bundle_path", "value": spp_bundle_path, "kind": "directory"})
    package_json_path = _safe_string(result_payload, "package_json_path")
    if package_json_path:
        artifact_refs.append({"ref_name": "spp_package_json", "value": package_json_path, "kind": "file"})
    artifact_refs.append({"ref_name": "request_ref", "value": str(request_path), "kind": "file"})

    return _result(
        tool_name="spp.package_for_qlip",
        execution_performed=True,
        status="succeeded",
        output_summary={
            "request_ref": str(request_path),
            "spp_bundle_path": spp_bundle_path,
            "package_json_path": package_json_path,
            "material_system": material_system,
            "formula": material_system,
        },
        artifact_refs=artifact_refs,
        raw_result_ref=raw_ref,
        warnings=[json.dumps(item, sort_keys=True) for item in normalization_warnings],
    )


def _qlip_validate_request_adapter(
    step: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
    step_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    _ = prior_step_results
    request_ref = _safe_string(arguments, "request_ref")
    if not request_ref:
        return _blocked("qlip.validate_request", "missing_request_ref", "request_ref is required for qlip.validate_request.")
    request_path = Path(request_ref)
    if not request_path.exists():
        return _blocked("qlip.validate_request", "missing_request_path", f"request_ref path does not exist: {request_ref}")
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        validate_solve_request(request_payload, enforce_objective_guidance_contract=False)
    except QLIPValidationError as exc:
        return _blocked("qlip.validate_request", "invalid_request_ref", str(exc))

    try:
        response, raw_ref = _call_tool(
            "qlip.validate_request",
            {"request": request_payload},
            settings=settings,
            step_dir=step_dir,
            extra_env={
                "SOKLLM_RUN_DIR": str((step_dir / "qlip_run").resolve()),
                **_qlip_request_path_env(settings, request_payload),
            },
        )
    except MCPClientError as exc:
        return _failed(
            "qlip.validate_request",
            "mcp_call_failed",
            str(exc),
            execution_performed=False,
            raw_result_summary={"request_ref": str(request_path)},
        )

    payload = _unwrap_mcp_payload(response)
    if payload.get("ok") is False:
        primary_error = payload.get("primary_error") if isinstance(payload.get("primary_error"), Mapping) else {}
        return _failed(
            "qlip.validate_request",
            _safe_string(primary_error, "code", "validation_failed"),
            _safe_string(primary_error, "message", "qlip.validate_request rejected the request."),
            execution_performed=True,
            raw_result_ref=raw_ref,
            raw_result_summary={"ok": payload.get("ok")},
        )

    result_payload = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    validation_errors = [
        to_json_dict(item)
        for item in result_payload.get("errors", [])
        if isinstance(item, Mapping)
    ] if isinstance(result_payload.get("errors"), list) else []
    validation_warnings = [
        to_json_dict(item)
        for item in result_payload.get("warnings", [])
        if isinstance(item, Mapping)
    ] if isinstance(result_payload.get("warnings"), list) else []
    capabilities = (
        to_json_dict(result_payload.get("capabilities"))
        if isinstance(result_payload.get("capabilities"), Mapping)
        else {}
    )
    solve_ready_request = request_payload
    validated_request_written_kind = "original_request"
    for candidate_key in ("normalized_request", "validated_request", "request"):
        candidate = result_payload.get(candidate_key)
        if isinstance(candidate, Mapping):
            solve_ready_request = to_json_dict(candidate)
            validated_request_written_kind = candidate_key
            break
    validated_request_schema_check: dict[str, Any]
    try:
        validate_solve_request(solve_ready_request)
    except QLIPValidationError as exc:
        validated_request_schema_check = {"ok": False, "error": str(exc)}
    else:
        validated_request_schema_check = {"ok": True}
    validated_path = step_dir / "validated_request.json"
    _write_json(validated_path, solve_ready_request)
    return _result(
        tool_name="qlip.validate_request",
        execution_performed=True,
        status="succeeded",
        output_summary={
            "valid": result_payload.get("valid", True),
            "package_valid": result_payload.get("valid", True),
            "package_validation_status": (
                "invalid" if result_payload.get("valid", True) is False else "valid"
            ),
            "validation_errors": validation_errors,
            "validation_warnings": validation_warnings,
            "validation_error_codes": [
                _safe_string(item, "code")
                for item in validation_errors
                if isinstance(item, Mapping) and _safe_string(item, "code")
            ],
            "capabilities": capabilities,
            "validated_request_written_kind": validated_request_written_kind,
            "validated_request_schema_check": validated_request_schema_check,
            "solve_ready_request_ref": str(validated_path),
        },
        artifact_refs=[
            {"ref_name": "validated_request_ref", "value": str(validated_path), "kind": "file"},
            {"ref_name": "solve_ready_request_ref", "value": str(validated_path), "kind": "file"},
        ],
        raw_result_ref=raw_ref,
        raw_result_summary={"ok": payload.get("ok"), "valid": result_payload.get("valid", True)},
    )


def _qlip_solve_adapter(
    step: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
    step_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    _ = prior_step_results
    validated_request_ref = _safe_string(arguments, "validated_request_ref")
    if not validated_request_ref:
        return _blocked("qlip.solve", "missing_validated_request_ref", "validated_request_ref is required for qlip.solve.")
    request_path = Path(validated_request_ref)
    if not request_path.exists():
        return _blocked("qlip.solve", "missing_validated_request_path", f"validated_request_ref path does not exist: {validated_request_ref}")
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    if _truthy_env("QLIP_EXPORT_GUROBI_VISUALS"):
        request_payload.setdefault("runtime", {})["export_gurobi_visuals"] = True
        request_payload.setdefault("context", {})["gurobi_visuals_dir"] = str((step_dir / "gurobi_visuals").resolve())
    try:
        validate_solve_request(request_payload)
    except QLIPValidationError as exc:
        return _blocked("qlip.solve", "invalid_validated_request_ref", str(exc))

    try:
        response, raw_ref = _call_tool(
            "qlip.solve",
            {"request": request_payload},
            settings=settings,
            step_dir=step_dir,
            extra_env={
                "SOKLLM_RUN_DIR": str((step_dir / "qlip_run").resolve()),
                **_qlip_request_path_env(settings, request_payload),
            },
        )
    except MCPClientError as exc:
        return _failed(
            "qlip.solve",
            "mcp_call_failed",
            str(exc),
            execution_performed=False,
            raw_result_summary={"validated_request_ref": str(request_path)},
        )

    payload = _unwrap_mcp_payload(response)
    if payload.get("ok") is False:
        primary_error = payload.get("primary_error") if isinstance(payload.get("primary_error"), Mapping) else {}
        return _failed(
            "qlip.solve",
            _safe_string(primary_error, "code", "solve_failed"),
            _safe_string(primary_error, "message", "qlip.solve returned a non-ok response."),
            execution_performed=True,
            raw_result_ref=raw_ref,
            raw_result_summary={"ok": payload.get("ok")},
        )

    result_payload = payload.get("result") if isinstance(payload.get("result"), Mapping) else {}
    nested_result = result_payload.get("result") if isinstance(result_payload.get("result"), Mapping) else {}
    status = _safe_string(nested_result, "status", "unknown")
    if status.lower() not in {"optimal", "success"}:
        summary = nested_result.get("summary") if isinstance(nested_result.get("summary"), Mapping) else {}
        errors = [
            to_json_dict(item)
            for item in nested_result.get("errors", [])
            if isinstance(item, Mapping)
        ] if isinstance(nested_result.get("errors"), list) else []
        certificates = (
            to_json_dict(nested_result.get("certificates"))
            if isinstance(nested_result.get("certificates"), Mapping)
            else {}
        )
        diagnostics = certificates.get("diagnostics") if isinstance(certificates.get("diagnostics"), Mapping) else {}
        formula, pot_root, required_pairs, missing_pairs = _request_formula_and_pot(request_payload)
        return _result(
            tool_name="qlip.solve",
            execution_performed=True,
            status="failed",
            output_summary={
                "qlip_status": status,
                "qlip_error_codes": [
                    _safe_string(item, "code")
                    for item in errors
                    if isinstance(item, Mapping) and _safe_string(item, "code")
                ],
                "qlip_error_messages": [
                    _safe_string(item, "message")
                    for item in errors
                    if isinstance(item, Mapping) and _safe_string(item, "message")
                ],
                "formula": formula or None,
                "pot_root": pot_root or None,
                "required_pairs": required_pairs,
                "missing_pairs": missing_pairs,
                "raw_tool_response_path": raw_ref,
            },
            raw_result_ref=raw_ref,
            raw_result_summary={
                "status": status,
                "termination": summary.get("termination"),
                "infeasibility_category": diagnostics.get("infeasibility_category") if isinstance(diagnostics, Mapping) else None,
            },
            error={"code": "non_solution_status", "message": f"qlip.solve returned status={status}"},
            warnings=[
                json.dumps(
                    {
                        "qlip_status": status,
                        "errors": errors,
                        "diagnostics": diagnostics,
                    },
                    sort_keys=True,
                )
            ],
        )

    outputs = nested_result.get("outputs") if isinstance(nested_result.get("outputs"), Mapping) else {}
    output_artifacts = outputs.get("artifacts") if isinstance(outputs.get("artifacts"), list) else []
    gurobi_visual_artifacts: dict[str, str] = {}
    for item in output_artifacts:
        if not isinstance(item, Mapping):
            continue
        kind = _safe_string(item, "kind")
        data = _safe_string(item, "data")
        if kind and data and kind in {
            "constraint_matrix_meta_path",
            "constraint_matrix_spy_path",
            "mip_trace_csv_path",
            "mip_trace_json_path",
            "mip_trace_plot_path",
        }:
            gurobi_visual_artifacts[kind] = data
    certificates = nested_result.get("certificates") if isinstance(nested_result.get("certificates"), Mapping) else {}
    diagnostics = certificates.get("diagnostics") if isinstance(certificates.get("diagnostics"), Mapping) else {}
    gurobi_visuals = diagnostics.get("gurobi_visuals") if isinstance(diagnostics.get("gurobi_visuals"), Mapping) else {}
    for diag_key, artifact_key in (
        ("constraint_matrix_meta_path", "constraint_matrix_meta_path"),
        ("constraint_matrix_spy_path", "constraint_matrix_spy_path"),
        ("mip_trace_csv_path", "mip_trace_csv_path"),
        ("mip_trace_json_path", "mip_trace_json_path"),
        ("mip_trace_plot_path", "mip_trace_plot_path"),
    ):
        value = _safe_string(gurobi_visuals, diag_key)
        if value:
            gurobi_visual_artifacts.setdefault(artifact_key, value)

    cif_value = outputs.get("cif")
    solution_cif_path_original = cif_value if isinstance(cif_value, str) else None
    solution_cif_path_original_summary = (
        solution_cif_path_original
        if isinstance(solution_cif_path_original, str)
        and "\n" not in solution_cif_path_original
        and "\r" not in solution_cif_path_original
        else "<inline_cif_content>"
        if isinstance(solution_cif_path_original, str)
        else None
    )
    cif_path: str | None = None
    if isinstance(cif_value, str) and cif_value.strip():
        candidate_path = Path(cif_value)
        step_relative_candidate = step_dir / candidate_path
        if candidate_path.is_absolute() and candidate_path.exists():
            cif_path = str(candidate_path.resolve())
        elif not candidate_path.is_absolute() and step_relative_candidate.exists():
            cif_path = str(step_relative_candidate.resolve())
        elif "\n" not in cif_value and "\r" not in cif_value and not cif_value.lstrip().startswith("data_"):
            cif_path = None
        else:
            written_path = step_dir / "solution.cif"
            _write_text(written_path, cif_value)
            cif_path = str(written_path.resolve())
    if not cif_path:
        return _failed(
            "qlip.solve",
            "missing_solution_cif",
            "qlip.solve did not return a usable CIF artifact.",
            execution_performed=True,
            raw_result_ref=raw_ref,
            raw_result_summary={"status": status},
        )

    artifact_refs = [
        {"ref_name": "solution_cif_path_original", "value": solution_cif_path_original_summary, "kind": "text"}
        if solution_cif_path_original_summary and solution_cif_path_original_summary != "<inline_cif_content>"
        else {},
        {"ref_name": "solution_cif_path", "value": cif_path, "kind": "file"},
        {"ref_name": "candidate_cif_path", "value": cif_path, "kind": "file"},
    ]
    for ref_name, value in gurobi_visual_artifacts.items():
        artifact_refs.append({"ref_name": ref_name, "value": value, "kind": "file"})
    return _result(
        tool_name="qlip.solve",
        execution_performed=True,
        status="succeeded",
        output_summary={
            "status": status,
            "objective_value": nested_result.get("summary", {}).get("objective_value")
            if isinstance(nested_result.get("summary"), Mapping)
            else None,
            "solution_cif_path": cif_path,
            "solution_cif_path_original": solution_cif_path_original_summary,
            "solution_cif_exists": Path(cif_path).exists(),
            "gurobi_visuals": to_json_dict(gurobi_visuals) if gurobi_visuals else {},
            **gurobi_visual_artifacts,
        },
        artifact_refs=[item for item in artifact_refs if item],
        raw_result_ref=raw_ref,
    )


def _crystal_novelty_check_adapter(
    step: Mapping[str, Any],
    *,
    arguments: Mapping[str, Any],
    prior_step_results: list[Mapping[str, Any]],
    step_dir: Path,
    settings: Settings,
) -> dict[str, Any]:
    _ = step
    _ = arguments
    path_candidates = _artifact_ref_candidates(prior_step_results, ("solution_cif_path", "candidate_cif_path"))
    path_candidates = sorted(path_candidates, key=lambda item: 0 if item["ref_name"] == "solution_cif_path" else 1)
    if not path_candidates:
        return _blocked("crystal.novelty_check", "missing_candidate_artifact", "No prior candidate CIF artifact was available for novelty checking.")
    attempted_paths: list[str] = []
    selected_ref_name = ""
    candidate_path: Path | None = None
    for candidate in path_candidates:
        original_value = candidate["value"]
        raw_path = Path(original_value)
        resolved_options = [raw_path]
        if not raw_path.is_absolute():
            resolved_options.append((Path.cwd() / raw_path).resolve())
            resolved_options.append((step_dir / raw_path).resolve())
        for option in resolved_options:
            option_text = str(option)
            if option_text not in attempted_paths:
                attempted_paths.append(option_text)
            if option.exists():
                candidate_path = option.resolve()
                selected_ref_name = candidate["ref_name"]
                break
        if candidate_path is not None:
            break
    if candidate_path is None:
        return _result(
            tool_name="crystal.novelty_check",
            execution_performed=False,
            status="blocked",
            output_summary={
                "novelty_input_cif_path": None,
                "novelty_input_cif_exists": False,
                "solution_cif_path_candidates": path_candidates,
                "attempted_paths": attempted_paths,
                "cwd": str(Path.cwd()),
                "step_dir": str(step_dir),
            },
            error={
                "code": "solution_cif_path_missing",
                "message": (
                    "No existing solution CIF path was available for novelty checking. "
                    f"Original refs: {path_candidates}; attempted paths: {attempted_paths}; "
                    f"cwd: {Path.cwd()}; step_dir: {step_dir}"
                ),
            },
        )

    call_args, policy_notes = apply_crystal_policy_defaults({"cif_path": str(candidate_path)}, settings.crystaldb_policy_mode)
    try:
        response, raw_ref = _call_tool("crystal.novelty_check", call_args, settings=settings, step_dir=step_dir)
    except MCPClientError as exc:
        return _failed(
            "crystal.novelty_check",
            "mcp_call_failed",
            str(exc),
            execution_performed=False,
            raw_result_summary={"cif_path": str(candidate_path)},
            warnings=policy_notes,
        )

    payload = _unwrap_mcp_payload(response)
    novelty = payload.get("novelty") if isinstance(payload.get("novelty"), Mapping) else {}
    return _result(
        tool_name="crystal.novelty_check",
        execution_performed=True,
        status="succeeded",
        output_summary={
            "is_novel": novelty.get("is_novel"),
            "max_text_similarity": novelty.get("max_text_similarity"),
            "max_fp_similarity": novelty.get("max_fp_similarity"),
            "novelty_input_ref_name": selected_ref_name,
            "novelty_input_cif_path": str(candidate_path),
            "novelty_input_cif_exists": candidate_path.exists(),
        },
        artifact_refs=[],
        raw_result_ref=raw_ref,
        warnings=policy_notes,
    )


def get_default_tool_execution_adapters(settings: Settings | None = None) -> dict[str, Callable[..., dict[str, Any]]]:
    active_settings = settings or Settings.from_sources(None)

    def _bind(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        def _wrapped(
            step: Mapping[str, Any],
            *,
            arguments: Mapping[str, Any],
            prior_step_results: list[Mapping[str, Any]],
            step_dir: Path,
        ) -> dict[str, Any]:
            return func(
                step,
                arguments=arguments,
                prior_step_results=prior_step_results,
                step_dir=step_dir,
                settings=active_settings,
            )

        return _wrapped

    return {
        "crystal.csp_pack": _bind(_crystal_csp_pack_adapter),
        "spp.run_pipeline": _bind(_spp_run_pipeline_adapter),
        "spp.package_for_qlip": _bind(_spp_package_for_qlip_adapter),
        "qlip.validate_request": _bind(_qlip_validate_request_adapter),
        "qlip.solve": _bind(_qlip_solve_adapter),
        "crystal.novelty_check": _bind(_crystal_novelty_check_adapter),
    }


__all__ = [
    "TOOL_EXECUTION_RESULT_SCHEMA_VERSION",
    "get_default_tool_execution_adapters",
]
