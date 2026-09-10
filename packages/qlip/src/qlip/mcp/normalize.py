from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from qlip.resources import schema_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _schema_bundle() -> Dict[str, Any]:
    return json.loads(schema_path("MCP_SCHEMA.json").read_text(encoding="utf-8"))


_SCHEMAS = _schema_bundle()
_SOLVE_REQUEST_SCHEMA = _SCHEMAS.get("solve_request", {})


def _is_obj(value: Any) -> bool:
    return isinstance(value, dict)


def _is_list(value: Any) -> bool:
    return isinstance(value, list)


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _resolve_pointer(root: Any, pointer: str) -> Any:
    if pointer in ("", "#"):
        return root
    if pointer.startswith("#"):
        pointer = pointer[1:]
    if not pointer:
        return root
    if not pointer.startswith("/"):
        raise ValueError(f"Unsupported pointer: {pointer}")
    current = root
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _resolve_ref(root: Dict[str, Any], ref: str) -> Any:
    if ref.startswith("$defs/"):
        ref = "#/" + ref
    elif ref.startswith("/$defs/"):
        ref = "#" + ref
    if ref.startswith("#"):
        return _resolve_pointer(root, ref)
    raise KeyError(f"Unknown ref: {ref}")


def _property_default(schema: Dict[str, Any], prop: str) -> Any:
    props = schema.get("properties", {})
    prop_schema = props.get(prop)
    if not isinstance(prop_schema, dict):
        return None
    if "default" in prop_schema:
        return copy.deepcopy(prop_schema["default"])
    ref = prop_schema.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(schema, ref)
        if isinstance(resolved, dict) and "default" in resolved:
            return copy.deepcopy(resolved["default"])
    return None


def _warn(
    warnings: List[Dict[str, Any]],
    code: str,
    path: str,
    message: str,
    before: Any | None = None,
    after: Any | None = None,
) -> None:
    warnings.append(
        {
            "code": code,
            "path": path,
            "message": message,
            "before": copy.deepcopy(before),
            "after": copy.deepcopy(after),
        }
    )


def _parse_bool(value: Any, allow_numeric: bool = False) -> Tuple[bool | None, bool]:
    if isinstance(value, bool):
        return value, False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True, True
        if lowered == "false":
            return False, True
        if allow_numeric:
            if lowered == "1":
                return True, True
            if lowered == "0":
                return False, True
    return None, False


_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _parse_int(value: Any) -> Tuple[int | None, bool]:
    if isinstance(value, bool):
        return None, False
    if isinstance(value, int):
        return value, False
    if isinstance(value, str) and _INT_RE.match(value.strip()):
        return int(value), True
    return None, False


def _parse_float(value: Any) -> Tuple[float | None, bool]:
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        return float(value), False
    if isinstance(value, str) and _FLOAT_RE.match(value.strip()):
        candidate = float(value)
        if math.isfinite(candidate):
            return candidate, True
    return None, False


def _normalize_list_args(args: Any, warnings: List[Dict[str, Any]], tool_name: str) -> Any:
    if args is None:
        _warn(warnings, "COERCED_TYPE", "/", "normalized null args -> {}", before=None, after={})
        return {}
    if not _is_obj(args):
        return args

    normalized = dict(args)
    for key in ("ids", "tags_any"):
        if key not in normalized:
            continue
        value = normalized.get(key)
        if value is None or value == "":
            _warn(
                warnings,
                "COERCED_TYPE",
                f"/{key}",
                f"normalized {key} empty -> []",
                before=value,
                after=[],
            )
            normalized[key] = []
            continue
        if _is_obj(value):
            if not value:
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    f"/{key}",
                    f"normalized {key}:{{}} -> []",
                    before=value,
                    after=[],
                )
                normalized[key] = []
                continue
            if key in value and _is_list(value.get(key)) and all(_is_str(v) for v in value.get(key)):
                normalized[key] = value.get(key)
                _warn(
                    warnings,
                    "UNWRAPPED_WRAPPER",
                    f"/{key}",
                    f"normalized {key} wrapper {{{key}:[...]}} -> {key}:[...]",
                    before=value,
                    after=value.get(key),
                )
                continue
            continue
        if _is_list(value):
            if all(_is_str(v) for v in value):
                normalized[key] = value
            continue
        if _is_str(value):
            if value:
                normalized[key] = [value]
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    f"/{key}",
                    f"normalized {key} string -> [{value}]",
                    before=value,
                    after=[value],
                )
            continue
    if "include_params_schema" in normalized:
        parsed, coerced = _parse_bool(normalized.get("include_params_schema"))
        if parsed is not None and coerced:
            _warn(
                warnings,
                "COERCED_TYPE",
                "/include_params_schema",
                "coerced include_params_schema to boolean",
                before=normalized.get("include_params_schema"),
                after=parsed,
            )
            normalized["include_params_schema"] = parsed
    return normalized


