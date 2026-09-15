from __future__ import annotations

import ast
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.crystaldb import CRYSTAL_TOOLS
from sok_llm_orchestrator.contracts.qlip_schema import QLIP_TOOLS
from sok_llm_orchestrator.contracts.spp_normalize import SPP_TOOLS
from sok_llm_orchestrator.mcp.stdio_client import MCPClientError, StdioMCPClient
from sok_llm_orchestrator.orchestrator.logging import canonical_json, sha256_text

REQUIRED_STARTUP_DEPENDENCIES = ("crystaldb", "spp", "qlip")

FAIL_CRYSTALDB_STARTUP = "CRYSTALDB_STARTUP_FAILED"
FAIL_CRYSTALDB_SEMANTIC = "CRYSTALDB_SEMANTIC_HEALTH_FAILED"
FAIL_CRYSTALDB_COLLAPSED = "CRYSTALDB_QUERY_INSENSITIVE_RETRIEVAL"
FAIL_CRYSTALDB_EMPTY = "CRYSTALDB_EMPTY_RETRIEVAL"
FAIL_CRYSTALDB_BACKEND_NOT_READY = "CRYSTALDB_BACKEND_NOT_READY"
FAIL_CRYSTALDB_QUERY_TOOL_MISMATCH = "CRYSTALDB_QUERY_TOOL_MISMATCH"
FAIL_SPP_STARTUP = "SPP_STARTUP_FAILED"
FAIL_SPP_SEMANTIC = "SPP_SEMANTIC_HEALTH_FAILED"
FAIL_QLIP_STARTUP = "QLIP_STARTUP_FAILED"
FAIL_QLIP_INVALID = "QLIP_INVALID_SOLUTION_ARTIFACT"
FAIL_QLIP_MISSING_ARTIFACT = "QLIP_MISSING_SOLUTION_ARTIFACT"
FAIL_QLIP_NON_SOLUTION = "QLIP_NON_SOLUTION_TERMINATION"
FAIL_QLIP_UNEXPECTED_CONTRACT = "QLIP_UNEXPECTED_RESPONSE_CONTRACT"
FAIL_QLIP_PLACEHOLDER = "QLIP_PLACEHOLDER_SOLUTION"
FAIL_QLIP_CONDITIONING = "QLIP_COMPOSITION_CONDITIONING_FAILED"
FAIL_QLIP_SEMANTIC = "QLIP_SEMANTIC_HEALTH_FAILED"
FAIL_QLIP_SHIM_PROVENANCE = "QLIP_SHIM_SERVER_PATH_BLOCKED"


