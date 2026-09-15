from __future__ import annotations

from copy import deepcopy
from typing import Any


SPP_TOOLS = [
    "spp.run_pipeline",
    "spp.check_compat",
    "spp.package_for_qlip",
    "spp.publish_to_qlip_outputs",
]

_ALIASES = {
    "traceId": "trace_id",
    "cifDir": "cif_dir",
    "outDir": "out_dir",
    "dryRun": "dry_run",
    "sppRoot": "spp_root",
    "runRoot": "run_root",
    "calibrationJson": "calibration_json",
    "artifactRoot": "artifact_root",
    "qlipOutputsPath": "qlip_outputs_path",
    "strictCompat": "strict_compat",
    "copyMode": "copy_mode",
    "setLatest": "set_latest",
    "includeRegistrySnapshot": "include_registry_snapshot",
}

_RUN_PIPELINE_KEYS = {
    "trace_id",
    "cif_dir",
    "out_dir",
    "name",
    "material_system",
    "formula",
    "required_pairs",
    "qlip_pair_mode",
    "qlip_pair_cutoff",
    "runtime_profile",
    "max_cifs",
    "max_distances_per_pair",
    "max_pairs_per_pair",
    "allow_fallback_precompiled",
    "fit",
    "covalent",
    "calibration",
    "filters",
    "publish",
    "timeout_seconds",
    "dry_run",
    "debug",
}
_PACKAGE_KEYS = {
    "trace_id",
    "run_root",
    "spp_root",
    "calibration_json",
    "out_dir",
    "name",
    "include_registry_snapshot",
    "debug",
}
_CHECK_KEYS = {"trace_id", "spp_root", "strict", "debug"}
_PUBLISH_KEYS = {
    "trace_id",
    "kind",
    "artifact_root",
    "qlip_outputs_path",
    "name",
    "overwrite",
    "strict_compat",
    "copy_mode",
    "set_latest",
    "debug",
}

_FIT_FIELDS = {
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
_CALIB_FIELDS = {
    "score_method",
    "mode",
    "target",
    "q",
    "max_calib",
    "convention",
    "min_lambda",
    "max_lambda",
    "bandpass",
}
_FILTER_FIELDS = {"meta_csv", "property_filter", "property_mode"}


def _apply_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[_ALIASES.get(key, key)] = value
    return out


def _unwrap_arguments(raw: dict[str, Any]) -> dict[str, Any]:
    if "arguments" in raw and isinstance(raw["arguments"], dict):
        return deepcopy(raw["arguments"])
    return deepcopy(raw)


def normalize_spp_arguments(tool_name: str, raw_arguments: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = _apply_aliases(_unwrap_arguments(raw_arguments))
    warnings: list[dict[str, Any]] = []

    if tool_name == "spp.run_pipeline":
        fit = dict(payload.get("fit", {})) if isinstance(payload.get("fit"), dict) else {}
        calibration = dict(payload.get("calibration", {})) if isinstance(payload.get("calibration"), dict) else {}
        filters = dict(payload.get("filters", {})) if isinstance(payload.get("filters"), dict) else {}
        publish = dict(payload.get("publish", {})) if isinstance(payload.get("publish"), dict) else {}

        hoisted_keys: list[str] = []
        for key in list(payload.keys()):
            if key in _FIT_FIELDS and key not in fit:
                fit[key] = payload.pop(key)
                hoisted_keys.append(key)
            elif key in _CALIB_FIELDS and key not in calibration:
                calibration[key] = payload.pop(key)
                hoisted_keys.append(key)
            elif key in _FILTER_FIELDS and key not in filters:
                filters[key] = payload.pop(key)
                hoisted_keys.append(key)
            elif key == "publish_to" and "publish_to" not in publish:
                publish["publish_to"] = payload.pop(key)
                hoisted_keys.append(key)
        if fit:
            payload["fit"] = fit
        if calibration:
            payload["calibration"] = calibration
        if filters:
            payload["filters"] = filters
        if publish:
            payload["publish"] = publish
        if hoisted_keys:
            warnings.append(
                {
                    "code": "fields_hoisted",
                    "message": "Top-level fields were hoisted into nested blocks.",
                    "path": None,
                    "dropped_keys": sorted(hoisted_keys),
                }
            )
        allowed = _RUN_PIPELINE_KEYS
    elif tool_name == "spp.package_for_qlip":
        allowed = _PACKAGE_KEYS
    elif tool_name == "spp.check_compat":
        allowed = _CHECK_KEYS
    elif tool_name == "spp.publish_to_qlip_outputs":
        allowed = _PUBLISH_KEYS
    else:
        return payload, warnings

    unknown = sorted([k for k in payload.keys() if k not in allowed])
    for key in unknown:
        payload.pop(key, None)
    if unknown:
        warnings.append(
            {
                "code": "unknown_key_filtered",
                "message": "Unknown keys were dropped for tolerant input normalization.",
                "path": None,
                "dropped_keys": unknown,
            }
        )
    return payload, warnings
