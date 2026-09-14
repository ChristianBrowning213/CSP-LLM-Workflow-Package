
"""MCP server exposing SPP maker orchestration and utility tools."""

from __future__ import annotations

import json
import os
import shutil
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, get_args, get_origin

from pydantic import ValidationError

from spp_maker import __version__ as spp_maker_version
from spp_maker.boundary import normalize_warnings
from spp_maker.io_cif import load_cifs_from_dir
from spp_maker.pot_compat import check_pot_root, render_compat_report
from spp_maker.publish import build_run_id, get_git_sha
from spp_maker.qlip_outputs_packages import publish_registry_artifact
from spp_maker.qlip_package import build_package_payload, compute_content_hash, write_package_json
from spp_maker.run_orchestrator import RunConfig, RunResult, run_pipeline
from spp_maker_qlip.qlip_package import create_spp_guidance_package
from spp_maker_qlip.required_pair_extraction import export_required_pair_spp_root

from .contracts import (
    MCPServerConfig,
    TOOL_REQUEST_MODELS,
    TOOL_RESULT_MODELS,
    CheckCompatRequest,
    CheckCompatResult,
    CompatFailure,
    PackageForQLIPRequest,
    PackageForQLIPResult,
    ProvenanceBlock,
    PublishToQLIPOutputsRequest,
    PublishToQLIPOutputsResult,
    RunPipelinePaths,
    RunPipelineRequest,
    RunPipelineResult,
    StructuredError,
    StructuredErrorDetail,
    ToolEnvelope,
    build_tool_schemas,
    stable_hash,
)

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - used when MCP SDK is not installed.

    class FastMCP:  # type: ignore[override]
        """Small fallback shim so tests can import without MCP installed."""

        def __init__(self, name: str) -> None:
            self.name = name
            self._tools: dict[str, Any] = {}

        def tool(self, name: str | None = None) -> Any:
            def _decorator(func: Any) -> Any:
                tool_name = name or func.__name__
                self._tools[tool_name] = func
                return func

            return _decorator

        def run(self, transport: str = "stdio") -> None:
            raise RuntimeError(
                "mcp package is not installed. Install with: pip install -e '.[mcp]'"
            )


TOOL_NAME_RUN = "spp.run_pipeline"
TOOL_NAME_COMPAT = "spp.check_compat"
TOOL_NAME_PACKAGE = "spp.package_for_qlip"
TOOL_NAME_PUBLISH = "spp.publish_to_qlip_outputs"

TOOL_SCHEMAS = build_tool_schemas()

mcp = FastMCP("spp-maker")