def required_startup_dependencies() -> list[str]:
    return list(REQUIRED_STARTUP_DEPENDENCIES)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_log(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _result(
    *,
    dependency: str,
    command: str | list[str],
    startup_ok: bool,
    surface_ok: bool,
    semantic_ok: bool,
    failure_code: str | None = None,
    detail: str = "",
    probe: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "dependency": dependency,
        "command": command,
        "startup_ok": bool(startup_ok),
        "surface_ok": bool(surface_ok),
        "semantic_ok": bool(semantic_ok),
        "ok": bool(startup_ok and surface_ok and semantic_ok),
        "failure_code": failure_code,
        "detail": detail,
        "probe": probe if isinstance(probe, dict) else {},
        "provenance": provenance if isinstance(provenance, dict) else {},
    }


def _to_args(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return [str(item) for item in command]
    return shlex.split(command, posix=os.name != "nt")


def _resolve_module_origin(
    *,
    python_executable: str,
    module_name: str,
    cwd: str,
    env: dict[str, str],
) -> tuple[str | None, str | None]:
    payload = (
        "import importlib.util, json; "
        f"spec=importlib.util.find_spec('{module_name}'); "
        "print(json.dumps({'origin': (spec.origin if spec else None)}))"
    )
    try:
        proc = subprocess.run(
            [python_executable, "-c", payload],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout or f"exit={proc.returncode}").strip() or None
    try:
        decoded = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError:
        return None, "failed_to_decode_module_origin_json"
    origin = decoded.get("origin")
    if isinstance(origin, str) and origin.strip():
        return str(Path(origin).resolve()), None
    return None, None


def _build_provenance(
    *,
    dependency: str,
    command: str | list[str],
    cwd: str,
    env: dict[str, str],
) -> dict[str, Any]:
    try:
        argv = _to_args(command)
    except ValueError as exc:
        argv = []
        module_origin_error = f"command_parse_error={exc}"
    else:
        module_origin_error = None
    executable = shutil.which(argv[0]) if argv else None
    module_name: str | None = None
    module_origin: str | None = None
    script_path: str | None = None
    if len(argv) >= 3 and "-m" in argv[1:]:
        m_idx = argv.index("-m")
        if m_idx + 1 < len(argv):
            module_name = str(argv[m_idx + 1])
        if module_name is None:
            module_name = None
    if module_name is not None:
        module_origin, module_origin_error = _resolve_module_origin(
            python_executable=argv[0],
            module_name=module_name,
            cwd=cwd,
            env=env,
        )
    else:
        for token in argv[1:]:
            if token.startswith("-"):
                continue
            if token.lower().endswith(".py"):
                script_path = str(Path(token).resolve())
            break
    repo_root = _repo_root()
    qlip_shim_path = (repo_root / "src" / "qlip_mcp" / "server.py").resolve()
    is_repo_qlip_shim = bool(
        dependency == "qlip"
        and module_name == "qlip_mcp.server"
        and module_origin is not None
        and Path(module_origin).resolve() == qlip_shim_path
    )
    return {
        "connection_mode": "launched_stdio_subprocess",
        "attached": False,
        "requested_command": command,
        "resolved_argv": argv,
        "launch_cwd": cwd,
        "resolved_executable": executable,
        "module_name": module_name,
        "module_origin": module_origin,
        "module_origin_error": module_origin_error,
        "script_path": script_path,
        "repo_root": str(repo_root),
        "is_repo_qlip_shim": bool(is_repo_qlip_shim),
        "python_executable": sys.executable,
    }


def _result_payload(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    result = response.get("result", response)
    if not isinstance(result, dict):
        return {}
    if any(
        key in result
        for key in (
            "neighbors",
            "errors",
            "status",
            "backend_status",
            "query",
            "run_id",
            "ready",
            "state",
        )
    ):
        return result
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "json" and isinstance(item.get("json"), dict):
                return item["json"]
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text = item["text"].strip()
                if text.startswith("{") and text.endswith("}"):
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        return parsed
    return result


def _extract_neighbors(response: dict[str, Any]) -> list[dict[str, Any]]:
    neighbors = _result_payload(response).get("neighbors", [])
    return [item for item in neighbors if isinstance(item, dict)] if isinstance(neighbors, list) else []


def _extract_crystal_errors(response: dict[str, Any]) -> dict[str, Any] | None:
    errors = _result_payload(response).get("errors")
    if isinstance(errors, dict):
        return errors
    return None


def _extract_error_code(error_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(error_payload, dict):
        return None
    code = error_payload.get("code")
    if isinstance(code, str) and code.strip():
        return code.strip()
    return None


def _extract_status(response: dict[str, Any]) -> str | None:
    payload = _result_payload(response)
    value = payload.get("status")
    if isinstance(value, str) and value.strip():
        return value.strip()
    ready = payload.get("ready")
    if isinstance(ready, bool):
        return "ok" if ready else "backend_not_ready"
    return None


def _extract_backend_status(response: dict[str, Any]) -> dict[str, Any] | None:
    payload = _result_payload(response)
    backend_status = payload.get("backend_status")
    if isinstance(backend_status, dict):
        return backend_status
    if any(key in payload for key in ("ready", "state", "db_path", "schema_present", "corpus", "requested_space")):
        return payload
    return None


def _extract_backend_state(response: dict[str, Any]) -> str | None:
    backend_status = _extract_backend_status(response)
    if not isinstance(backend_status, dict):
        return None
    state = backend_status.get("state")
    if isinstance(state, str) and state.strip():
        return state.strip().lower()
    return None


def _extract_backend_counts(response: dict[str, Any]) -> dict[str, Any]:
    backend_status = _extract_backend_status(response)
    if not isinstance(backend_status, dict):
        return {}
    counts: dict[str, Any] = {}
    for key in (
        "candidate_count",
        "corpus_size",
        "embedding_space_count",
        "embedding_count",
        "fingerprint_count",
        "index_count",
    ):
        if key in backend_status:
            counts[key] = backend_status.get(key)
    corpus = backend_status.get("corpus")
    if isinstance(corpus, dict):
        for key in ("structure_count", "metadata_count", "text_doc_count", "text_doc_ok_count"):
            if key in corpus:
                counts[f"corpus_{key}"] = corpus.get(key)
    requested_space = backend_status.get("requested_space")
    if isinstance(requested_space, dict):
        for key in ("embedding_row_count", "text_doc_count", "text_doc_ok_count", "distinct_structure_count"):
            if key in requested_space:
                counts[f"requested_space_{key}"] = requested_space.get(key)
    return counts


def _parse_mcp_error(exc: MCPClientError) -> dict[str, Any]:
    raw = str(exc).strip()
    if not raw:
        return {"message": "unknown_mcp_error"}
    parsed: dict[str, Any] | None = None
    try:
        decoded = json.loads(raw)
        if isinstance(decoded, dict):
            parsed = decoded
    except json.JSONDecodeError:
        parsed = None
    if parsed is None:
        try:
            decoded = ast.literal_eval(raw)
            if isinstance(decoded, dict):
                parsed = decoded
        except (ValueError, SyntaxError):
            parsed = None
    if parsed is None:
        return {"message": raw}
    return parsed


def _extract_payload_from_mcp_error(error_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(error_payload, dict):
        return None
    data = error_payload.get("data")
    if isinstance(data, dict):
        payload = data.get("payload")
        if isinstance(payload, dict):
            return payload
    payload = error_payload.get("payload")
    if isinstance(payload, dict):
        return payload
    return None


def _compose_probe_response(response: dict[str, Any], mcp_error: dict[str, Any] | None) -> dict[str, Any]:
    payload = _extract_payload_from_mcp_error(mcp_error)
    if isinstance(payload, dict):
        return {"result": payload}
    return response if isinstance(response, dict) else {}


def _collect_error_codes(*, probe_response: dict[str, Any], mcp_error: dict[str, Any] | None) -> set[str]:
    codes: set[str] = set()
    non_error_markers = {"ok", "ready", "healthy"}
    code = _extract_error_code(_extract_crystal_errors(probe_response))
    if isinstance(code, str) and code.strip().lower() not in non_error_markers:
        codes.add(code)
    backend_status = _extract_backend_status(probe_response)
    if isinstance(backend_status, dict):
        for key in ("code", "error_code", "reason_code"):
            value = backend_status.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() not in non_error_markers:
                codes.add(value.strip())
    if isinstance(mcp_error, dict):
        for key in ("code", "error_code"):
            value = mcp_error.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() not in non_error_markers:
                codes.add(value.strip())
        payload = _extract_payload_from_mcp_error(mcp_error)
        if isinstance(payload, dict):
            payload_code = _extract_error_code(_extract_crystal_errors({"result": payload}))
            if isinstance(payload_code, str) and payload_code.strip().lower() not in non_error_markers:
                codes.add(payload_code)
    return codes


def _is_backend_not_ready_signal(*, state: str | None, status: str | None, codes: set[str]) -> bool:
    backend_not_ready_codes = {
        "backend_not_ready",
        "missing_db",
        "db_schema_missing",
        "missing_embedding_space",
        "embedding_space_missing",
        "missing_fingerprint_index",
        "missing_index",
        "index_missing",
        "candidate_set_empty",
        "empty_corpus",
    }
    if any(code in backend_not_ready_codes for code in codes):
        return True
    state_value = (state or "").strip().lower()
    status_value = (status or "").strip().lower()
    if state_value in {"not_ready", "initializing", "error", "degraded", "missing"}:
        return True
    if status_value in {"backend_not_ready", "not_ready", "error"}:
        return True
    return False


def _neighbor_signature(neighbors: list[dict[str, Any]]) -> str:
    compact = []
    for item in neighbors:
        compact.append(
            {
                "structure_id": item.get("structure_id"),
                "score": item.get("score"),
                "rank": item.get("rank"),
            }
        )
    return sha256_text(canonical_json(compact))


def _probe_crystaldb_semantic(
    client: StdioMCPClient,
    *,
    log_lines: list[str],
    startup_dir: Path,
    provenance: dict[str, Any],
    available_tools: set[str],
) -> tuple[bool, str | None, str, dict[str, Any]]:
    query_a = "TiO2 rutile startup semantic probe"
    query_b = "BaTiO3 perovskite startup semantic probe"
    status_probe: dict[str, Any] = {}
    status_probe_error: dict[str, Any] | None = None
    if "crystal.status" in available_tools:
        try:
            status_probe = client.call_tool("crystal.status", {})
        except MCPClientError as exc:
            status_probe_error = _parse_mcp_error(exc)
    resp_a: dict[str, Any] = {}
    resp_b: dict[str, Any] = {}
    call_error_a: dict[str, Any] | None = None
    call_error_b: dict[str, Any] | None = None
    try:
        resp_a = client.call_tool("crystal.text_search", {"query": query_a, "k": 3})
    except MCPClientError as exc:
        call_error_a = _parse_mcp_error(exc)
    try:
        resp_b = client.call_tool("crystal.text_search", {"query": query_b, "k": 3})
    except MCPClientError as exc:
        call_error_b = _parse_mcp_error(exc)
    probe_resp_a = _compose_probe_response(resp_a, call_error_a)
    probe_resp_b = _compose_probe_response(resp_b, call_error_b)
    err_a = _extract_crystal_errors(probe_resp_a)
    err_b = _extract_crystal_errors(probe_resp_b)
    n_a = _extract_neighbors(probe_resp_a)
    n_b = _extract_neighbors(probe_resp_b)
    status_a = _extract_status(probe_resp_a)
    status_b = _extract_status(probe_resp_b)
    backend_a = _extract_backend_status(probe_resp_a)
    backend_b = _extract_backend_status(probe_resp_b)
    backend_state_a = _extract_backend_state(probe_resp_a)
    backend_state_b = _extract_backend_state(probe_resp_b)
    ids_a = [str(item.get("structure_id")) for item in n_a if isinstance(item.get("structure_id"), str)]
    ids_b = [str(item.get("structure_id")) for item in n_b if isinstance(item.get("structure_id"), str)]
    sig_a = _neighbor_signature(n_a)
    sig_b = _neighbor_signature(n_b)
    pack_root = startup_dir / "probe_outputs" / "crystaldb"
    pack_a: dict[str, Any] = {}
    pack_b: dict[str, Any] = {}
    call_error_pack_a: dict[str, Any] | None = None
    call_error_pack_b: dict[str, Any] | None = None
    try:
        pack_a = client.call_tool(
            "crystal.csp_pack",
            {"query": query_a, "out_dir": str(pack_root / "pack_a"), "export_top": 1},
        )
    except MCPClientError as exc:
        call_error_pack_a = _parse_mcp_error(exc)
    try:
        pack_b = client.call_tool(
            "crystal.csp_pack",
            {"query": query_b, "out_dir": str(pack_root / "pack_b"), "export_top": 1},
        )
    except MCPClientError as exc:
        call_error_pack_b = _parse_mcp_error(exc)
    probe_pack_a = _compose_probe_response(pack_a, call_error_pack_a)
    probe_pack_b = _compose_probe_response(pack_b, call_error_pack_b)
    err_pack_a = _extract_crystal_errors(probe_pack_a)
    err_pack_b = _extract_crystal_errors(probe_pack_b)
    p_a = _extract_neighbors(probe_pack_a)
    p_b = _extract_neighbors(probe_pack_b)
    pack_status_a = _extract_status(probe_pack_a)
    pack_status_b = _extract_status(probe_pack_b)
    pack_backend_a = _extract_backend_status(probe_pack_a)
    pack_backend_b = _extract_backend_status(probe_pack_b)
    pack_backend_state_a = _extract_backend_state(probe_pack_a)
    pack_backend_state_b = _extract_backend_state(probe_pack_b)
    p_ids_a = [str(item.get("structure_id")) for item in p_a if isinstance(item.get("structure_id"), str)]
    p_ids_b = [str(item.get("structure_id")) for item in p_b if isinstance(item.get("structure_id"), str)]
    p_sig_a = _neighbor_signature(p_a)
    p_sig_b = _neighbor_signature(p_b)
    status_probe_response = _compose_probe_response(status_probe, status_probe_error)
    crystal_status = _extract_status(status_probe_response)
    crystal_backend_status = _extract_backend_status(status_probe_response)
    crystal_backend_state = _extract_backend_state(status_probe_response)

    codes: set[str] = set()
    codes.update(_collect_error_codes(probe_response=probe_resp_a, mcp_error=call_error_a))
    codes.update(_collect_error_codes(probe_response=probe_resp_b, mcp_error=call_error_b))
    codes.update(_collect_error_codes(probe_response=probe_pack_a, mcp_error=call_error_pack_a))
    codes.update(_collect_error_codes(probe_response=probe_pack_b, mcp_error=call_error_pack_b))
    if "crystal.status" in available_tools:
        codes.update(_collect_error_codes(probe_response=status_probe_response, mcp_error=status_probe_error))
    error_codes = sorted(codes)

    all_backend_states = [
        state
        for state in (
            crystal_backend_state,
            backend_state_a,
            backend_state_b,
            pack_backend_state_a,
            pack_backend_state_b,
        )
        if isinstance(state, str)
    ]
    all_status_values = [
        status
        for status in (
            crystal_status,
            status_a,
            status_b,
            pack_status_a,
            pack_status_b,
        )
        if isinstance(status, str)
    ]
    backend_not_ready = any(
        _is_backend_not_ready_signal(state=state, status=None, codes=codes) for state in all_backend_states
    ) or any(_is_backend_not_ready_signal(state=None, status=status, codes=codes) for status in all_status_values)

    probe = {
        "query_a": query_a,
        "query_b": query_b,
        "status_tool_available": bool("crystal.status" in available_tools),
        "status_tool_response_status": crystal_status,
        "status_tool_backend_state": crystal_backend_state,
        "status_tool_backend_status": crystal_backend_status,
        "status_tool_error": status_probe_error,
        "neighbor_count_a": len(n_a),
        "neighbor_count_b": len(n_b),
        "candidate_ids_a": ids_a,
        "candidate_ids_b": ids_b,
        "candidate_signature_a": sig_a,
        "candidate_signature_b": sig_b,
        "status_a": status_a,
        "status_b": status_b,
        "backend_state_a": backend_state_a,
        "backend_state_b": backend_state_b,
        "backend_status_a": backend_a,
        "backend_status_b": backend_b,
        "pack_neighbor_count_a": len(p_a),
        "pack_neighbor_count_b": len(p_b),
        "pack_candidate_ids_a": p_ids_a,
        "pack_candidate_ids_b": p_ids_b,
        "pack_candidate_signature_a": p_sig_a,
        "pack_candidate_signature_b": p_sig_b,
        "pack_status_a": pack_status_a,
        "pack_status_b": pack_status_b,
        "pack_backend_state_a": pack_backend_state_a,
        "pack_backend_state_b": pack_backend_state_b,
        "pack_backend_status_a": pack_backend_a,
        "pack_backend_status_b": pack_backend_b,
        "backend_counts_a": _extract_backend_counts(probe_resp_a),
        "backend_counts_b": _extract_backend_counts(probe_resp_b),
        "pack_backend_counts_a": _extract_backend_counts(probe_pack_a),
        "pack_backend_counts_b": _extract_backend_counts(probe_pack_b),
        "status_backend_counts": _extract_backend_counts(status_probe_response),
        "tool_errors_a": err_a,
        "tool_errors_b": err_b,
        "pack_tool_errors_a": err_pack_a,
        "pack_tool_errors_b": err_pack_b,
        "transport_error_a": call_error_a,
        "transport_error_b": call_error_b,
        "pack_transport_error_a": call_error_pack_a,
        "pack_transport_error_b": call_error_pack_b,
        "likely_local_shim": bool(
            isinstance(provenance.get("module_origin"), str)
            and str(provenance.get("module_origin", "")).lower().endswith("skill-loop-csp\\src\\crystaldb_mcp\\server.py")
        ),
    }
    log_lines.append(f"semantic_probe crystaldb ids_a={ids_a}")
    log_lines.append(f"semantic_probe crystaldb ids_b={ids_b}")
    log_lines.append(f"semantic_probe crystaldb sig_a={sig_a}")
    log_lines.append(f"semantic_probe crystaldb sig_b={sig_b}")
    log_lines.append(f"semantic_probe crystaldb pack_ids_a={p_ids_a}")
    log_lines.append(f"semantic_probe crystaldb pack_ids_b={p_ids_b}")
    log_lines.append(f"semantic_probe crystaldb status={crystal_status}")
    log_lines.append(f"semantic_probe crystaldb backend_state={crystal_backend_state}")
    probe["error_codes"] = error_codes
    if backend_not_ready:
        detail = "crystaldb backend not ready for startup retrieval"
        if error_codes:
            detail = f"{detail}: error_codes={error_codes}"
        if crystal_backend_state:
            detail = f"{detail}; backend_state={crystal_backend_state}"
        return (
            False,
            FAIL_CRYSTALDB_BACKEND_NOT_READY,
            detail,
            probe,
        )
    mismatch_codes = {"invalid_input", "query_tool_mismatch", "unsupported_query_mode", "tool_contract_mismatch"}
    if any(code in mismatch_codes for code in error_codes):
        return (
            False,
            FAIL_CRYSTALDB_QUERY_TOOL_MISMATCH,
            f"startup probe detected crystaldb query/tool mismatch: error_codes={error_codes}",
            probe,
        )
    if error_codes:
        return (
            False,
            FAIL_CRYSTALDB_SEMANTIC,
            "crystaldb startup probe returned tool-level errors",
            probe,
        )
    has_any_a = bool(n_a or p_a)
    has_any_b = bool(n_b or p_b)
    if not has_any_a and not has_any_b:
        return (
            False,
            FAIL_CRYSTALDB_EMPTY,
            "both startup probe queries returned empty retrieval across text_search and csp_pack",
            probe,
        )
    if not has_any_a or not has_any_b:
        return (
            False,
            FAIL_CRYSTALDB_EMPTY,
            "one startup probe query returned empty retrieval across text_search and csp_pack",
            probe,
        )
    has_text = bool(n_a or n_b)
    has_pack = bool(p_a or p_b)
    if has_text != has_pack:
        return (
            False,
            FAIL_CRYSTALDB_QUERY_TOOL_MISMATCH,
            "startup probe saw asymmetric retrieval across text_search vs csp_pack with no backend-not-ready signal",
            probe,
        )
    distinct_text = set(ids_a) != set(ids_b) or sig_a != sig_b
    distinct_pack = set(p_ids_a) != set(p_ids_b) or p_sig_a != p_sig_b
    if not (distinct_text or distinct_pack):
        detail = "startup probe observed query-insensitive retrieval (text_search and csp_pack signatures identical)"
        if bool(probe["likely_local_shim"]):
            detail = (
                detail
                + "; resolved module origin points to local Skill-Loop-CSP crystaldb shim, "
                + "not external Crystal-DB MCP server"
            )
        return (
            False,
            FAIL_CRYSTALDB_COLLAPSED,
            detail,
            probe,
        )
    return True, None, "ok", probe


def _unwrap_spp_response(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    if "result" in response and isinstance(response["result"], dict):
        if response.get("ok", True) is False:
            return {}
        return dict(response["result"])
    return dict(response)


def _write_probe_cifs(root: Path, prefix: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for idx in range(2):
        (root / f"{prefix}_{idx+1}.cif").write_text(
            "\n".join(
                [
                    f"data_{prefix}_{idx+1}",
                    f"_chemical_formula_sum '{'TiO2' if prefix == 'a' else 'BaTiO3'}'",
                    f"_cell_length_a {4.0 + idx:.4f}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    return root


def _path_signature(path: str | None) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    p = Path(path)
    if p.exists() and p.is_file():
        return sha256_text(p.read_text(encoding="utf-8", errors="ignore"))
    return sha256_text(path)


def _probe_spp_semantic(client: StdioMCPClient, *, startup_dir: Path, log_lines: list[str]) -> tuple[bool, str | None, str, dict[str, Any]]:
    probe_root = startup_dir / "probe_inputs" / "spp"
    cifs_a = _write_probe_cifs(probe_root / "corpus_a", "a")
    cifs_b = _write_probe_cifs(probe_root / "corpus_b", "b")
    out_root = startup_dir / "probe_outputs" / "spp"
    run_a = _unwrap_spp_response(
        client.call_tool(
            "spp.run_pipeline",
            {"cif_dir": str(cifs_a), "out_dir": str(out_root / "run_a"), "name": "startup_probe_a", "target": 0.85},
        )
    )
    run_b = _unwrap_spp_response(
        client.call_tool(
            "spp.run_pipeline",
            {"cif_dir": str(cifs_b), "out_dir": str(out_root / "run_b"), "name": "startup_probe_b", "target": 0.95},
        )
    )
    pkg_a = _unwrap_spp_response(
        client.call_tool(
            "spp.package_for_qlip",
            {"run_root": str(run_a.get("run_root")), "out_dir": str(out_root / "pkg_a"), "name": "startup_pkg_a"},
        )
    )
    pkg_b = _unwrap_spp_response(
        client.call_tool(
            "spp.package_for_qlip",
            {"run_root": str(run_b.get("run_root")), "out_dir": str(out_root / "pkg_b"), "name": "startup_pkg_b"},
        )
    )
    path_a = str(pkg_a.get("final_bundle_path")) if isinstance(pkg_a.get("final_bundle_path"), str) else None
    path_b = str(pkg_b.get("final_bundle_path")) if isinstance(pkg_b.get("final_bundle_path"), str) else None
    package_json_a = str(pkg_a.get("package_json_path")) if isinstance(pkg_a.get("package_json_path"), str) else None
    package_json_b = str(pkg_b.get("package_json_path")) if isinstance(pkg_b.get("package_json_path"), str) else None
    sig_a = _path_signature(package_json_a)
    sig_b = _path_signature(package_json_b)
    probe = {
        "run_root_a": run_a.get("run_root"),
        "run_root_b": run_b.get("run_root"),
        "package_path_a": path_a,
        "package_path_b": path_b,
        "package_json_a": package_json_a,
        "package_json_b": package_json_b,
        "package_signature_a": sig_a,
        "package_signature_b": sig_b,
    }
    log_lines.append(f"semantic_probe spp package_path_a={path_a}")
    log_lines.append(f"semantic_probe spp package_path_b={path_b}")
    if not path_a or not path_b or not Path(path_a).exists() or not Path(path_b).exists():
        return False, FAIL_SPP_SEMANTIC, "spp package generation did not produce bundle paths", probe
    if not package_json_a or not package_json_b or not Path(package_json_a).exists() or not Path(package_json_b).exists():
        return False, FAIL_SPP_SEMANTIC, "spp package metadata json missing", probe
    if sig_a == sig_b:
        return False, FAIL_SPP_SEMANTIC, "distinct corpus probes produced identical package signatures", probe
    return True, None, "ok", probe


def _probe_qlip_requests() -> tuple[dict[str, Any], dict[str, Any]]:
    base_a = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "TiO2"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 4.6,
                        "b": 4.6,
                        "c": 3.0,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {
                    "mode": "uniform_grid",
                    "uniform_grid": {"density": 4},
                },
            },
        },
        "constraints": [
            {
                "id": "proximity.atomic_radii",
                "params": {
                    "scale": 1.0,
                    "allow_self_overlap": False,
                },
            }
        ],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }
    base_b = json.loads(json.dumps(base_a))
    base_b["problem"]["chemistry"]["formula"] = "BaTiO3"
    lattice_b = base_b["problem"]["design_space"]["template"]["lattice"]
    if isinstance(lattice_b, dict):
        lattice_b["a"] = 4.0
        lattice_b["b"] = 4.0
        lattice_b["c"] = 4.1
    sites_b = base_b["problem"]["design_space"]["sites"]
    if isinstance(sites_b, dict) and isinstance(sites_b.get("uniform_grid"), dict):
        sites_b["uniform_grid"]["density"] = 5
    return base_a, base_b


def _fallback_probe_request(req_a: dict[str, Any]) -> dict[str, Any]:
    fallback = json.loads(json.dumps(req_a))
    chemistry = fallback.get("problem", {}).get("chemistry")
    if isinstance(chemistry, dict) and isinstance(chemistry.get("formula"), str):
        chemistry["formula"] = "TiO2"
    lattice = fallback.get("problem", {}).get("design_space", {}).get("template", {}).get("lattice")
    if isinstance(lattice, dict):
        lattice["a"] = 5.2
        lattice["b"] = 5.0
        lattice["c"] = 3.4
    uniform = fallback.get("problem", {}).get("design_space", {}).get("sites", {}).get("uniform_grid")
    if isinstance(uniform, dict):
        uniform["density"] = 5
    return fallback


def _extract_qlip_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if any(key in payload for key in ("ok", "tool", "result", "errors", "primary_error", "meta")):
        return payload
    unwrapped = _result_payload(payload)
    if isinstance(unwrapped, dict) and any(
        key in unwrapped for key in ("ok", "tool", "result", "errors", "primary_error", "meta")
    ):
        return unwrapped
    return {}


def _extract_qlip_solve_result(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    result = envelope.get("result")
    if not isinstance(result, dict):
        return {}
    nested = result.get("result")
    if isinstance(nested, dict):
        return nested
    return result


def _extract_qlip_artifact(payload: dict[str, Any]) -> tuple[str | None, str | None, str | None, dict[str, Any]]:
    envelope = _extract_qlip_envelope(payload)
    solve_result = _extract_qlip_solve_result(envelope)
    if not envelope:
        return None, None, None, {}
    path_candidates: list[str] = []
    inline_candidates: list[str] = []
    for value in (
        envelope.get("cif_path"),
        solve_result.get("cif_path"),
    ):
        if isinstance(value, str) and value.strip():
            path_candidates.append(value.strip())
    outputs = solve_result.get("outputs")
    if isinstance(outputs, dict):
        cif_path = outputs.get("cif_path")
        if isinstance(cif_path, str) and cif_path.strip():
            path_candidates.append(cif_path.strip())
        cif = outputs.get("cif")
        if isinstance(cif, str) and cif.strip():
            normalized = cif.strip()
            if "\n" in normalized or "\r" in normalized or normalized.lower().startswith("data_"):
                inline_candidates.append(normalized)
            else:
                path_candidates.append(normalized)
    path = path_candidates[0] if path_candidates else None
    inline = inline_candidates[0] if inline_candidates else None
    source = "inline" if inline is not None else ("path" if path is not None else None)
    return source, path, inline, envelope


def _extract_qlip_status_and_errors(payload: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]], bool | None]:
    envelope = _extract_qlip_envelope(payload)
    if not envelope:
        return None, [], None
    solve_result = _extract_qlip_solve_result(envelope)
    summary = solve_result.get("summary") if isinstance(solve_result.get("summary"), dict) else {}
    status = solve_result.get("status")
    if isinstance(summary, dict) and isinstance(summary.get("termination"), str):
        status = str(summary.get("termination"))
    errors = envelope.get("errors")
    if not isinstance(errors, list):
        errors = solve_result.get("errors")
    items = [e for e in errors if isinstance(e, dict)] if isinstance(errors, list) else []
    ok_flag = envelope.get("ok")
    ok_value = bool(ok_flag) if isinstance(ok_flag, bool) else None
    return (str(status) if isinstance(status, str) else None), items, ok_value


def _cif_integrity_check(content: str) -> tuple[bool, str | None, str]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    meaningful_lines = [line for line in lines if not line.startswith("#")]
    if not meaningful_lines:
        return False, FAIL_QLIP_INVALID, "solution.cif is empty"
    if len(meaningful_lines) == 1 and meaningful_lines[0] == "data_solution":
        return False, FAIL_QLIP_PLACEHOLDER, "solution.cif content is placeholder 'data_solution'"
    if not meaningful_lines[0].lower().startswith("data_"):
        return False, FAIL_QLIP_INVALID, "solution.cif missing data_ header"
    if not any(line.startswith("_") for line in meaningful_lines[1:]):
        return False, FAIL_QLIP_INVALID, "solution.cif missing CIF fields beyond data_ header"
    return True, None, "ok"


def _probe_qlip_semantic(
    client: StdioMCPClient,
    *,
    log_lines: list[str],
    mode: str = "stub",
) -> tuple[bool, str | None, str, dict[str, Any]]:
    req_a, req_b = _probe_qlip_requests()
    req_sig_a = sha256_text(canonical_json(req_a))
    req_sig_b = sha256_text(canonical_json(req_b))
    if req_sig_a == req_sig_b:
        return False, FAIL_QLIP_CONDITIONING, "startup probe requests collapsed to same signature", {}

    shapes = client.call_tool("qlip.shapes", {})
    shapes_env = _extract_qlip_envelope(shapes)
    shapes_tools = None
    if isinstance(shapes_env.get("result"), dict):
        shapes_tools = shapes_env.get("result", {}).get("tools")
    shapes_meta = shapes_env.get("meta") if isinstance(shapes_env.get("meta"), dict) else {}

    validate_a = client.call_tool("qlip.validate_request", {"request": req_a})
    validate_b = client.call_tool("qlip.validate_request", {"request": req_b})
    validate_a_env = _extract_qlip_envelope(validate_a)
    validate_b_env = _extract_qlip_envelope(validate_b)
    validate_a_result = validate_a_env.get("result") if isinstance(validate_a_env.get("result"), dict) else {}
    validate_b_result = validate_b_env.get("result") if isinstance(validate_b_env.get("result"), dict) else {}
    validate_a_ok = bool(validate_a_env.get("ok")) if isinstance(validate_a_env.get("ok"), bool) else None
    validate_b_ok = bool(validate_b_env.get("ok")) if isinstance(validate_b_env.get("ok"), bool) else None
    validate_a_valid = bool(validate_a_result.get("valid")) if isinstance(validate_a_result.get("valid"), bool) else None
    validate_b_valid = bool(validate_b_result.get("valid")) if isinstance(validate_b_result.get("valid"), bool) else None
    validate_result_errors_a = validate_a_result.get("errors") if isinstance(validate_a_result.get("errors"), list) else []
    validate_result_errors_b = validate_b_result.get("errors") if isinstance(validate_b_result.get("errors"), list) else []
    if validate_a_valid is True and validate_b_valid is False:
        req_b_fallback = _fallback_probe_request(req_a)
        req_sig_b = sha256_text(canonical_json(req_b_fallback))
        validate_b = client.call_tool("qlip.validate_request", {"request": req_b_fallback})
        validate_b_env = _extract_qlip_envelope(validate_b)
        validate_b_result = validate_b_env.get("result") if isinstance(validate_b_env.get("result"), dict) else {}
        validate_b_ok = bool(validate_b_env.get("ok")) if isinstance(validate_b_env.get("ok"), bool) else None
        validate_b_valid = bool(validate_b_result.get("valid")) if isinstance(validate_b_result.get("valid"), bool) else None
        validate_result_errors_b = (
            validate_b_result.get("errors") if isinstance(validate_b_result.get("errors"), list) else []
        )
        if validate_b_valid is True:
            req_b = req_b_fallback
    if not validate_a_env or not validate_b_env:
        return False, FAIL_QLIP_UNEXPECTED_CONTRACT, "qlip.validate_request returned unexpected response contract", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "validate_response_contract_a": bool(validate_a_env),
            "validate_response_contract_b": bool(validate_b_env),
        }
    if (validate_a_ok is False or validate_b_ok is False) or (validate_a_valid is False or validate_b_valid is False):
        return False, FAIL_QLIP_UNEXPECTED_CONTRACT, "startup probe requests rejected by qlip.validate_request", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "validate_ok_a": validate_a_ok,
            "validate_ok_b": validate_b_ok,
            "validate_valid_a": validate_a_valid,
            "validate_valid_b": validate_b_valid,
            "validate_errors_a": validate_a_env.get("errors"),
            "validate_errors_b": validate_b_env.get("errors"),
            "validate_result_errors_a": validate_result_errors_a,
            "validate_result_errors_b": validate_result_errors_b,
        }

    solve_a = client.call_tool("qlip.solve", {"request": req_a})
    source_a, cif_a, inline_a, solve_a_env = _extract_qlip_artifact(solve_a)
    status_a, errors_a, solve_ok_a = _extract_qlip_status_and_errors(solve_a)
    if not solve_a_env:
        return False, FAIL_QLIP_UNEXPECTED_CONTRACT, "qlip.solve returned unexpected response contract for probe A", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
        }
    if solve_ok_a is False:
        return False, FAIL_QLIP_NON_SOLUTION, "qlip.solve failed before producing a solution for probe A", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "status_a": status_a,
            "errors_a": errors_a,
        }
    if isinstance(status_a, str) and status_a.strip().lower() not in {"optimal", "success"}:
        return False, FAIL_QLIP_NON_SOLUTION, f"qlip.solve non-solution termination for probe A: {status_a}", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "status_a": status_a,
            "errors_a": errors_a,
        }
    if source_a is None:
        return False, FAIL_QLIP_MISSING_ARTIFACT, "qlip.solve did not return CIF artifact for probe A", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "status_a": status_a,
            "errors_a": errors_a,
        }
    if source_a == "path" and cif_a is not None:
        path_a = Path(cif_a)
        if not path_a.exists():
            return False, FAIL_QLIP_MISSING_ARTIFACT, "qlip.solve referenced missing solution artifact path for probe A", {
                "request_signature_a": req_sig_a,
                "request_signature_b": req_sig_b,
                "cif_path_a": cif_a,
                "cif_exists_a": False,
                "status_a": status_a,
                "errors_a": errors_a,
            }
        content_a = path_a.read_text(encoding="utf-8", errors="ignore")
    elif source_a == "inline" and inline_a is not None:
        content_a = inline_a
    else:
        return False, FAIL_QLIP_UNEXPECTED_CONTRACT, "qlip.solve returned unsupported CIF artifact shape for probe A", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "status_a": status_a,
            "errors_a": errors_a,
        }
    ok_a, code_a, detail_a = _cif_integrity_check(content_a)
    if not ok_a:
        return False, code_a, detail_a, {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_exists_a": bool(source_a == "inline" or (isinstance(cif_a, str) and Path(cif_a).exists())),
            "cif_signature_a": sha256_text(content_a.strip()),
            "status_a": status_a,
            "errors_a": errors_a,
        }
    if mode == "live":
        probe_live: dict[str, Any] = {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "single_solve_probe_mode": "live_single_solve",
            "server_marker_payload_sha256": (
                shapes_env.get("payload_sha256")
                if isinstance(shapes_env.get("payload_sha256"), str)
                else (shapes_meta.get("payload_sha256") if isinstance(shapes_meta.get("payload_sha256"), str) else None)
            ),
            "server_shapes_tool_count": len(shapes_tools) if isinstance(shapes_tools, list) else None,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_exists_a": bool(source_a == "inline" or (isinstance(cif_a, str) and Path(cif_a).exists())),
            "cif_signature_a": sha256_text(content_a.strip()),
            "cif_integrity_a": "ok",
            "status_a": status_a,
            "solve_ok_a": solve_ok_a,
            "errors_a": errors_a,
        }
        log_lines.append("semantic_probe qlip mode=live_single_solve")
        log_lines.append(f"semantic_probe qlip cif_path_a={cif_a}")
        log_lines.append(f"semantic_probe qlip cif_sig_a={probe_live['cif_signature_a']}")
        return True, None, "ok", probe_live

    solve_b = client.call_tool("qlip.solve", {"request": req_b})
    source_b, cif_b, inline_b, solve_b_env = _extract_qlip_artifact(solve_b)
    status_b, errors_b, solve_ok_b = _extract_qlip_status_and_errors(solve_b)
    if not solve_b_env:
        return False, FAIL_QLIP_UNEXPECTED_CONTRACT, "qlip.solve returned unexpected response contract for probe B", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_signature_a": sha256_text(content_a.strip()),
        }
    if solve_ok_b is False:
        return False, FAIL_QLIP_NON_SOLUTION, "qlip.solve failed before producing a solution for probe B", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_signature_a": sha256_text(content_a.strip()),
            "status_b": status_b,
            "errors_b": errors_b,
        }
    if isinstance(status_b, str) and status_b.strip().lower() not in {"optimal", "success"}:
        return False, FAIL_QLIP_NON_SOLUTION, f"qlip.solve non-solution termination for probe B: {status_b}", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_signature_a": sha256_text(content_a.strip()),
            "status_b": status_b,
            "errors_b": errors_b,
        }
    if source_b is None:
        return False, FAIL_QLIP_MISSING_ARTIFACT, "qlip.solve did not return CIF artifact for probe B", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_signature_a": sha256_text(content_a.strip()),
            "status_b": status_b,
            "errors_b": errors_b,
        }
    if source_b == "path" and cif_b is not None:
        path_b = Path(cif_b)
        if not path_b.exists():
            return False, FAIL_QLIP_MISSING_ARTIFACT, "qlip.solve referenced missing solution artifact path for probe B", {
                "request_signature_a": req_sig_a,
                "request_signature_b": req_sig_b,
                "cif_path_a": cif_a,
                "cif_source_a": source_a,
                "cif_path_b": cif_b,
                "cif_source_b": source_b,
                "cif_exists_b": False,
                "cif_signature_a": sha256_text(content_a.strip()),
                "status_b": status_b,
                "errors_b": errors_b,
            }
        content_b = path_b.read_text(encoding="utf-8", errors="ignore")
    elif source_b == "inline" and inline_b is not None:
        content_b = inline_b
    else:
        return False, FAIL_QLIP_UNEXPECTED_CONTRACT, "qlip.solve returned unsupported CIF artifact shape for probe B", {
            "request_signature_a": req_sig_a,
            "request_signature_b": req_sig_b,
            "cif_path_a": cif_a,
            "cif_source_a": source_a,
            "cif_path_b": cif_b,
            "cif_source_b": source_b,
            "cif_signature_a": sha256_text(content_a.strip()),
            "status_b": status_b,
            "errors_b": errors_b,
        }
    ok_b, code_b, detail_b = _cif_integrity_check(content_b)
    probe: dict[str, Any] = {
        "request_signature_a": req_sig_a,
        "request_signature_b": req_sig_b,
        "server_marker_payload_sha256": (
            shapes_env.get("payload_sha256")
            if isinstance(shapes_env.get("payload_sha256"), str)
            else (shapes_meta.get("payload_sha256") if isinstance(shapes_meta.get("payload_sha256"), str) else None)
        ),
        "server_shapes_tool_count": len(shapes_tools) if isinstance(shapes_tools, list) else None,
        "cif_path_a": cif_a,
        "cif_path_b": cif_b,
        "cif_source_a": source_a,
        "cif_source_b": source_b,
        "cif_exists_a": bool(source_a == "inline" or (isinstance(cif_a, str) and Path(cif_a).exists())),
        "cif_exists_b": bool(source_b == "inline" or (isinstance(cif_b, str) and Path(cif_b).exists())),
        "cif_signature_a": sha256_text(content_a.strip()),
        "cif_signature_b": sha256_text(content_b.strip()),
        "cif_integrity_a": "ok",
        "status_a": status_a,
        "status_b": status_b,
        "solve_ok_a": solve_ok_a,
        "solve_ok_b": solve_ok_b,
        "errors_a": errors_a,
        "errors_b": errors_b,
    }
    log_lines.append(f"semantic_probe qlip cif_path_a={cif_a}")
    log_lines.append(f"semantic_probe qlip cif_path_b={cif_b}")
    log_lines.append(f"semantic_probe qlip cif_sig_a={probe['cif_signature_a']}")
    log_lines.append(f"semantic_probe qlip cif_sig_b={probe['cif_signature_b']}")
    if not ok_b:
        probe["cif_integrity_b"] = "invalid"
        return False, code_b, detail_b, probe
    probe["cif_integrity_b"] = "ok"
    if probe["cif_signature_a"] == probe["cif_signature_b"]:
        return (
            False,
            FAIL_QLIP_CONDITIONING,
            "distinct startup probe requests produced identical solution.cif signatures",
            probe,
        )
    return True, None, "ok", probe


