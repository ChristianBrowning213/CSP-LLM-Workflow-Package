import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from crystal_db import api
from crystal_db.db import resolve_db_path

SERVER_NAME = "crystal-db-mcp"
SERVER_VERSION = "1.0.0"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = str(PACKAGE_ROOT / "configs" / "retrieval_defaults.json")
SUPPORTED_POLICY_MODES = {"safe", "demo"}
HARD_FAILURE_CODES = {
    "candidate_set_empty",
    "empty_corpus",
    "missing_embedding_space",
    "missing_index",
    "missing_db",
    "db_schema_missing",
    "query_tool_mismatch",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]


class ToolExecutionError(Exception):
    def __init__(self, *, tool_name: str, payload: Dict[str, Any], code: str, message: str):
        super().__init__(message)
        self.tool_name = tool_name
        self.payload = payload
        self.code = code
        self.message = message


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value: Any, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: Optional[str]) -> Optional[str]:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text


def _pick_value(args: Dict[str, Any], config: Dict[str, Any], keys: List[str], default: Any) -> Any:
    for key in keys:
        if key in args and args[key] is not None:
            return args[key]
    for key in keys:
        if key in config and config[key] is not None:
            return config[key]
    return default


def _resolve_path(path_value: Optional[str], *, base_dir: Optional[Path] = None) -> Optional[str]:
    text = _as_str(path_value, None)
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return str(candidate.resolve())
    anchor = base_dir or Path.cwd()
    return str((anchor / candidate).resolve())


def _resolve_policy_mode() -> str:
    raw = os.getenv("CRYSTALDB_POLICY_MODE", "safe").strip().lower()
    if raw not in SUPPORTED_POLICY_MODES:
        return "safe"
    return raw