class ToolValidationError(Exception):
    """Validation error intended for machine-readable responses."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "validation_error",
        details: list[StructuredErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or []


@dataclass(frozen=True)
class RuntimeContext:
    config: MCPServerConfig
    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]
    repo_root: Path


class RuntimeStageRecorder:
    """Collect lightweight stage timing for MCP responses."""

    def __init__(self) -> None:
        self._t0 = perf_counter()
        self._active: dict[str, float] = {}
        self.stages: list[dict[str, Any]] = []
        self.path: Path | None = None

    def attach(self, path: Path) -> None:
        self.path = path
        self._flush()

    def _flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"runtime_stages": self.stages}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def start(self, stage: str) -> None:
        self._active[stage] = perf_counter()
        self.stages.append({"stage": stage, "status": "started"})
        self._flush()

    def complete(self, stage: str, **extra: Any) -> None:
        start = self._active.pop(stage, perf_counter())
        payload: dict[str, Any] = {
            "stage": stage,
            "status": "completed",
            "duration_ms": int(round((perf_counter() - start) * 1000)),
        }
        payload.update({key: value for key, value in extra.items() if value is not None})
        self.stages.append(payload)
        self._flush()

    def fail(self, stage: str, diagnostic: str, **extra: Any) -> None:
        start = self._active.pop(stage, self._t0)
        payload: dict[str, Any] = {
            "stage": stage,
            "status": "failed",
            "duration_ms": int(round((perf_counter() - start) * 1000)),
            "diagnostic": diagnostic,
        }
        payload.update({key: value for key, value in extra.items() if value is not None})
        self.stages.append(payload)
        self._flush()

    def elapsed_ms(self) -> int:
        return int(round((perf_counter() - self._t0) * 1000))


def _ensure_trace_id(value: str | None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"trace_{uuid.uuid4().hex[:16]}"


def _warning(*, code: str, message: str, path: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "message": message}
    if path:
        out["path"] = path
    return out


def _resolve_roots(raw_roots: list[str], *, fallback: Path) -> tuple[Path, ...]:
    roots = [Path(item).expanduser().resolve() for item in raw_roots if str(item).strip()]
    if roots:
        return tuple(sorted(set(roots), key=lambda p: str(p).lower()))
    return (fallback.resolve(),)


def _split_env_paths(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(os.pathsep) if item.strip()]


def load_server_config() -> RuntimeContext:
    """Load server runtime config from environment with safe defaults."""
    repo_root = Path(__file__).resolve().parents[2]
    default_root = Path.cwd().resolve()
    config = MCPServerConfig(
        allowed_read_roots=_split_env_paths(os.environ.get("SPP_MCP_ALLOWED_READ_ROOTS", "")),
        allowed_write_roots=_split_env_paths(os.environ.get("SPP_MCP_ALLOWED_WRITE_ROOTS", "")),
        max_cif_count=int(os.environ.get("SPP_MCP_MAX_CIF_COUNT", "5000")),
        max_runtime_seconds=int(os.environ.get("SPP_MCP_MAX_RUNTIME_SECONDS", "7200")),
        max_output_bytes=int(os.environ.get("SPP_MCP_MAX_OUTPUT_BYTES", "2000000000")),
    )
    return RuntimeContext(
        config=config,
        read_roots=_resolve_roots(config.allowed_read_roots, fallback=default_root),
        write_roots=_resolve_roots(config.allowed_write_roots, fallback=default_root),
        repo_root=repo_root,
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _validate_under_roots(
    *,
    raw_path: str,
    roots: tuple[Path, ...],
    path_name: str,
    must_exist: bool,
) -> Path:
    path_obj = Path(raw_path).expanduser()
    if must_exist:
        resolved = path_obj.resolve(strict=True)
    else:
        resolved = path_obj.resolve(strict=False)
    if any(_is_within(resolved, root) for root in roots):
        return resolved
    root_list = [str(root) for root in roots]
    raise ToolValidationError(
        f"{path_name} escapes allowlisted roots.",
        code="path_not_allowed",
        details=[
            StructuredErrorDetail(
                path=f"$.{path_name}",
                message="path is outside allowlisted roots",
                expected=f"in {root_list}",
                received=str(resolved),
            )
        ],
    )


def _count_non_recursive_cifs(cif_dir: Path) -> int:
    return sum(1 for entry in cif_dir.iterdir() if entry.is_file() and entry.suffix.lower() == ".cif")


def _tree_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return int(path.stat().st_size)
    total = 0
    for file_path in path.rglob("*"):
        if file_path.is_file():
            total += int(file_path.stat().st_size)
    return total


def _sorted_files_relative(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        [
            file_path.relative_to(root).as_posix()
            for file_path in root.rglob("*")
            if file_path.is_file()
        ]
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _validation_details_from_pydantic(exc: ValidationError, *, prefix: str = "$") -> list[StructuredErrorDetail]:
    details: list[StructuredErrorDetail] = []
    for item in exc.errors():
        loc = item.get("loc", ())
        if isinstance(loc, tuple):
            loc_path = ".".join(str(part) for part in loc)
        else:
            loc_path = str(loc)
        path = prefix if not loc_path else f"{prefix}.{loc_path}"
        details.append(
            StructuredErrorDetail(
                path=path,
                message=str(item.get("msg", "validation error")),
                expected=None,
                received=str(item.get("input")),
            )
        )
    return sorted(details, key=lambda d: (d.path, d.message, d.received or ""))


def _finalize_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return normalize_warnings(warnings)


def _warnings_payload(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in _finalize_warnings(warnings):
        entry: dict[str, Any] = {
            "code": item["code"],
            "message": item["message"],
            "dropped_keys": item.get("dropped_keys", []),
        }
        if item.get("path") is not None:
            entry["path"] = item.get("path")
        payload.append(entry)
    return payload


def _json_object_from_value(value: Any, *, path: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ToolValidationError(
                "Failed to decode JSON object.",
                code="invalid_json",
                details=[
                    StructuredErrorDetail(
                        path=path,
                        message="JSON string could not be decoded",
                        expected="JSON object",
                        received=str(exc),
                    )
                ],
            ) from exc
        if not isinstance(decoded, Mapping):
            raise ToolValidationError(
                "Decoded JSON must be an object.",
                code="invalid_json_object",
                details=[
                    StructuredErrorDetail(
                        path=path,
                        message="decoded JSON is not an object",
                        expected="object",
                        received=type(decoded).__name__,
                    )
                ],
            )
        return dict(decoded)
    raise ToolValidationError(
        "Tool arguments must be an object or JSON object string.",
        code="invalid_arguments_type",
        details=[
            StructuredErrorDetail(
                path=path,
                message="unsupported arguments type",
                expected="object|string(JSON object)",
                received=type(value).__name__,
            )
        ],
    )


def _rename_aliases(
    payload: dict[str, Any],
    *,
    aliases: dict[str, str],
    warnings: list[dict[str, Any]],
    path: str,
) -> dict[str, Any]:
    out = dict(payload)
    for alias_key in sorted(aliases):
        canonical = aliases[alias_key]
        if alias_key not in out:
            continue
        alias_value = out.pop(alias_key)
        if canonical in out:
            warnings.append(
                _warning(
                    code="alias_ignored",
                    message=f"alias '{alias_key}' ignored because canonical '{canonical}' is present.",
                    path=f"{path}.{alias_key}",
                )
            )
            continue
        out[canonical] = alias_value
        warnings.append(
            _warning(
                code="alias_key_used",
                message=f"normalized alias '{alias_key}' to '{canonical}'.",
                path=f"{path}.{canonical}",
            )
        )
    return out


def _extract_nested_model(annotation: Any) -> type[Any] | None:
    if isinstance(annotation, type) and hasattr(annotation, "model_fields"):
        return annotation
    origin = get_origin(annotation)
    if origin is None:
        return None
    for arg in get_args(annotation):
        nested = _extract_nested_model(arg)
        if nested is not None:
            return nested
    return None


def _filter_unknown_for_model(
    payload: dict[str, Any],
    *,
    model_type: type[Any],
    warnings: list[dict[str, Any]],
    path: str,
) -> dict[str, Any]:
    fields = getattr(model_type, "model_fields", {})
    out: dict[str, Any] = {}
    for key in sorted(payload.keys(), key=str):
        if key not in fields:
            warnings.append(
                _warning(
                    code="unknown_key_filtered",
                    message=f"unknown key '{key}' was dropped.",
                    path=f"{path}.{key}",
                )
            )
            continue
        value = payload[key]
        nested_model = _extract_nested_model(fields[key].annotation)
        if nested_model is not None and isinstance(value, Mapping):
            out[key] = _filter_unknown_for_model(
                dict(value),
                model_type=nested_model,
                warnings=warnings,
                path=f"{path}.{key}",
            )
        else:
            out[key] = value
    return out


def _normalize_run_arguments(raw_arguments: Any, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _json_object_from_value(raw_arguments, path="$")
    if len(payload) == 1 and "arguments" in payload:
        payload = _json_object_from_value(payload["arguments"], path="$.arguments")
        warnings.append(
            _warning(
                code="wrapper_unwrapped",
                message="unwrapped top-level 'arguments' object.",
                path="$.arguments",
            )
        )
    aliases = {
        "traceId": "trace_id",
        "cifDir": "cif_dir",
        "outDir": "out_dir",
        "dryRun": "dry_run",
        "fitMethod": "fit_method",
        "fit_params": "fit",
        "calib": "calibration",
        "calib_params": "calibration",
        "publish_to": "publish_to",
        "timeout": "timeout_seconds",
    }
    payload = _rename_aliases(payload, aliases=aliases, warnings=warnings, path="$")

    if "fit" in payload and not isinstance(payload["fit"], Mapping):
        payload["fit"] = _json_object_from_value(payload["fit"], path="$.fit")
    if "calibration" in payload and not isinstance(payload["calibration"], Mapping):
        payload["calibration"] = _json_object_from_value(payload["calibration"], path="$.calibration")
    if "filters" in payload and not isinstance(payload["filters"], Mapping):
        payload["filters"] = _json_object_from_value(payload["filters"], path="$.filters")
    if "publish" in payload and not isinstance(payload["publish"], Mapping):
        payload["publish"] = _json_object_from_value(payload["publish"], path="$.publish")

    fit = dict(payload.get("fit", {})) if isinstance(payload.get("fit"), Mapping) else {}
    calibration = (
        dict(payload.get("calibration", {})) if isinstance(payload.get("calibration"), Mapping) else {}
    )
    filters = dict(payload.get("filters", {})) if isinstance(payload.get("filters"), Mapping) else {}
    publish = dict(payload.get("publish", {})) if isinstance(payload.get("publish"), Mapping) else {}

    fit_keys = {
        "fit_method",
        "r_cut",
        "knn",
        "min_d",
        "d_min",
        "d_max",
        "alpha",
        "supercell_target_len",
        "r_max",
        "bin_width",
        "sigma",
        "truncate_sigma",
        "gr_eps",
        "max_pairs",
    }
    calibration_keys = {
        "target",
        "score_method",
        "mode",
        "q",
        "max_calib",
        "convention",
        "min_lambda",
        "max_lambda",
    }
    bandpass_keys = {"d_lo", "d_hi", "sigma_lo", "sigma_hi"}
    filter_keys = {"meta_csv", "property_filter", "property_mode"}

    for key in sorted(fit_keys):
        if key in payload and key not in fit:
            fit[key] = payload.pop(key)
            warnings.append(
                _warning(
                    code="field_hoisted_to_fit",
                    message=f"moved top-level '{key}' into 'fit.{key}'.",
                    path=f"$.fit.{key}",
                )
            )
    for key in sorted(calibration_keys):
        if key in payload and key not in calibration:
            calibration[key] = payload.pop(key)
            warnings.append(
                _warning(
                    code="field_hoisted_to_calibration",
                    message=f"moved top-level '{key}' into 'calibration.{key}'.",
                    path=f"$.calibration.{key}",
                )
            )
    for key in sorted(filter_keys):
        if key in payload and key not in filters:
            filters[key] = payload.pop(key)
            warnings.append(
                _warning(
                    code="field_hoisted_to_filters",
                    message=f"moved top-level '{key}' into 'filters.{key}'.",
                    path=f"$.filters.{key}",
                )
            )
    if "publish_to" in payload and "publish_to" not in publish:
        publish["publish_to"] = payload.pop("publish_to")
        warnings.append(
            _warning(
                code="field_hoisted_to_publish",
                message="moved top-level 'publish_to' into 'publish.publish_to'.",
                path="$.publish.publish_to",
            )
        )

    bandpass = (
        dict(calibration.get("bandpass", {}))
        if isinstance(calibration.get("bandpass"), Mapping)
        else {}
    )
    if "use_bandpass" in payload and "enabled" not in bandpass:
        bandpass["enabled"] = payload.pop("use_bandpass")
        warnings.append(
            _warning(
                code="field_hoisted_to_bandpass",
                message="moved top-level 'use_bandpass' into 'calibration.bandpass.enabled'.",
                path="$.calibration.bandpass.enabled",
            )
        )
    if "no_bandpass" in payload and "enabled" not in bandpass:
        value = payload.pop("no_bandpass")
        bandpass["enabled"] = (not bool(value)) if isinstance(value, bool) else False
        warnings.append(
            _warning(
                code="field_hoisted_to_bandpass",
                message="interpreted top-level 'no_bandpass' into 'calibration.bandpass.enabled'.",
                path="$.calibration.bandpass.enabled",
            )
        )
    for key in sorted(bandpass_keys):
        if key in payload and key not in bandpass:
            bandpass[key] = payload.pop(key)
            warnings.append(
                _warning(
                    code="field_hoisted_to_bandpass",
                    message=f"moved top-level '{key}' into 'calibration.bandpass.{key}'.",
                    path=f"$.calibration.bandpass.{key}",
                )
            )
    if bandpass:
        calibration["bandpass"] = bandpass

    if fit:
        payload["fit"] = fit
    if calibration:
        payload["calibration"] = calibration
    if filters:
        payload["filters"] = filters
    if publish:
        payload["publish"] = publish
    return payload


def _normalize_tool_arguments(
    *,
    tool_name: str,
    raw_arguments: Any,
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    if tool_name == TOOL_NAME_RUN:
        payload = _normalize_run_arguments(raw_arguments, warnings)
    else:
        payload = _json_object_from_value(raw_arguments, path="$")
        if len(payload) == 1 and "arguments" in payload:
            payload = _json_object_from_value(payload["arguments"], path="$.arguments")
            warnings.append(
                _warning(
                    code="wrapper_unwrapped",
                    message="unwrapped top-level 'arguments' object.",
                    path="$.arguments",
                )
            )
        aliases_by_tool: dict[str, dict[str, str]] = {
            TOOL_NAME_COMPAT: {"traceId": "trace_id", "sppRoot": "spp_root"},
            TOOL_NAME_PACKAGE: {
                "traceId": "trace_id",
                "runRoot": "run_root",
                "sppRoot": "spp_root",
                "calibrationJson": "calibration_json",
                "outDir": "out_dir",
                "includeRegistrySnapshot": "include_registry_snapshot",
            },
            TOOL_NAME_PUBLISH: {
                "traceId": "trace_id",
                "artifactRoot": "artifact_root",
                "qlipOutputsPath": "qlip_outputs_path",
                "strictCompat": "strict_compat",
                "copyMode": "copy_mode",
                "setLatest": "set_latest",
            },
        }
        payload = _rename_aliases(
            payload,
            aliases=aliases_by_tool.get(tool_name, {}),
            warnings=warnings,
            path="$",
        )

    model_type = TOOL_REQUEST_MODELS[tool_name]
    return _filter_unknown_for_model(
        payload,
        model_type=model_type,
        warnings=warnings,
        path="$",
    )


def _envelope_success(
    *,
    tool_name: str,
    trace_id: str,
    result_payload: Mapping[str, Any],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    envelope = ToolEnvelope(
        ok=True,
        trace_id=trace_id,
        tool_name=tool_name,
        result=dict(result_payload),
        error=None,
        warnings=_warnings_payload(warnings),
    )
    return envelope.model_dump(mode="json")


def _envelope_error(
    *,
    tool_name: str,
    trace_id: str,
    error_type: str,
    message: str,
    code: str,
    warnings: list[dict[str, Any]],
    details: list[StructuredErrorDetail] | None = None,
) -> dict[str, Any]:
    envelope = ToolEnvelope(
        ok=False,
        trace_id=trace_id,
        tool_name=tool_name,
        result=None,
        error=StructuredError(
            type=error_type,
            message=message,
            code=code,
            details=(details or []),
        ),
        warnings=_warnings_payload(warnings),
    )
    return envelope.model_dump(mode="json")


def _provenance(
    *,
    runtime: RuntimeContext,
    params_hash: str | None = None,
    content_hash: str | None = None,
) -> ProvenanceBlock:
    return ProvenanceBlock(
        git_sha=get_git_sha(runtime.repo_root),
        tool="SPP_Maker",
        tool_version=spp_maker_version,
        params_hash=params_hash,
        content_hash=content_hash,
    )


def _load_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ToolValidationError(
            f"Expected JSON object at {path}",
            code="invalid_json_object",
            details=[
                StructuredErrorDetail(
                    path="$",
                    message="JSON payload must be an object",
                    expected="object",
                    received=type(data).__name__,
                )
            ],
        )
    return data


def _copy_final_bundle_common(
    *,
    final_bundle: Path,
    package_json_src: Path,
    spp_root_src: Path,
    calibration_json_src: Path,
    compat_report_text: str,
) -> None:
    if final_bundle.exists():
        raise ToolValidationError(
            f"Final bundle already exists: {final_bundle}",
            code="path_exists",
            details=[
                StructuredErrorDetail(
                    path="$.out_dir",
                    message="target final bundle already exists",
                    expected="new output path",
                    received=str(final_bundle),
                )
            ],
        )
    final_bundle.mkdir(parents=True, exist_ok=False)
    shutil.copy2(package_json_src, final_bundle / "package.json")
    shutil.copytree(spp_root_src, final_bundle / "spp_root")
    guidance_dir = final_bundle / "guidance"
    guidance_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(calibration_json_src, guidance_dir / "calibration.json")
    (final_bundle / "compat_report.txt").write_text(compat_report_text, encoding="utf-8")
    (final_bundle / "README.txt").write_text(
        "Copy this folder into your QLIP repo.\n"
        "Point SPPCollection at ./spp_root and use guidance/calibration.json.\n",
        encoding="utf-8",
    )


def _build_unified_qlip_package(
    *,
    run_root: Path,
    calibration_json: Path,
    out_dir: Path,
    name: str,
    qlip_outputs_root: Path | None = None,
    published_spp_rel: str | None = None,
    required_pairs: list[str] | None = None,
    material_system: str | None = None,
    formula: str | None = None,
    cif_count: int | None = None,
    fresh_spp_root: Path | None = None,
    fresh_generation: dict[str, Any] | None = None,
    allow_fallback_precompiled: bool = True,
) -> dict[str, Any]:
    def pair_key(pair: str) -> tuple[str, str]:
        left, right = str(pair).split("-", 1)
        ordered = sorted([left, right], key=str.lower)
        return ordered[0], ordered[1]

    def list_of_strings(payload: dict[str, Any], key: str) -> list[str]:
        return [
            str(item)
            for item in payload.get(key, [])
            if isinstance(item, str) and item.strip()
        ] if isinstance(payload.get(key), list) else []

    def supported_required_pairs(available: list[str], required: list[str]) -> list[str]:
        if not required:
            return sorted(dict.fromkeys(available), key=str.lower)
        available_keys = {pair_key(pair) for pair in available if "-" in pair}
        return [pair for pair in required if "-" in pair and pair_key(pair) in available_keys]

    bundle_name = name if name else "_bundle"
    bundle_root = out_dir / f"{bundle_name}_bundle"
    package_json_path = bundle_root / "package.json"
    try:
        guidance_result = create_spp_guidance_package(
            run_root,
            calibration_json,
            out_dir,
            bundle_name,
            qlip_outputs_root=qlip_outputs_root,
            published_spp_rel=published_spp_rel,
            required_pairs=required_pairs,
            material_system=material_system,
            formula=formula,
            cif_count=cif_count,
            fresh_spp_root=fresh_spp_root,
            fresh_generation=fresh_generation,
            allow_fallback_precompiled=allow_fallback_precompiled,
        )
        guidance_package_path = Path(str(guidance_result["guidance_package_path"]))
        compatibility = (
            guidance_result.get("compatibility")
            if isinstance(guidance_result.get("compatibility"), dict)
            else {}
        )
        qlip_solve_compatible = bool(compatibility.get("qlip_solve_compatible"))
        missing = [
            str(item)
            for item in compatibility.get("missing", [])
            if isinstance(item, str) and item.strip()
        ] if isinstance(compatibility.get("missing"), list) else []
        warnings = []
        if not qlip_solve_compatible:
            reason = compatibility.get("reason")
            warnings.append(str(reason) if isinstance(reason, str) and reason.strip() else "QLIP solve compatibility is false.")
        fresh_package = (
            guidance_result.get("fresh_package")
            if isinstance(guidance_result.get("fresh_package"), dict)
            else compatibility.get("fresh_package")
            if isinstance(compatibility.get("fresh_package"), dict)
            else {}
        )
        fallback_package = (
            guidance_result.get("fallback_package")
            if isinstance(guidance_result.get("fallback_package"), dict)
            else compatibility.get("fallback_package")
            if isinstance(compatibility.get("fallback_package"), dict)
            else {"metadata_available": False, "available_pairs": [], "missing_pairs": [], "pot_root": None}
        )
        selected_package = (
            guidance_result.get("selected_package")
            if isinstance(guidance_result.get("selected_package"), dict)
            else compatibility.get("selected_package")
            if isinstance(compatibility.get("selected_package"), dict)
            else {
                "pot_root_source": guidance_result.get("pot_root_source"),
                "pot_root": guidance_result.get("selected_pot_root"),
                "available_pairs": guidance_result.get("available_pairs")
                if isinstance(guidance_result.get("available_pairs"), list)
                else [],
                "required_pairs": guidance_result.get("required_pairs")
                if isinstance(guidance_result.get("required_pairs"), list)
                else [],
                "missing_pairs": guidance_result.get("missing_pairs")
                if isinstance(guidance_result.get("missing_pairs"), list)
                else [],
                "qlip_solve_compatible": qlip_solve_compatible,
            }
        )
        required_pairs_out = list_of_strings(guidance_result, "required_pairs") or list_of_strings(compatibility, "required_pairs")
        missing_pairs_out = list_of_strings(guidance_result, "missing_pairs") or list_of_strings(compatibility, "missing_pairs")
        fresh_available_pairs = list_of_strings(fresh_package, "available_pairs")
        fallback_available_pairs = list_of_strings(fallback_package, "available_pairs")
        selected_available_pairs = list_of_strings(selected_package, "available_pairs")
        if not selected_available_pairs:
            selected_available_pairs = list_of_strings(guidance_result, "available_pairs")
        fresh_supported_pairs = list_of_strings(fresh_package, "supported_pairs") or supported_required_pairs(
            fresh_available_pairs,
            list_of_strings(fresh_package, "required_pairs") or required_pairs_out,
        )
        fallback_supported_pairs = list_of_strings(fallback_package, "supported_pairs") or supported_required_pairs(
            fallback_available_pairs,
            list_of_strings(fallback_package, "required_pairs") or required_pairs_out,
        )
        selected_supported_pairs = list_of_strings(selected_package, "supported_pairs") or supported_required_pairs(
            selected_available_pairs,
            list_of_strings(selected_package, "required_pairs") or required_pairs_out,
        )
        if qlip_solve_compatible or selected_package.get("pot_root_source") == "fallback_precompiled":
            supported_pairs_out = selected_supported_pairs
        else:
            supported_pairs_out = list_of_strings(guidance_result, "supported_pairs") or fresh_supported_pairs
        available_pairs_out = list_of_strings(guidance_result, "available_pairs") or selected_available_pairs
        available_pairs_out = supported_required_pairs(available_pairs_out, required_pairs_out) if required_pairs_out else available_pairs_out
        diagnostic_only = bool(guidance_result.get("diagnostic_only")) or bool(selected_package.get("diagnostic_only")) or (
            bool(supported_pairs_out) and not qlip_solve_compatible
        )
        partial_pair_coverage = bool(supported_pairs_out) and bool(missing_pairs_out)
        can_use_as_partial_guidance = bool(guidance_result.get("can_use_as_partial_guidance"))
        qlip_partial_guidance_compatible = bool(guidance_result.get("qlip_partial_guidance_compatible")) or can_use_as_partial_guidance
        partial_guidance_pot_root = guidance_result.get("partial_guidance_pot_root") or guidance_result.get("partial_pot_root")
        supported_pair_pot_paths = (
            guidance_result.get("supported_pair_pot_paths")
            if isinstance(guidance_result.get("supported_pair_pot_paths"), dict)
            else {}
        )
        missing_pair_policy_recommendation = (
            guidance_result.get("missing_pair_policy_recommendation")
            if isinstance(guidance_result.get("missing_pair_policy_recommendation"), str)
            else "neutral"
        )
        strict_pair_coverage = bool(guidance_result.get("strict_pair_coverage", qlip_solve_compatible))
        fresh_required_complete = bool(
            guidance_result.get(
                "fresh_required_pair_coverage_complete",
                fresh_package.get("fresh_required_pair_coverage_complete", False),
            )
        )
        required_pot_export_complete = bool(
            guidance_result.get(
                "required_pair_pot_export_complete",
                fresh_package.get("required_pair_pot_export_complete", qlip_solve_compatible),
            )
        )
        fallback_required_to_solve = bool(guidance_result.get("fallback_required_to_solve"))
        if not fallback_required_to_solve:
            fallback_required_to_solve = not bool(
                qlip_solve_compatible
                and fresh_required_complete
                and required_pot_export_complete
                and not diagnostic_only
            )
        fallback_selected_reason = guidance_result.get("fallback_selected_reason")
        if not isinstance(fallback_selected_reason, str) or not fallback_selected_reason.strip():
            fallback_selected_reason = guidance_result.get("fallback_reason") if isinstance(guidance_result.get("fallback_reason"), str) else None
        if fallback_required_to_solve and (not isinstance(fallback_selected_reason, str) or not fallback_selected_reason.strip()):
            if missing_pairs_out:
                fallback_selected_reason = "fresh_required_pair_coverage_incomplete"
            elif diagnostic_only:
                fallback_selected_reason = "fresh_package_diagnostic_only"
            elif selected_package.get("pot_root_source") == "fallback_precompiled" or guidance_result.get("fallback_used"):
                fallback_selected_reason = "fallback_precompiled_selected"
            else:
                fallback_selected_reason = "fresh_package_not_solver_compatible"
        fresh_package = {
            **fresh_package,
            "supported_pairs": fresh_supported_pairs,
            "supported_pair_count": len(fresh_supported_pairs),
            "missing_pair_count": len(list_of_strings(fresh_package, "missing_pairs")),
            "partial_pair_coverage": bool(fresh_supported_pairs) and bool(list_of_strings(fresh_package, "missing_pairs")),
            "fallback_required_to_solve": fallback_required_to_solve,
            "fallback_selected_reason": fallback_selected_reason,
            "can_use_as_partial_guidance": can_use_as_partial_guidance,
            "qlip_partial_guidance_compatible": qlip_partial_guidance_compatible,
            "partial_guidance_pot_root": partial_guidance_pot_root,
            "supported_pair_pot_paths": supported_pair_pot_paths,
            "missing_pair_policy_recommendation": missing_pair_policy_recommendation,
            "strict_pair_coverage": strict_pair_coverage,
        }
        fallback_package = {
            **fallback_package,
            "supported_pairs": fallback_supported_pairs,
            "supported_pair_count": len(fallback_supported_pairs),
            "missing_pair_count": len(list_of_strings(fallback_package, "missing_pairs")),
            "partial_pair_coverage": bool(fallback_supported_pairs) and bool(list_of_strings(fallback_package, "missing_pairs")),
            "fallback_required_to_solve": fallback_required_to_solve,
            "fallback_selected_reason": fallback_selected_reason,
            "can_use_as_partial_guidance": can_use_as_partial_guidance,
            "qlip_partial_guidance_compatible": qlip_partial_guidance_compatible,
            "partial_guidance_pot_root": partial_guidance_pot_root,
            "supported_pair_pot_paths": supported_pair_pot_paths,
            "missing_pair_policy_recommendation": missing_pair_policy_recommendation,
            "strict_pair_coverage": strict_pair_coverage,
        }
        selected_package = {
            **selected_package,
            "available_pairs": selected_available_pairs,
            "supported_pairs": selected_supported_pairs,
            "supported_pair_count": len(selected_supported_pairs),
            "missing_pair_count": len(list_of_strings(selected_package, "missing_pairs")),
            "partial_pair_coverage": bool(selected_supported_pairs) and bool(list_of_strings(selected_package, "missing_pairs")),
            "diagnostic_only": diagnostic_only,
            "required_pair_pot_export_complete": bool(
                selected_package.get("required_pair_pot_export_complete", qlip_solve_compatible)
            ),
            "qlip_solve_compatible": qlip_solve_compatible,
            "fallback_required_to_solve": fallback_required_to_solve,
            "fallback_selected_reason": fallback_selected_reason,
            "can_use_as_partial_guidance": can_use_as_partial_guidance,
            "qlip_partial_guidance_compatible": qlip_partial_guidance_compatible,
            "partial_guidance_pot_root": partial_guidance_pot_root,
            "supported_pair_pot_paths": supported_pair_pot_paths,
            "missing_pair_policy_recommendation": missing_pair_policy_recommendation,
            "strict_pair_coverage": strict_pair_coverage,
        }

        package_json_path.parent.mkdir(parents=True, exist_ok=True)
        package_json_path.write_text(
            json.dumps(
                {
                    "name": bundle_name,
                    "spp_run_root": str(run_root),
                    "guidance_package_path": str(guidance_package_path),
                    "compatibility": compatibility,
                    "qlip_solve_compatible": qlip_solve_compatible,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "status": "ready" if qlip_solve_compatible else "partial",
            "guidance_package_path": str(guidance_package_path),
            "package_json_path": str(package_json_path),
            "final_bundle_path": str(bundle_root),
            "compatibility": compatibility,
            "qlip_solve_compatible": qlip_solve_compatible,
            "context": guidance_result.get("context") if isinstance(guidance_result.get("context"), dict) else {},
            "material_system": guidance_result.get("material_system") if isinstance(guidance_result.get("material_system"), str) else material_system,
            "formula": guidance_result.get("formula") if isinstance(guidance_result.get("formula"), str) else formula or material_system,
            "selected_pot_root": guidance_result.get("selected_pot_root"),
            "pot_root_source": guidance_result.get("pot_root_source"),
            "extraction_mode": guidance_result.get("extraction_mode"),
            "fresh_generation": guidance_result.get("fresh_generation") if isinstance(guidance_result.get("fresh_generation"), dict) else {},
            "fallback_used": bool(guidance_result.get("fallback_used")),
            "fallback_reason": guidance_result.get("fallback_reason"),
            "request_ref": guidance_result.get("request_ref"),
            "artifact_refs": guidance_result.get("artifact_refs") if isinstance(guidance_result.get("artifact_refs"), list) else [],
            "summary": guidance_result.get("summary") if isinstance(guidance_result.get("summary"), str) else "",
            "required_pairs": required_pairs_out,
            "missing_pairs": missing_pairs_out,
            "supported_pairs": supported_pairs_out,
            "supported_pair_count": len(supported_pairs_out),
            "missing_pair_count": len(missing_pairs_out),
            "partial_pair_coverage": partial_pair_coverage,
            "diagnostic_only": diagnostic_only,
            "required_pair_pot_export_complete": required_pot_export_complete,
            "fresh_required_pair_coverage_complete": fresh_required_complete,
            "fallback_required_to_solve": fallback_required_to_solve,
            "fallback_selected_reason": fallback_selected_reason,
            "can_use_as_partial_guidance": can_use_as_partial_guidance,
            "qlip_partial_guidance_compatible": qlip_partial_guidance_compatible,
            "partial_guidance_pot_root": partial_guidance_pot_root,
            "supported_pair_pot_paths": supported_pair_pot_paths,
            "missing_pair_policy_recommendation": missing_pair_policy_recommendation,
            "strict_pair_coverage": strict_pair_coverage,
            "sparse_pairs": guidance_result.get("sparse_pairs") if isinstance(guidance_result.get("sparse_pairs"), list) else [],
            "candidate_roots_checked": guidance_result.get("candidate_roots_checked") if isinstance(guidance_result.get("candidate_roots_checked"), list) else [],
            "available_pairs_by_candidate_root": guidance_result.get("available_pairs_by_candidate_root") if isinstance(guidance_result.get("available_pairs_by_candidate_root"), dict) else {},
            "available_pairs": available_pairs_out,
            "available_pair_count": len(available_pairs_out),
            "pair_coverage_complete": bool(selected_package.get("available_pairs")) and not bool(selected_package.get("missing_pairs")),
            "fresh_package": fresh_package,
            "fallback_package": fallback_package,
            "selected_package": selected_package,
            "missing": missing,
            "warnings": warnings,
            "errors": guidance_result.get("errors") if isinstance(guidance_result.get("errors"), list) else [],
        }
    except Exception as exc:
        return {
            "status": "failed",
            "guidance_package_path": None,
            "package_json_path": str(package_json_path),
            "final_bundle_path": str(bundle_root),
            "compatibility": {},
            "qlip_solve_compatible": False,
            "context": {},
            "material_system": material_system,
            "formula": formula or material_system,
            "selected_pot_root": None,
            "pot_root_source": "none",
            "extraction_mode": None,
            "fresh_generation": {},
            "fallback_used": False,
            "fallback_reason": None,
            "request_ref": None,
            "artifact_refs": [],
            "summary": "QLIP packaging failed.",
            "missing": [],
            "warnings": [],
            "errors": [
                {
                    "code": "qlip_packaging_failed",
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                }
            ],
        }


def _write_required_pair_run_scaffold(
    *,
    run_root: Path,
    final_bundle: Path,
    name: str,
    cif_dir: Path,
    content_hash: str,
    params_hash: str,
    runtime: RuntimeContext,
    stages: RuntimeStageRecorder | None = None,
) -> None:
    """Create the minimal run artifacts needed by the QLIP handoff package."""
    if stages is not None:
        stages.start("run_scaffold_dirs")
    (run_root / "fit" / "spp_root").mkdir(parents=True, exist_ok=True)
    (run_root / "calibrate" / "scaled_spp_root").mkdir(parents=True, exist_ok=True)
    (run_root / "package").mkdir(parents=True, exist_ok=True)
    if stages is not None:
        stages.complete("run_scaffold_dirs")
        stages.start("run_scaffold_calibration")
    calibration_payload = {
        "lambda_used": 1.0,
        "fit_method": "qlip_required_pairs",
        "score_method": "qlip_required_pairs",
        "convention": "reward",
    }
    (run_root / "calibrate" / "calibration.json").write_text(
        json.dumps(calibration_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if stages is not None:
        stages.complete("run_scaffold_calibration")
        stages.start("run_scaffold_package_payload")
    package_payload = build_package_payload(
        run_id=run_root.name,
        name=name,
        created_at_utc=datetime.now(timezone.utc).isoformat(),
        content_hash=content_hash,
        lambda_used=1.0,
        convention="reward",
        fit_method="qlip_required_pairs",
        calibration_method="qlip_required_pairs",
        corpus={
            "cif_dir": str(cif_dir),
            "num_structures_total": _count_non_recursive_cifs(cif_dir),
            "num_structures_selected": _count_non_recursive_cifs(cif_dir),
        },
        run_paths={
            "spp_root": str(run_root / "qlip_required_pairs" / "spp_root"),
            "guidance": str(run_root / "calibrate" / "calibration.json"),
        },
        final_paths={
            "spp_root": "spp_root",
            "guidance": "guidance/calibration.json",
        },
        provenance={
            "git_sha": None,
            "tool": "SPP_Maker",
            "tool_version": spp_maker_version,
            "params_hash": params_hash,
            "content_hash": content_hash,
        },
    )
    if stages is not None:
        stages.complete("run_scaffold_package_payload")
        stages.start("run_scaffold_package_write")
    write_package_json(run_root / "package" / "package.json", package_payload)
    if stages is not None:
        stages.complete("run_scaffold_package_write")
        stages.start("run_scaffold_final_bundle")
    final_bundle.mkdir(parents=True, exist_ok=True)
    if stages is not None:
        stages.complete("run_scaffold_final_bundle")

def _run_pipeline_impl(
    req: RunPipelineRequest,
    *,
    runtime: RuntimeContext,
    trace_id: str,
    warnings: list[dict[str, Any]],
) -> RunPipelineResult:
    stages = RuntimeStageRecorder()
    stages.start("path_validation")
    cif_dir = _validate_under_roots(
        raw_path=req.cif_dir,
        roots=runtime.read_roots,
        path_name="cif_dir",
        must_exist=True,
    )
    if not cif_dir.is_dir():
        raise ToolValidationError(
            "cif_dir must be a directory.",
            code="invalid_path_type",
            details=[
                StructuredErrorDetail(
                    path="$.cif_dir",
                    message="path is not a directory",
                    expected="directory",
                    received=str(cif_dir),
                )
            ],
        )
    out_dir = _validate_under_roots(
        raw_path=req.out_dir,
        roots=runtime.write_roots,
        path_name="out_dir",
        must_exist=False,
    )

    if req.filters.meta_csv is not None:
        _validate_under_roots(
            raw_path=req.filters.meta_csv,
            roots=runtime.read_roots,
            path_name="filters.meta_csv",
            must_exist=True,
        )
    if req.publish.publish_to is not None:
        _validate_under_roots(
            raw_path=req.publish.publish_to,
            roots=runtime.write_roots,
            path_name="publish.publish_to",
            must_exist=False,
        )
    stages.complete("path_validation")

    if req.covalent.enabled or req.covalent.rules_path is not None:
        raise ToolValidationError(
            "covalent settings are not supported by the current run orchestrator.",
            code="unsupported_parameter",
            details=[
                StructuredErrorDetail(
                    path="$.covalent",
                    message="current orchestrator does not accept covalent options",
                    expected="enabled=false and rules_path=null",
                    received=json.dumps(req.covalent.model_dump(mode="json"), sort_keys=True),
                )
            ],
        )

    stages.start("corpus_scan")
    cif_count = _count_non_recursive_cifs(cif_dir)
    stages.complete("corpus_scan", cif_count=cif_count)
    if cif_count > runtime.config.max_cif_count:
        raise ToolValidationError(
            "cif_dir exceeds max_cif_count cap.",
            code="max_cif_count_exceeded",
            details=[
                StructuredErrorDetail(
                    path="$.cif_dir",
                    message="too many CIF files",
                    expected=f"<={runtime.config.max_cif_count}",
                    received=str(cif_count),
                )
            ],
        )
    profile_max_cifs = req.max_cifs
    if profile_max_cifs is None and req.runtime_profile == "probe":
        profile_max_cifs = 2
    elif profile_max_cifs is None and req.runtime_profile == "demo":
        profile_max_cifs = 20
    if profile_max_cifs is not None and cif_count > int(profile_max_cifs):
        raise ToolValidationError(
            "cif_dir exceeds runtime profile max_cifs cap.",
            code="runtime_profile_max_cifs_exceeded",
            details=[
                StructuredErrorDetail(
                    path="$.max_cifs",
                    message="too many CIF files for runtime profile",
                    expected=f"<={profile_max_cifs}",
                    received=str(cif_count),
                )
            ],
        )

    timeout_limit = runtime.config.max_runtime_seconds
    effective_timeout = timeout_limit
    if req.timeout_seconds is not None:
        effective_timeout = int(req.timeout_seconds)
        if effective_timeout > timeout_limit:
            warnings.append(
                _warning(
                    code="timeout_capped",
                    message="timeout_seconds exceeded server cap; using max_runtime_seconds.",
                    path="$.timeout_seconds",
                )
            )
            effective_timeout = timeout_limit
        if effective_timeout <= 0:
            raise ToolValidationError(
                "timeout_seconds must be > 0 when provided.",
                code="invalid_timeout",
                details=[
                    StructuredErrorDetail(
                        path="$.timeout_seconds",
                        message="timeout must be > 0",
                        expected=">0",
                        received=str(req.timeout_seconds),
                    )
                ],
            )

    params_hash = stable_hash(
        req.model_dump(mode="json", exclude={"trace_id", "debug"})
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_root = out_dir / "logs"
    stages.attach(logs_root / f"{trace_id}_runtime_stages.json")

    if req.dry_run:
        selected_cifs = load_cifs_from_dir(cif_dir)
        cif_names = [Path(item.path).name for item in selected_cifs]
        content_hash = compute_content_hash(
            params_payload=req.model_dump(mode="json", exclude={"trace_id", "debug"}),
            cif_names=cif_names,
        )
        run_id = build_run_id(
            name=req.name,
            manifest_bytes=content_hash.encode("utf-8"),
            now_utc=datetime.now(timezone.utc),
        )
        run_root = out_dir / "SPP_Runs" / run_id
        final_bundle = out_dir / "Final_QLIP_output" / run_id
        log_path = logs_root / f"{run_id}.jsonl"
        _write_jsonl(
            log_path,
            [
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "phase": "run_pipeline",
                    "event": "start",
                    "trace_id": trace_id,
                    "dry_run": True,
                },
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "phase": "run_pipeline",
                    "event": "stop",
                    "trace_id": trace_id,
                    "dry_run": True,
                    "run_id": run_id,
                },
            ],
        )
        qlip_package = _build_unified_qlip_package(
            run_root=run_root,
            calibration_json=run_root / "calibrate" / "calibration.json",
            out_dir=run_root / "qlip_package",
            name=req.name,
            qlip_outputs_root=runtime.repo_root / "QLIP_Outputs",
            required_pairs=req.required_pairs,
            material_system=req.material_system or req.formula,
            formula=req.formula or req.material_system,
            cif_count=cif_count,
        )
        return RunPipelineResult(
            run_id=run_id,
            run_root=str(run_root),
            final_bundle=str(final_bundle),
            spp_run_root=str(run_root),
            final_bundle_path=str(final_bundle),
            calibration_json=str(run_root / "calibrate" / "calibration.json"),
            guidance_package_path=qlip_package.get("guidance_package_path"),
            package_json_path=qlip_package.get("package_json_path"),
            compatibility=qlip_package.get("compatibility", {}),
            qlip_solve_compatible=bool(qlip_package.get("qlip_solve_compatible")),
            qlip_package=qlip_package,
            runtime_profile=req.runtime_profile,
            runtime_stages=stages.stages,
            content_hash=content_hash,
            paths=RunPipelinePaths(
                fit_spp_root=str(run_root / "fit" / "spp_root"),
                calibration_json=str(run_root / "calibrate" / "calibration.json"),
                scaled_spp_root=str(run_root / "calibrate" / "scaled_spp_root"),
                package_json=str(run_root / "package" / "package.json"),
            ),
            published=None,
            provenance=ProvenanceBlock(
                git_sha=None,
                tool="SPP_Maker",
                tool_version=spp_maker_version,
                params_hash=params_hash,
                content_hash=content_hash,
            ),
            log_path=str(log_path),
            dry_run=True,
            cif_count=cif_count,
            output_bytes=0,
        )

    if req.qlip_pair_mode == "required_pairs":
        t0 = perf_counter()
        stages.start("run_scaffold")
        selected_cifs = load_cifs_from_dir(cif_dir)
        cif_names = [Path(item.path).name for item in selected_cifs]
        content_hash = compute_content_hash(
            params_payload=req.model_dump(mode="json", exclude={"trace_id", "debug"}),
            cif_names=cif_names,
        )
        run_id = build_run_id(
            name=req.name,
            manifest_bytes=content_hash.encode("utf-8"),
            now_utc=datetime.now(timezone.utc),
        )
        run_root = out_dir / "SPP_Runs" / run_id
        final_bundle = out_dir / "Final_QLIP_output" / run_id
        _write_required_pair_run_scaffold(
            run_root=run_root,
            final_bundle=final_bundle,
            name=req.name,
            cif_dir=cif_dir,
            content_hash=content_hash,
            params_hash=params_hash,
            runtime=runtime,
            stages=stages,
        )
        stages.complete("run_scaffold", run_id=run_id)

        formula_for_pairs = req.formula or req.material_system
        fresh_spp_root: Path | None = None
        fresh_generation: dict[str, Any] | None = None
        if formula_for_pairs:
            distances_cap = req.max_distances_per_pair or req.max_pairs_per_pair
            if distances_cap is None and req.runtime_profile == "probe":
                distances_cap = 128
            elif distances_cap is None and req.runtime_profile == "demo":
                distances_cap = 5000
            stages.start("required_pair_extraction")
            fresh_spp_root = run_root / "qlip_required_pairs" / "spp_root"
            try:
                fresh_generation = export_required_pair_spp_root(
                    cif_dir=cif_dir,
                    formula=formula_for_pairs,
                    out_root=fresh_spp_root,
                    name=f"{req.name}_qlip_required_pairs",
                    cutoff=float(req.qlip_pair_cutoff),
                    max_distances_per_pair=distances_cap,
                )
            except Exception as exc:
                stages.fail(
                    "required_pair_extraction",
                    str(exc),
                    code="required_pair_pot_export_failed",
                )
                raise
            stages.complete(
                "required_pair_extraction",
                missing_pairs=fresh_generation.get("missing_pairs") if isinstance(fresh_generation, dict) else [],
            )

        allow_fallback = (
            bool(req.allow_fallback_precompiled)
            if req.allow_fallback_precompiled is not None
            else req.runtime_profile != "probe"
        )
        stages.start("qlip_package")
        qlip_package = _build_unified_qlip_package(
            run_root=run_root,
            calibration_json=run_root / "calibrate" / "calibration.json",
            out_dir=run_root / "qlip_package",
            name=req.name,
            qlip_outputs_root=Path(req.publish.publish_to).resolve()
            if req.publish.publish_to is not None
            else runtime.repo_root / "QLIP_Outputs",
            required_pairs=req.required_pairs,
            material_system=req.material_system or req.formula,
            formula=req.formula or req.material_system,
            cif_count=cif_count,
            fresh_spp_root=fresh_spp_root,
            fresh_generation=fresh_generation,
            allow_fallback_precompiled=allow_fallback,
        )
        stages.complete(
            "qlip_package",
            status=qlip_package.get("status"),
            qlip_solve_compatible=qlip_package.get("qlip_solve_compatible"),
        )
        qlip_package["runtime_stages"] = stages.stages
        qlip_package["runtime_profile"] = req.runtime_profile

        elapsed = perf_counter() - t0
        log_path = logs_root / f"{run_id}.jsonl"
        _write_jsonl(
            log_path,
            [
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "phase": "run_pipeline",
                    "event": "required_pair_fast_path",
                    "trace_id": trace_id,
                    "run_id": run_id,
                    "elapsed_seconds": elapsed,
                    "runtime_profile": req.runtime_profile,
                    "runtime_stages": stages.stages,
                }
            ],
        )
        output_bytes = _tree_size_bytes(run_root) + _tree_size_bytes(final_bundle)
        return RunPipelineResult(
            run_id=run_id,
            run_root=str(run_root),
            final_bundle=str(final_bundle),
            spp_run_root=str(run_root),
            final_bundle_path=str(final_bundle),
            calibration_json=str(run_root / "calibrate" / "calibration.json"),
            guidance_package_path=qlip_package.get("guidance_package_path"),
            package_json_path=qlip_package.get("package_json_path"),
            compatibility=qlip_package.get("compatibility", {}),
            qlip_solve_compatible=bool(qlip_package.get("qlip_solve_compatible")),
            qlip_package=qlip_package,
            runtime_profile=req.runtime_profile,
            runtime_stages=stages.stages,
            content_hash=content_hash,
            paths=RunPipelinePaths(
                fit_spp_root=str(run_root / "fit" / "spp_root"),
                calibration_json=str(run_root / "calibrate" / "calibration.json"),
                scaled_spp_root=str(run_root / "calibrate" / "scaled_spp_root"),
                package_json=str(run_root / "package" / "package.json"),
            ),
            published=None,
            provenance=_provenance(
                runtime=runtime,
                params_hash=params_hash,
                content_hash=content_hash,
            ),
            log_path=str(log_path),
            dry_run=False,
            cif_count=cif_count,
            output_bytes=output_bytes,
        )

    t0 = perf_counter()
    existing_runs: set[str] = set()
    runs_root = out_dir / "SPP_Runs"
    if runs_root.is_dir():
        existing_runs = {p.name for p in runs_root.iterdir() if p.is_dir()}

    config = RunConfig(
        name=req.name,
        cif_dir=cif_dir,
        out_dir=out_dir,
        fit_method=req.fit.fit_method,
        calib_score_method=req.calibration.score_method,
        target=float(req.calibration.target),
        max_calib=req.calibration.max_calib,
        use_bandpass=bool(req.calibration.bandpass.enabled),
        convention=req.calibration.convention,
        min_lambda=float(req.calibration.min_lambda),
        max_lambda=float(req.calibration.max_lambda),
        calibration_mode=req.calibration.mode,
        q=float(req.calibration.q),
        r_cut=req.fit.r_cut,
        knn=req.fit.knn,
        min_d=req.fit.min_d,
        d_lo=req.calibration.bandpass.d_lo,
        d_hi=req.calibration.bandpass.d_hi,
        sigma_lo=req.calibration.bandpass.sigma_lo,
        sigma_hi=req.calibration.bandpass.sigma_hi,
        d_min=float(req.fit.d_min),
        d_max=float(req.fit.d_max),
        alpha=float(req.fit.alpha),
        supercell_target_len=float(req.fit.supercell_target_len),
        r_max=float(req.fit.r_max),
        bin_width=float(req.fit.bin_width),
        sigma=float(req.fit.sigma),
        truncate_sigma=float(req.fit.truncate_sigma),
        gr_eps=float(req.fit.gr_eps),
        max_pairs=req.fit.max_pairs,
        meta_csv=(None if req.filters.meta_csv is None else Path(req.filters.meta_csv).resolve()),
        property_filter=req.filters.property_filter,
        property_mode=req.filters.property_mode,
        publish_to=(
            None if req.publish.publish_to is None else Path(req.publish.publish_to).resolve()
        ),
    )

    orchestrator_result: RunResult | None = None
    try:
        stages.start("spp_fit")
        orchestrator_result = run_pipeline(config)
        stages.complete("spp_fit")
    except Exception:
        elapsed = perf_counter() - t0
        stages.fail("spp_fit", "run_pipeline raised an exception", elapsed_ms_so_far=stages.elapsed_ms())
        new_run_id = None
        if runs_root.is_dir():
            created = [
                p.name
                for p in runs_root.iterdir()
                if p.is_dir() and p.name not in existing_runs
            ]
            if created:
                new_run_id = sorted(created)[-1]
        log_id = new_run_id or trace_id
        log_path = logs_root / f"{log_id}.jsonl"
        rows: list[dict[str, Any]] = [
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "phase": "run_pipeline",
                "event": "start",
                "trace_id": trace_id,
            },
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "phase": "run_pipeline",
                "event": "error",
                "trace_id": trace_id,
                "elapsed_seconds": elapsed,
            },
        ]
        _write_jsonl(log_path, rows)
        raise

    elapsed = perf_counter() - t0
    if elapsed > float(effective_timeout):
        raise ToolValidationError(
            "run_pipeline exceeded max_runtime_seconds cap.",
            code="max_runtime_exceeded",
            details=[
                StructuredErrorDetail(
                    path="$.timeout_seconds",
                    message="runtime exceeded configured cap",
                    expected=f"<={effective_timeout}",
                    received=f"{elapsed:.6f}",
                )
            ],
        )

    run_root = Path(orchestrator_result.run_root).resolve()
    final_bundle = Path(orchestrator_result.final_bundle).resolve()
    output_bytes = _tree_size_bytes(run_root) + _tree_size_bytes(final_bundle)
    if output_bytes > runtime.config.max_output_bytes:
        raise ToolValidationError(
            "output size exceeded max_output_bytes cap.",
            code="max_output_bytes_exceeded",
            details=[
                StructuredErrorDetail(
                    path="$.out_dir",
                    message="generated output exceeds server cap",
                    expected=f"<={runtime.config.max_output_bytes}",
                    received=str(output_bytes),
                )
            ],
        )

    log_rows: list[dict[str, Any]] = [
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "phase": "run_pipeline",
            "event": "start",
            "trace_id": trace_id,
            "run_id": orchestrator_result.run_id,
        }
    ]
    timings_path = run_root / "logs" / "timings.json"
    if timings_path.is_file():
        timings_payload = _load_json_file(timings_path)
        timeline_start = datetime.now(timezone.utc).timestamp() - float(
            sum(float(v) for v in timings_payload.values())
        )
        cursor = timeline_start
        for phase, duration in timings_payload.items():
            dur = float(duration)
            start_iso = datetime.fromtimestamp(cursor, tz=timezone.utc).isoformat()
            stop_iso = datetime.fromtimestamp(cursor + dur, tz=timezone.utc).isoformat()
            log_rows.append(
                {"timestamp_utc": start_iso, "phase": str(phase), "event": "start", "run_id": orchestrator_result.run_id}
            )
            log_rows.append(
                {
                    "timestamp_utc": stop_iso,
                    "phase": str(phase),
                    "event": "stop",
                    "run_id": orchestrator_result.run_id,
                    "duration_seconds": dur,
                }
            )
            cursor += dur

    key_paths = [
        run_root / "fit" / "spp_root",
        run_root / "calibrate" / "scaled_spp_root",
        run_root / "package" / "package.json",
        run_root / "calibrate" / "calibration.json",
        final_bundle,
    ]
    log_rows.append(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "phase": "run_pipeline",
            "event": "paths_written",
            "run_id": orchestrator_result.run_id,
            "paths": [str(path) for path in key_paths],
        }
    )
    log_rows.append(
        {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "phase": "run_pipeline",
            "event": "stop",
            "trace_id": trace_id,
            "run_id": orchestrator_result.run_id,
            "elapsed_seconds": elapsed,
        }
    )
    log_path = logs_root / f"{orchestrator_result.run_id}.jsonl"
    _write_jsonl(log_path, log_rows)

    fresh_spp_root: Path | None = None
    fresh_generation: dict[str, Any] | None = None
    if req.qlip_pair_mode == "required_pairs":
        formula_for_pairs = req.formula or req.material_system
        if formula_for_pairs:
            fresh_spp_root = run_root / "qlip_required_pairs" / "spp_root"
            stages.start("required_pair_extraction")
            fresh_generation = export_required_pair_spp_root(
                cif_dir=cif_dir,
                formula=formula_for_pairs,
                out_root=fresh_spp_root,
                name=f"{req.name}_qlip_required_pairs",
                cutoff=float(req.qlip_pair_cutoff),
            )
            stages.complete("required_pair_extraction")

    stages.start("qlip_package")
    qlip_package = _build_unified_qlip_package(
        run_root=run_root,
        calibration_json=run_root / "calibrate" / "calibration.json",
        out_dir=run_root / "qlip_package",
        name=req.name,
        qlip_outputs_root=Path(req.publish.publish_to).resolve()
        if req.publish.publish_to is not None
        else runtime.repo_root / "QLIP_Outputs",
        published_spp_rel=orchestrator_result.published.get("spp")
        if isinstance(orchestrator_result.published, dict)
        else None,
        required_pairs=req.required_pairs,
        material_system=req.material_system or req.formula,
        formula=req.formula or req.material_system,
        cif_count=cif_count,
        fresh_spp_root=fresh_spp_root,
        fresh_generation=fresh_generation,
    )
    stages.complete("qlip_package", status=qlip_package.get("status"))
    qlip_package["runtime_stages"] = stages.stages
    qlip_package["runtime_profile"] = req.runtime_profile
    return RunPipelineResult(
        run_id=orchestrator_result.run_id,
        run_root=str(run_root),
        final_bundle=str(final_bundle),
        spp_run_root=str(run_root),
        final_bundle_path=str(final_bundle),
        calibration_json=str(run_root / "calibrate" / "calibration.json"),
        guidance_package_path=qlip_package.get("guidance_package_path"),
        package_json_path=qlip_package.get("package_json_path"),
        compatibility=qlip_package.get("compatibility", {}),
        qlip_solve_compatible=bool(qlip_package.get("qlip_solve_compatible")),
        qlip_package=qlip_package,
        runtime_profile=req.runtime_profile,
        runtime_stages=stages.stages,
        content_hash=orchestrator_result.content_hash,
        paths=RunPipelinePaths(
            fit_spp_root=str(run_root / "fit" / "spp_root"),
            calibration_json=str(run_root / "calibrate" / "calibration.json"),
            scaled_spp_root=str(run_root / "calibrate" / "scaled_spp_root"),
            package_json=str(run_root / "package" / "package.json"),
        ),
        published=orchestrator_result.published,
        provenance=_provenance(
            runtime=runtime,
            params_hash=params_hash,
            content_hash=orchestrator_result.content_hash,
        ),
        log_path=str(log_path),
        dry_run=False,
        cif_count=cif_count,
        output_bytes=output_bytes,
    )

def _check_compat_impl(
    req: CheckCompatRequest,
    *,
    runtime: RuntimeContext,
) -> CheckCompatResult:
    spp_root = _validate_under_roots(
        raw_path=req.spp_root,
        roots=runtime.read_roots,
        path_name="spp_root",
        must_exist=True,
    )
    if not spp_root.is_dir():
        raise ToolValidationError(
            "spp_root must be a directory.",
            code="invalid_path_type",
            details=[
                StructuredErrorDetail(
                    path="$.spp_root",
                    message="path is not a directory",
                    expected="directory",
                    received=str(spp_root),
                )
            ],
        )
    report = check_pot_root(spp_root, strict=bool(req.strict))
    failures = [
        CompatFailure(path=str(item.path), reason=item.reason)
        for item in sorted(report.failures, key=lambda f: str(f.path))
    ]
    return CheckCompatResult(
        ok=bool(report.ok),
        files_checked=int(report.checked),
        failed_count=int(report.failed),
        failures=failures,
    )


def _package_for_qlip_impl(
    req: PackageForQLIPRequest,
    *,
    runtime: RuntimeContext,
    warnings: list[dict[str, Any]],
) -> PackageForQLIPResult:
    out_dir = _validate_under_roots(
        raw_path=req.out_dir,
        roots=runtime.write_roots,
        path_name="out_dir",
        must_exist=False,
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    if req.run_root is not None:
        run_root = _validate_under_roots(
            raw_path=req.run_root,
            roots=runtime.read_roots,
            path_name="run_root",
            must_exist=True,
        )
        if not run_root.is_dir():
            raise ToolValidationError(
                "run_root must be a directory.",
                code="invalid_path_type",
                details=[
                    StructuredErrorDetail(
                        path="$.run_root",
                        message="path is not a directory",
                        expected="directory",
                        received=str(run_root),
                    )
                ],
            )
        run_id = run_root.name
        spp_root = run_root / "calibrate" / "scaled_spp_root"
        calibration_json = run_root / "calibrate" / "calibration.json"
        package_json_src = run_root / "package" / "package.json"
        compat_report = run_root / "calibrate" / "compat_report_scaled.txt"
        if not spp_root.is_dir():
            raise ToolValidationError(
                "run_root is missing calibrate/scaled_spp_root.",
                code="missing_required_path",
                details=[
                    StructuredErrorDetail(
                        path="$.run_root",
                        message="missing scaled_spp_root",
                        expected=str(spp_root),
                        received="missing",
                    )
                ],
            )
        if not calibration_json.is_file():
            raise ToolValidationError(
                "run_root is missing calibrate/calibration.json.",
                code="missing_required_path",
                details=[
                    StructuredErrorDetail(
                        path="$.run_root",
                        message="missing calibration.json",
                        expected=str(calibration_json),
                        received="missing",
                    )
                ],
            )
        if not package_json_src.is_file():
            raise ToolValidationError(
                "run_root is missing package/package.json.",
                code="missing_required_path",
                details=[
                    StructuredErrorDetail(
                        path="$.run_root",
                        message="missing package.json",
                        expected=str(package_json_src),
                        received="missing",
                    )
                ],
            )
        if compat_report.is_file():
            compat_text = compat_report.read_text(encoding="utf-8")
            if not compat_text.endswith("\n"):
                compat_text += "\n"
        else:
            compat_text = render_compat_report(check_pot_root(spp_root, strict=True)) + "\n"

        final_bundle = out_dir / "Final_QLIP_output" / run_id
        _copy_final_bundle_common(
            final_bundle=final_bundle,
            package_json_src=package_json_src,
            spp_root_src=spp_root,
            calibration_json_src=calibration_json,
            compat_report_text=compat_text,
        )

        if req.include_registry_snapshot:
            candidate_tree = run_root.parents[1] / "Final_QLIP_output" / run_id / "qlip_outputs_tree"
            if candidate_tree.is_dir():
                shutil.copytree(candidate_tree, final_bundle / "qlip_outputs_tree")
            else:
                warnings.append(
                    _warning(
                        code="registry_snapshot_missing",
                        message="include_registry_snapshot was requested but no source tree was found.",
                        path="$.include_registry_snapshot",
                    )
                )
    else:
        assert req.spp_root is not None
        assert req.calibration_json is not None
        spp_root = _validate_under_roots(
            raw_path=req.spp_root,
            roots=runtime.read_roots,
            path_name="spp_root",
            must_exist=True,
        )
        calibration_json = _validate_under_roots(
            raw_path=req.calibration_json,
            roots=runtime.read_roots,
            path_name="calibration_json",
            must_exist=True,
        )
        if not spp_root.is_dir():
            raise ToolValidationError(
                "spp_root must be a directory.",
                code="invalid_path_type",
                details=[
                    StructuredErrorDetail(
                        path="$.spp_root",
                        message="path is not a directory",
                        expected="directory",
                        received=str(spp_root),
                    )
                ],
            )
        if not calibration_json.is_file():
            raise ToolValidationError(
                "calibration_json must be a file.",
                code="invalid_path_type",
                details=[
                    StructuredErrorDetail(
                        path="$.calibration_json",
                        message="path is not a file",
                        expected="file",
                        received=str(calibration_json),
                    )
                ],
            )

        manifest_path = spp_root / "manifest.json"
        hash_bytes = manifest_path.read_bytes() if manifest_path.is_file() else calibration_json.read_bytes()
        run_id = build_run_id(
            name=req.name,
            manifest_bytes=hash_bytes,
            now_utc=datetime.now(timezone.utc),
        )
        final_bundle = out_dir / "Final_QLIP_output" / run_id
        calibration_payload = _load_json_file(calibration_json)
        lambda_used = float(calibration_payload.get("lambda_used", 1.0))
        fit_method = str(calibration_payload.get("fit_method", "unknown"))
        calibration_method = str(calibration_payload.get("score_method", "unknown"))
        convention = str(calibration_payload.get("convention", "reward"))
        content_hash = stable_hash(
            {
                "spp_manifest": manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else "",
                "calibration": calibration_payload,
            }
        )
        package_payload = build_package_payload(
            run_id=run_id,
            name=req.name,
            created_at_utc=datetime.now(timezone.utc).isoformat(),
            content_hash=content_hash,
            lambda_used=lambda_used,
            convention=convention,
            fit_method=fit_method,
            calibration_method=calibration_method,
            corpus={
                "cif_dir": None,
                "num_structures_total": 0,
                "num_structures_selected": 0,
            },
            run_paths={
                "spp_root": str(spp_root),
                "guidance": str(calibration_json),
            },
            final_paths={
                "spp_root": "spp_root",
                "guidance": "guidance/calibration.json",
            },
            provenance=_provenance(runtime=runtime, params_hash=None, content_hash=content_hash).model_dump(
                mode="json"
            ),
        )
        temp_package_json = out_dir / "_mcp_tmp" / f"{run_id}_package.json"
        temp_package_json.parent.mkdir(parents=True, exist_ok=True)
        write_package_json(temp_package_json, package_payload)
        compat_text = render_compat_report(check_pot_root(spp_root, strict=True)) + "\n"
        _copy_final_bundle_common(
            final_bundle=final_bundle,
            package_json_src=temp_package_json,
            spp_root_src=spp_root,
            calibration_json_src=calibration_json,
            compat_report_text=compat_text,
        )
        if temp_package_json.is_file():
            temp_package_json.unlink()

    package_json_path = final_bundle / "package.json"
    contents = _sorted_files_relative(final_bundle)
    output_bytes = _tree_size_bytes(final_bundle)
    if output_bytes > runtime.config.max_output_bytes:
        raise ToolValidationError(
            "packaged output exceeds max_output_bytes cap.",
            code="max_output_bytes_exceeded",
            details=[
                StructuredErrorDetail(
                    path="$.out_dir",
                    message="bundle exceeds max_output_bytes",
                    expected=f"<={runtime.config.max_output_bytes}",
                    received=str(output_bytes),
                )
            ],
        )
    return PackageForQLIPResult(
        run_id=run_id,
        final_bundle_path=str(final_bundle),
        package_json_path=str(package_json_path),
        contents=contents,
        provenance=_provenance(runtime=runtime),
        output_bytes=output_bytes,
    )


def _publish_to_qlip_outputs_impl(
    req: PublishToQLIPOutputsRequest,
    *,
    runtime: RuntimeContext,
) -> PublishToQLIPOutputsResult:
    artifact_root = _validate_under_roots(
        raw_path=req.artifact_root,
        roots=runtime.read_roots,
        path_name="artifact_root",
        must_exist=True,
    )
    qlip_outputs = _validate_under_roots(
        raw_path=req.qlip_outputs_path,
        roots=runtime.write_roots,
        path_name="qlip_outputs_path",
        must_exist=False,
    )
    if not artifact_root.is_dir():
        raise ToolValidationError(
            "artifact_root must be a directory.",
            code="invalid_path_type",
            details=[
                StructuredErrorDetail(
                    path="$.artifact_root",
                    message="path is not a directory",
                    expected="directory",
                    received=str(artifact_root),
                )
            ],
        )

    pub = publish_registry_artifact(
        kind=req.kind,
        artifact_root=artifact_root,
        qlip_outputs=qlip_outputs,
        name=req.name,
        params={
            "copy_mode": req.copy_mode,
            "strict_compat": bool(req.strict_compat),
            "set_latest": bool(req.set_latest),
            "invoked_by": "spp_maker_mcp",
        },
        strict_compat=bool(req.strict_compat),
        copy_mode=req.copy_mode,
        set_latest=bool(req.set_latest),
        overwrite=bool(req.overwrite),
        repo_root=runtime.repo_root,
    )
    index_path = qlip_outputs / "index.json"
    kind_dir = {
        "spp": "SPP",
        "guidance": "GUIDANCES",
        "package": "PACKAGES",
        "constraint": "CONSTRAINTS",
    }[req.kind]
    latest_pointer_path = qlip_outputs / kind_dir / "latest.txt"
    latest_value = (
        latest_pointer_path.read_text(encoding="utf-8").strip()
        if latest_pointer_path.is_file()
        else ""
    )
    output_bytes = _tree_size_bytes(pub.run_dir)
    if output_bytes > runtime.config.max_output_bytes:
        raise ToolValidationError(
            "published output exceeds max_output_bytes cap.",
            code="max_output_bytes_exceeded",
            details=[
                StructuredErrorDetail(
                    path="$.qlip_outputs_path",
                    message="published artifact exceeds max_output_bytes",
                    expected=f"<={runtime.config.max_output_bytes}",
                    received=str(output_bytes),
                )
            ],
        )
    return PublishToQLIPOutputsResult(
        published_run_id=pub.run_id,
        published_path=str(pub.run_dir),
        index_json_path=str(index_path),
        latest_pointer_path=str(latest_pointer_path),
        latest_pointer_value=latest_value,
        provenance=_provenance(runtime=runtime),
    )

def _invoke_tool(
    *,
    tool_name: str,
    arguments: Any,
    runtime: RuntimeContext | None = None,
) -> dict[str, Any]:
    runtime_ctx = runtime or load_server_config()
    warnings: list[dict[str, Any]] = []
    trace_id = _ensure_trace_id(arguments.get("trace_id") if isinstance(arguments, Mapping) else None)
    try:
        normalized_arguments = _normalize_tool_arguments(
            tool_name=tool_name,
            raw_arguments=arguments,
            warnings=warnings,
        )
    except ToolValidationError as exc:
        return _envelope_error(
            tool_name=tool_name,
            trace_id=trace_id,
            error_type="validation_error",
            message=str(exc),
            code=exc.code,
            warnings=warnings,
            details=list(exc.details),
        )

    request_model = TOOL_REQUEST_MODELS[tool_name]
    try:
        request_obj = request_model.model_validate(normalized_arguments)
    except ValidationError as exc:
        return _envelope_error(
            tool_name=tool_name,
            trace_id=trace_id,
            error_type="validation_error",
            message="Request validation failed.",
            code="request_validation_failed",
            warnings=warnings,
            details=_validation_details_from_pydantic(exc),
        )

    trace_id = _ensure_trace_id(getattr(request_obj, "trace_id", None))
    t0 = perf_counter()
    try:
        if tool_name == TOOL_NAME_RUN:
            assert isinstance(request_obj, RunPipelineRequest)
            result_obj = _run_pipeline_impl(
                request_obj,
                runtime=runtime_ctx,
                trace_id=trace_id,
                warnings=warnings,
            )
        elif tool_name == TOOL_NAME_COMPAT:
            assert isinstance(request_obj, CheckCompatRequest)
            result_obj = _check_compat_impl(request_obj, runtime=runtime_ctx)
        elif tool_name == TOOL_NAME_PACKAGE:
            assert isinstance(request_obj, PackageForQLIPRequest)
            result_obj = _package_for_qlip_impl(request_obj, runtime=runtime_ctx, warnings=warnings)
        elif tool_name == TOOL_NAME_PUBLISH:
            assert isinstance(request_obj, PublishToQLIPOutputsRequest)
            result_obj = _publish_to_qlip_outputs_impl(request_obj, runtime=runtime_ctx)
        else:
            raise ToolValidationError(
                f"Unsupported tool: {tool_name}",
                code="unsupported_tool",
                details=[
                    StructuredErrorDetail(
                        path="$.tool_name",
                        message="unknown tool name",
                        expected=str(sorted(TOOL_REQUEST_MODELS)),
                        received=tool_name,
                    )
                ],
            )
    except ToolValidationError as exc:
        return _envelope_error(
            tool_name=tool_name,
            trace_id=trace_id,
            error_type="validation_error",
            message=str(exc),
            code=exc.code,
            warnings=warnings,
            details=list(exc.details),
        )
    except Exception as exc:
        details: list[StructuredErrorDetail] = []
        if bool(getattr(request_obj, "debug", False)):
            details.append(
                StructuredErrorDetail(
                    path="$",
                    message="debug traceback",
                    expected=None,
                    received=traceback.format_exc(),
                )
            )
        return _envelope_error(
            tool_name=tool_name,
            trace_id=trace_id,
            error_type="execution_error",
            message=str(exc),
            code="execution_failed",
            warnings=warnings,
            details=details,
        )

    elapsed = perf_counter() - t0
    if elapsed > runtime_ctx.config.max_runtime_seconds:
        return _envelope_error(
            tool_name=tool_name,
            trace_id=trace_id,
            error_type="validation_error",
            message="execution exceeded max_runtime_seconds cap.",
            code="max_runtime_exceeded",
            warnings=warnings,
            details=[
                StructuredErrorDetail(
                    path="$.max_runtime_seconds",
                    message="runtime exceeded configured cap",
                    expected=f"<={runtime_ctx.config.max_runtime_seconds}",
                    received=f"{elapsed:.6f}",
                )
            ],
        )

    result_model = TOOL_RESULT_MODELS[tool_name]
    result_payload = result_obj.model_dump(mode="json")
    result_obj = result_model.model_validate(result_payload)
    return _envelope_success(
        tool_name=tool_name,
        trace_id=trace_id,
        result_payload=result_obj.model_dump(mode="json"),
        warnings=warnings,
    )


def invoke_tool(
    tool_name: str,
    arguments: Any,
    *,
    runtime: RuntimeContext | None = None,
) -> dict[str, Any]:
    """Test-friendly helper for invoking tool handlers without MCP transport."""
    return _invoke_tool(tool_name=tool_name, arguments=arguments, runtime=runtime)


def get_tool_schemas() -> dict[str, dict[str, Any]]:
    """Return canonical request/result/envelope schemas for all MCP tools."""
    return TOOL_SCHEMAS


@mcp.tool(name=TOOL_NAME_RUN)
def tool_run_pipeline(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run fit -> compat -> calibrate -> package -> publish pipeline."""
    return _invoke_tool(tool_name=TOOL_NAME_RUN, arguments=arguments)