def _run_dependency(
    *,
    dependency: str,
    command: str | list[str],
    expected_tools: set[str],
    env: dict[str, str],
    cwd: str,
    startup_dir: Path,
    mode: str,
    allow_repo_qlip_shim: bool,
) -> dict[str, Any]:
    timeout_s = 30
    if dependency == "qlip":
        timeout_s = 120 if mode == "live" else 45
    provenance = _build_provenance(dependency=dependency, command=command, cwd=cwd, env=env)
    log_lines = [
        f"dependency={dependency}",
        f"command={command}",
        f"timeout_s={timeout_s}",
        f"resolved_argv={provenance.get('resolved_argv')}",
        f"launch_cwd={cwd}",
        f"module_name={provenance.get('module_name')}",
        f"module_origin={provenance.get('module_origin')}",
        f"script_path={provenance.get('script_path')}",
    ]
    if dependency == "qlip" and mode == "live" and bool(provenance.get("is_repo_qlip_shim")) and not allow_repo_qlip_shim:
        detail = (
            "live startup resolved QLIP to repo shim module 'qlip_mcp.server'; "
            "configure qlip_mcp_cmd/qlip_mcp_cwd to the fixed external QLIP server"
        )
        log_lines.append("provenance_fail qlip_repo_shim_blocked=true")
        _write_log(startup_dir / "startup_logs" / f"{dependency}.log", log_lines)
        return _result(
            dependency=dependency,
            command=command,
            startup_ok=False,
            surface_ok=False,
            semantic_ok=False,
            failure_code=FAIL_QLIP_SHIM_PROVENANCE,
            detail=detail,
            probe={},
            provenance=provenance,
        )
    try:
        with StdioMCPClient(command, timeout_s=timeout_s, cwd=cwd, env=env) as client:
            tools = set(client.list_tools())
            missing = sorted(expected_tools - tools)
            log_lines.append(f"tools={sorted(tools)}")
            if missing:
                detail = f"missing_tools={missing}"
                log_lines.append(f"surface_fail {detail}")
                result = _result(
                    dependency=dependency,
                    command=command,
                    startup_ok=True,
                    surface_ok=False,
                    semantic_ok=False,
                    failure_code={
                        "crystaldb": FAIL_CRYSTALDB_STARTUP,
                        "spp": FAIL_SPP_STARTUP,
                        "qlip": FAIL_QLIP_STARTUP,
                    }[dependency],
                    detail=detail,
                    probe={"missing_tools": missing},
                    provenance=provenance,
                )
                _write_log(startup_dir / "startup_logs" / f"{dependency}.log", log_lines)
                return result

            if dependency == "crystaldb":
                ok, failure_code, detail, probe = _probe_crystaldb_semantic(
                    client,
                    log_lines=log_lines,
                    startup_dir=startup_dir,
                    provenance=provenance,
                    available_tools=tools,
                )
            elif dependency == "spp":
                ok, failure_code, detail, probe = _probe_spp_semantic(
                    client,
                    startup_dir=startup_dir,
                    log_lines=log_lines,
                )
            else:
                ok, failure_code, detail, probe = _probe_qlip_semantic(client, log_lines=log_lines, mode=mode)
            result = _result(
                dependency=dependency,
                command=command,
                startup_ok=True,
                surface_ok=True,
                semantic_ok=ok,
                failure_code=failure_code,
                detail=detail,
                probe=probe,
                provenance=provenance,
            )
            _write_log(startup_dir / "startup_logs" / f"{dependency}.log", log_lines)
            return result
    except (MCPClientError, Exception) as exc:  # noqa: BLE001
        log_lines.append(f"startup_exception={exc}")
        _write_log(startup_dir / "startup_logs" / f"{dependency}.log", log_lines)
        return _result(
            dependency=dependency,
            command=command,
            startup_ok=False,
            surface_ok=False,
            semantic_ok=False,
            failure_code={
                "crystaldb": FAIL_CRYSTALDB_STARTUP,
                "spp": FAIL_SPP_STARTUP,
                "qlip": FAIL_QLIP_STARTUP,
            }[dependency],
            detail=str(exc),
            probe={},
            provenance=provenance,
        )