def load_config(config_path: Optional[str]) -> Dict[str, Any]:
    resolved_path = _resolve_path(config_path) or _resolve_path(os.getenv("CRYSTALDB_CONFIG")) or DEFAULT_CONFIG_PATH
    if not resolved_path:
        return {}
    if not os.path.exists(resolved_path):
        return {}
    with open(resolved_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("retrieval defaults config must be a JSON object")
    payload["__config_path"] = resolved_path
    return payload


def _resolve_db_path(args: Dict[str, Any], config: Dict[str, Any]) -> str:
    explicit = _as_str(args.get("db_path"), None)
    if explicit:
        return _resolve_path(explicit) or explicit
    env_value = _as_str(os.getenv("CRYSTALDB_PATH") or os.getenv("CRYSTAL_DB_PATH"), None)
    if env_value:
        return _resolve_path(env_value) or env_value
    config_value = _as_str(config.get("db_path"), None)
    if config_value:
        config_base_dir = None
        config_path = _as_str(config.get("__config_path"), None)
        if config_path:
            config_base_dir = Path(config_path).resolve().parent
        return _resolve_path(config_value, base_dir=config_base_dir) or config_value
    return resolve_db_path()


def _resolve_common_settings(args: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    settings["k"] = max(1, _as_int(_pick_value(args, config, ["k"], 10), 10))
    settings["engine"] = _as_str(_pick_value(args, config, ["embed_engine", "engine"], "auto"), "auto")
    settings["model"] = _as_str(_pick_value(args, config, ["model", "model_name"], None), None)
    settings["model_version"] = _as_str(_pick_value(args, config, ["model_version"], None), None)
    settings["text_engine"] = _as_str(_pick_value(args, config, ["text_engine"], "robocrys"), "robocrys")
    settings["text_view"] = _as_str(_pick_value(args, config, ["text_view"], "robocrys"), "robocrys")
    settings["hybrid"] = _as_bool(_pick_value(args, config, ["hybrid"], False), False)
    settings["w_text"] = _as_float(_pick_value(args, config, ["w_text"], 1.0), 1.0)
    settings["w_fp"] = _as_float(_pick_value(args, config, ["w_fp"], 0.0), 0.0)
    settings["redacted"] = _as_bool(_pick_value(args, config, ["redacted"], True), True)
    requested_demo_export = _as_bool(_pick_value(args, config, ["demo_export"], False), False)
    settings["policy_mode"] = _resolve_policy_mode()
    settings["demo_export"] = requested_demo_export and settings["policy_mode"] == "demo"
    return settings


def _should_raise_hard_failure(payload: Dict[str, Any]) -> bool:
    errors = payload.get("errors")
    if not isinstance(errors, dict):
        return False
    code = str(errors.get("code") or "").strip()
    if not code:
        return False
    if code in HARD_FAILURE_CODES:
        return True
    lowered = code.lower()
    if "missing" in lowered and ("embedding" in lowered or "db" in lowered):
        return True
    return False


def _tool_text_search(args: Dict[str, Any]) -> Dict[str, Any]:
    config = load_config(_as_str(args.get("config_path"), None))
    settings = _resolve_common_settings(args, config)
    db_path = _resolve_db_path(args, config)
    query = _as_str(_pick_value(args, config, ["query", "text"], ""), "") or ""
    show_text_top = max(0, _as_int(_pick_value(args, config, ["show_text_top"], 3), 3))
    return api.retrieve_text(
        db_path,
        query,
        k=settings["k"],
        embed_engine=settings["engine"],
        model=settings["model"],
        model_version=settings["model_version"],
        text_engine=settings["text_engine"],
        text_view=settings["text_view"],
        hybrid=settings["hybrid"],
        w_text=settings["w_text"],
        w_fp=settings["w_fp"],
        redacted=settings["redacted"],
        show_text_top=show_text_top,
        demo_export=settings["demo_export"],
    )


def _tool_csp_pack(args: Dict[str, Any]) -> Dict[str, Any]:
    config = load_config(_as_str(args.get("config_path"), None))
    settings = _resolve_common_settings(args, config)
    db_path = _resolve_db_path(args, config)
    export_top = max(0, _as_int(_pick_value(args, config, ["export_top"], settings["k"]), settings["k"]))
    return api.make_csp_pack(
        db_path,
        query=_as_str(_pick_value(args, config, ["query", "text"], None), None),
        structure_id=_as_str(_pick_value(args, config, ["structure_id", "id"], None), None),
        out_dir=_as_str(_pick_value(args, config, ["out_dir", "out"], None), None),
        export_top=export_top,
        redacted=settings["redacted"],
        demo_export=settings["demo_export"],
        k=settings["k"],
        embed_engine=settings["engine"],
        model=settings["model"],
        model_version=settings["model_version"],
        text_engine=settings["text_engine"],
        text_view=settings["text_view"],
        hybrid=settings["hybrid"],
        w_text=settings["w_text"],
        w_fp=settings["w_fp"],
        material_system=_as_str(_pick_value(args, config, ["material_system"], None), None),
        formula=_as_str(_pick_value(args, config, ["formula"], None), None),
        semantic_min_threshold=(
            _as_float(_pick_value(args, config, ["semantic_min_threshold"], 0.0), 0.0)
            if _pick_value(args, config, ["semantic_min_threshold"], None) is not None
            else None
        ),
        spp_corpus_config=_pick_value(args, config, ["spp_corpus_config"], None),
    )


def _tool_status(args: Dict[str, Any]) -> Dict[str, Any]:
    config = load_config(_as_str(args.get("config_path"), None))
    settings = _resolve_common_settings(args, config)
    db_path = _resolve_db_path(args, config)
    surface = _as_str(_pick_value(args, config, ["surface"], "text_search"), "text_search") or "text_search"
    query_mode = "id" if _as_str(_pick_value(args, config, ["structure_id", "id"], None), None) else "query"
    return api.backend_status(
        db_path,
        surface=surface,
        query_mode=query_mode,
        structure_id=_as_str(_pick_value(args, config, ["structure_id", "id"], None), None),
        embed_engine=settings["engine"],
        model=settings["model"],
        model_version=settings["model_version"],
        text_engine=settings["text_engine"],
        text_view=settings["text_view"],
        hybrid=settings["hybrid"],
    )


TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "crystal.text_search": ToolSpec(
        name="crystal.text_search",
        description="Run Crystal-DB semantic text retrieval and return schema-versioned neighbors.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "db_path": {"type": "string"},
                "config_path": {"type": "string"},
                "k": {"type": "integer"},
                "embed_engine": {"type": "string"},
                "model": {"type": "string"},
                "model_version": {"type": "string"},
                "text_engine": {"type": "string"},
                "text_view": {"type": "string"},
                "hybrid": {"type": "boolean"},
                "w_text": {"type": "number"},
                "w_fp": {"type": "number"},
                "redacted": {"type": "boolean"},
                "show_text_top": {"type": "integer"},
                "demo_export": {"type": "boolean"},
            },
            "required": ["query"],
            "additionalProperties": True,
        },
        handler=_tool_text_search,
    ),
    "crystal.csp_pack": ToolSpec(
        name="crystal.csp_pack",
        description="Build CSP pack payloads from retrieval and optional CIF export.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "structure_id": {"type": "string"},
                "id": {"type": "string"},
                "db_path": {"type": "string"},
                "out_dir": {"type": "string"},
                "export_top": {"type": "integer"},
                "redacted": {"type": "boolean"},
                "demo_export": {"type": "boolean"},
                "material_system": {"type": "string"},
                "formula": {"type": "string"},
                "semantic_min_threshold": {"type": "number"},
                "spp_corpus_config": {"type": "object"},
                "config_path": {"type": "string"},
            },
            "additionalProperties": True,
        },
        handler=_tool_csp_pack,
    ),
    "crystal.status": ToolSpec(
        name="crystal.status",
        description="Report CrystalDB backend readiness for the requested retrieval surface and embedding space.",
        input_schema={
            "type": "object",
            "properties": {
                "surface": {"type": "string"},
                "structure_id": {"type": "string"},
                "id": {"type": "string"},
                "db_path": {"type": "string"},
                "config_path": {"type": "string"},
                "k": {"type": "integer"},
                "embed_engine": {"type": "string"},
                "model": {"type": "string"},
                "model_version": {"type": "string"},
                "text_engine": {"type": "string"},
                "text_view": {"type": "string"},
                "hybrid": {"type": "boolean"},
            },
            "additionalProperties": True,
        },
        handler=_tool_status,
    ),
}