def _normalize_shapes_args(args: Any, warnings: List[Dict[str, Any]]) -> Any:
    if args is None:
        return {}
    if not _is_obj(args):
        return args
    normalized = dict(args)
    if "tool" in normalized and normalized.get("tool") == "":
        _warn(
            warnings,
            "DROPPED_FIELD",
            "/tool",
            "removed empty tool filter",
            before="",
            after=None,
        )
        normalized.pop("tool", None)
    if "include_examples" in normalized:
        value = normalized.get("include_examples")
        if value is None or value == {}:
            _warn(
                warnings,
                "DROPPED_FIELD",
                "/include_examples",
                "removed include_examples because it was empty",
                before=value,
                after=None,
            )
            normalized.pop("include_examples", None)
        else:
            parsed, coerced = _parse_bool(value, allow_numeric=True)
            if parsed is not None and coerced:
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    "/include_examples",
                    "coerced include_examples to boolean",
                    before=value,
                    after=parsed,
                )
                normalized["include_examples"] = parsed
    return normalized


def _normalize_solve_args(args: Any, warnings: List[Dict[str, Any]], tool_name: str) -> Any:
    if not _is_obj(args):
        return args

    wrapper_keys = {"request", "solverequest", "solve_request", "payload"}
    has_wrapper_key = any(key.lower() in wrapper_keys for key in args.keys())
    if len(args) == 1:
        key = next(iter(args.keys()))
        value = args[key]
        key_lower = key.lower()
        if key_lower in wrapper_keys and _is_obj(value):
            _warn(
                warnings,
                "UNWRAPPED_WRAPPER",
                "/",
                f"normalized wrapper {{{key}: ...}} -> top-level SolveRequest",
                before=args,
                after=value,
            )
            args = value
            has_wrapper_key = False

    if not _is_obj(args):
        return args
    if has_wrapper_key:
        return args

    return _normalize_solve_request_scalars(args, warnings)