def _resolve_cwd(configured: str | None) -> str:
    if isinstance(configured, str) and configured.strip():
        return str(Path(configured).resolve())
    return str(Path.cwd())


def run_startup_validation(
    *,
    mode: str,
    settings: Settings,
    workspace: Path,
    commands: tuple[str | list[str], str | list[str], str | list[str]],
    strict: bool = True,
) -> dict[str, Any]:
    startup_dir = workspace / "startup"
    startup_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "CRYSTALDB_POLICY_MODE": settings.crystaldb_policy_mode,
        "SOKLLM_RUN_DIR": str((startup_dir / "probe_outputs" / "qlip" / "run").resolve()),
    }
    crystal_cwd = _resolve_cwd(settings.crystaldb_mcp_cwd)
    spp_cwd = _resolve_cwd(settings.spp_mcp_cwd)
    qlip_cwd = _resolve_cwd(settings.qlip_mcp_cwd)
    crystal_cmd, spp_cmd, qlip_cmd = commands
    results = {
        "crystaldb": _run_dependency(
            dependency="crystaldb",
            command=crystal_cmd,
            expected_tools=set(CRYSTAL_TOOLS),
            env=env,
            cwd=crystal_cwd,
            startup_dir=startup_dir,
            mode=mode,
            allow_repo_qlip_shim=bool(settings.qlip_allow_repo_shim),
        ),
        "spp": _run_dependency(
            dependency="spp",
            command=spp_cmd,
            expected_tools=set(SPP_TOOLS),
            env=env,
            cwd=spp_cwd,
            startup_dir=startup_dir,
            mode=mode,
            allow_repo_qlip_shim=bool(settings.qlip_allow_repo_shim),
        ),
        "qlip": _run_dependency(
            dependency="qlip",
            command=qlip_cmd,
            expected_tools=set(QLIP_TOOLS),
            env=env,
            cwd=qlip_cwd,
            startup_dir=startup_dir,
            mode=mode,
            allow_repo_qlip_shim=bool(settings.qlip_allow_repo_shim),
        ),
    }
    failed = [row for row in results.values() if not bool(row.get("ok", False))]
    blocked_by = str(failed[0].get("failure_code")) if failed else None
    detail = str(failed[0].get("detail")) if failed else "startup semantic checks passed"
    startup_ok = not failed
    if not strict:
        # Non-strict mode still records failures but allows startup.
        startup_ok = True
        blocked_by = None
        detail = "non_strict_mode: startup failures recorded but not gated"

    report = {
        "schema_version": "startup.report.v1",
        "mode": mode,
        "strict": bool(strict),
        "required_dependencies": required_startup_dependencies(),
        "startup_ok": bool(startup_ok),
        "blocked_by": blocked_by,
        "detail": detail,
        "dependencies": results,
        "startup_dependency_runtime": {
            "commands": {
                "crystaldb": crystal_cmd,
                "spp": spp_cmd,
                "qlip": qlip_cmd,
            },
            "cwds": {
                "crystaldb": crystal_cwd,
                "spp": spp_cwd,
                "qlip": qlip_cwd,
            },
        },
        "startup_dir": str(startup_dir),
        "artifacts": {
            "startup_report": str(startup_dir / "startup_report.json"),
            "startup_probe_results": str(startup_dir / "startup_probe_results.json"),
            "startup_logs_dir": str(startup_dir / "startup_logs"),
        },
    }
    _write_json(startup_dir / "startup_probe_results.json", {"dependencies": results})
    _write_json(startup_dir / "startup_report.json", report)
    return report