def list_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "inputSchema": spec.input_schema,
        }
        for spec in TOOL_REGISTRY.values()
    ]


def execute_tool(tool_name: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if tool_name not in TOOL_REGISTRY:
        raise ToolExecutionError(
            tool_name=tool_name,
            payload={"errors": {"code": "tool_not_found", "message": f"Unknown tool: {tool_name}"}},
            code="tool_not_found",
            message=f"Unknown tool: {tool_name}",
        )
    payload = TOOL_REGISTRY[tool_name].handler(arguments or {})
    if _should_raise_hard_failure(payload):
        errors = payload.get("errors") or {}
        raise ToolExecutionError(
            tool_name=tool_name,
            payload=payload,
            code=str(errors.get("code") or "tool_failed"),
            message=str(errors.get("message") or "Tool execution failed"),
        )
    return payload


def _jsonrpc_success(request_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


def _call_tool_for_rpc(params: Dict[str, Any]) -> Dict[str, Any]:
    name = str(params.get("name") or "").strip()
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    payload = execute_tool(name, arguments)
    return {
        "content": [
            {
                "type": "json",
                "json": payload,
            }
        ],
        "isError": False,
    }


def _handle_rpc_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = request.get("method")
    request_id = request.get("id")
    is_notification = "id" not in request

    if not isinstance(method, str):
        return None if is_notification else _jsonrpc_error(request_id, -32600, "Invalid Request")

    if method in {"notifications/initialized", "initialized"}:
        return None

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        return None if is_notification else _jsonrpc_success(request_id, result)

    if method == "ping":
        return None if is_notification else _jsonrpc_success(request_id, {})

    if method == "tools/list":
        return None if is_notification else _jsonrpc_success(request_id, {"tools": list_tools()})

    if method == "tools/call":
        params = request.get("params")
        if not isinstance(params, dict):
            return None if is_notification else _jsonrpc_error(request_id, -32602, "Invalid params")
        try:
            result = _call_tool_for_rpc(params)
            return None if is_notification else _jsonrpc_success(request_id, result)
        except ToolExecutionError as exc:
            data = {"tool": exc.tool_name, "payload": exc.payload, "error_code": exc.code}
            return None if is_notification else _jsonrpc_error(request_id, -32010, exc.message, data)
        except Exception as exc:  # pylint: disable=broad-except
            data = {"tool": str((params or {}).get("name") or ""), "error": str(exc)}
            return None if is_notification else _jsonrpc_error(request_id, -32000, "Tool execution failed", data)

    return None if is_notification else _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def _emit(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _serve_minimal_stdio() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError:
            _emit(_jsonrpc_error(None, -32700, "Parse error"))
            continue

        if isinstance(decoded, list):
            responses: List[Dict[str, Any]] = []
            for item in decoded:
                if not isinstance(item, dict):
                    responses.append(_jsonrpc_error(None, -32600, "Invalid Request"))
                    continue
                response = _handle_rpc_request(item)
                if response is not None:
                    responses.append(response)
            if responses:
                _emit(responses[0] if len(responses) == 1 else responses)
            continue

        if not isinstance(decoded, dict):
            _emit(_jsonrpc_error(None, -32600, "Invalid Request"))
            continue
        response = _handle_rpc_request(decoded)
        if response is not None:
            _emit(response)


def _try_run_fastmcp() -> bool:
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except Exception:
        return False

    try:
        app = FastMCP(SERVER_NAME)
        for spec in TOOL_REGISTRY.values():

            def _runner(arguments: Optional[Dict[str, Any]] = None, *, _tool_name: str = spec.name) -> Dict[str, Any]:
                return execute_tool(_tool_name, arguments or {})

            app.tool(name=spec.name, description=spec.description)(_runner)
        app.run(transport="stdio")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        print(f"warning: FastMCP unavailable, falling back to minimal stdio runtime ({exc})", file=sys.stderr)
        return False


def main() -> int:
    if _try_run_fastmcp():
        return 0
    _serve_minimal_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