@mcp.tool(name=TOOL_NAME_COMPAT)
def tool_check_compat(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run strict/non-strict POT compatibility checks on an SPP root."""
    return _invoke_tool(tool_name=TOOL_NAME_COMPAT, arguments=arguments)


@mcp.tool(name=TOOL_NAME_PACKAGE)
def tool_package_for_qlip(arguments: dict[str, Any]) -> dict[str, Any]:
    """Build a Final_QLIP_output style bundle from run_root or spp_root + calibration."""
    return _invoke_tool(tool_name=TOOL_NAME_PACKAGE, arguments=arguments)


@mcp.tool(name=TOOL_NAME_PUBLISH)
def tool_publish_to_qlip_outputs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Publish an artifact root to QLIP_Outputs registry layout."""
    return _invoke_tool(tool_name=TOOL_NAME_PUBLISH, arguments=arguments)


def _simple_stdio_main() -> None:
    """Run a small JSON-RPC stdio loop compatible with Skill-Loop's MCP client."""
    import sys

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
            sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
            sys.stdout.flush()
            continue

        request_id = request.get("id")
        method = request.get("method")
        if method == "notifications/initialized":
            continue
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "spp-maker", "version": spp_maker_version},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {"name": name, "inputSchema": TOOL_SCHEMAS[name]["request"]}
                        for name in sorted(TOOL_SCHEMAS)
                    ]
                }
            elif method == "tools/call":
                params = request.get("params") if isinstance(request.get("params"), Mapping) else {}
                tool_name = str(params.get("name", ""))
                arguments = params.get("arguments", {})
                if isinstance(arguments, Mapping) and set(arguments.keys()) == {"arguments"}:
                    arguments = arguments["arguments"]
                result = _invoke_tool(tool_name=tool_name, arguments=arguments)
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Unsupported method: {method}"},
                }
                sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
                sys.stdout.flush()
                continue
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:  # noqa: BLE001
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
                    "data": {"type": exc.__class__.__name__},
                },
            }
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()


def main() -> None:
    """Run MCP server over stdio transport."""
    if os.environ.get("SPP_MCP_USE_FASTMCP", "").strip().lower() in {"1", "true", "yes"}:
        mcp.run(transport="stdio")
        return
    _simple_stdio_main()


if __name__ == "__main__":
    main()