def _normalize_solve_request_scalars(req: Dict[str, Any], warnings: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not _is_obj(req):
        return req

    solver = req.get("solver")
    if _is_obj(solver):
        for key, path in [
            ("time_limit_s", "/solver/time_limit_s"),
            ("threads", "/solver/threads"),
            ("seed", "/solver/seed"),
        ]:
            if key in solver:
                parsed, coerced = _parse_int(solver.get(key))
                if parsed is not None and coerced:
                    _warn(
                        warnings,
                        "COERCED_TYPE",
                        path,
                        f"coerced {path} to int",
                        before=solver.get(key),
                        after=parsed,
                    )
                    solver[key] = parsed
        if "mip_gap" in solver:
            parsed, coerced = _parse_float(solver.get("mip_gap"))
            if parsed is not None and coerced:
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    "/solver/mip_gap",
                    "coerced /solver/mip_gap to number",
                    before=solver.get("mip_gap"),
                    after=parsed,
                )
                solver["mip_gap"] = parsed

    lattice = (
        req.get("problem", {})
        .get("design_space", {})
        .get("template", {})
        .get("lattice", {})
    )
    if _is_obj(lattice):
        for key in ("a", "b", "c", "alpha", "beta", "gamma"):
            if key in lattice:
                parsed, coerced = _parse_float(lattice.get(key))
                if parsed is not None and coerced:
                    _warn(
                        warnings,
                        "COERCED_TYPE",
                        f"/problem/design_space/template/lattice/{key}",
                        f"coerced lattice.{key} to number",
                        before=lattice.get(key),
                        after=parsed,
                    )
                    lattice[key] = parsed

    uniform = (
        req.get("problem", {})
        .get("design_space", {})
        .get("sites", {})
        .get("uniform_grid", {})
    )
    if _is_obj(uniform):
        if "density" in uniform:
            parsed, coerced = _parse_int(uniform.get("density"))
            if parsed is not None and coerced:
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    "/problem/design_space/sites/uniform_grid/density",
                    "coerced uniform_grid.density to int",
                    before=uniform.get("density"),
                    after=parsed,
                )
                uniform["density"] = parsed
        if "jitter" in uniform:
            parsed, coerced = _parse_float(uniform.get("jitter"))
            if parsed is not None and coerced:
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    "/problem/design_space/sites/uniform_grid/jitter",
                    "coerced uniform_grid.jitter to number",
                    before=uniform.get("jitter"),
                    after=parsed,
                )
                uniform["jitter"] = parsed
        if "seed" in uniform:
            parsed, coerced = _parse_int(uniform.get("seed"))
            if parsed is not None and coerced:
                _warn(
                    warnings,
                    "COERCED_TYPE",
                    "/problem/design_space/sites/uniform_grid/seed",
                    "coerced uniform_grid.seed to int",
                    before=uniform.get("seed"),
                    after=parsed,
                )
                uniform["seed"] = parsed

    artifacts = req.get("artifacts")
    if _is_obj(artifacts):
        for key in ("return_cif", "return_decoder_debug", "render_vesta"):
            if key in artifacts:
                parsed, coerced = _parse_bool(artifacts.get(key))
                if parsed is not None and coerced:
                    _warn(
                        warnings,
                        "COERCED_TYPE",
                        f"/artifacts/{key}",
                        f"coerced artifacts.{key} to boolean",
                        before=artifacts.get(key),
                        after=parsed,
                    )
                    artifacts[key] = parsed
        if "supercell" in artifacts and _is_list(artifacts.get("supercell")):
            supercell = list(artifacts.get("supercell"))
            updated = False
            for idx, value in enumerate(supercell):
                parsed, coerced = _parse_int(value)
                if parsed is not None and coerced:
                    _warn(
                        warnings,
                        "COERCED_TYPE",
                        f"/artifacts/supercell/{idx}",
                        "coerced supercell entry to int",
                        before=value,
                        after=parsed,
                    )
                    supercell[idx] = parsed
                    updated = True
            if updated:
                artifacts["supercell"] = supercell

    runtime = req.get("runtime")
    if _is_obj(runtime):
        for key in ("max_sites", "max_binary_vars", "max_constraints"):
            if key in runtime:
                parsed, coerced = _parse_int(runtime.get(key))
                if parsed is not None and coerced:
                    _warn(
                        warnings,
                        "COERCED_TYPE",
                        f"/runtime/{key}",
                        f"coerced runtime.{key} to int",
                        before=runtime.get(key),
                        after=parsed,
                    )
                    runtime[key] = parsed

    return req


def normalize_tool_args(tool_name: str, args: Any) -> Tuple[Any, List[Dict[str, Any]]]:
    warnings: List[Dict[str, Any]] = []
    if tool_name in {"qlip.list_constraints", "qlip.list_guidance"}:
        return _normalize_list_args(args, warnings, tool_name), warnings
    if tool_name == "qlip.shapes":
        return _normalize_shapes_args(args, warnings), warnings
    if tool_name in {"qlip.validate_request", "qlip.solve"}:
        return _normalize_solve_args(args, warnings, tool_name), warnings
    return args, warnings
