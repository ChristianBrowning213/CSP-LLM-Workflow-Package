from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .schemas import assert_json_serializable, to_json_dict

QLIP_RECOVERY_SCHEMA_VERSION = "agentic_csp.qlip_recovery.v1"


def _safe_string(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return default


def _mapping_list(mapping: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = mapping.get(key)
    if not isinstance(value, list):
        return []
    return [to_json_dict(item) for item in value if isinstance(item, Mapping)]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _artifact_ref_map(step_result: Mapping[str, Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for item in _mapping_list(step_result, "artifact_refs"):
        ref_name = _safe_string(item, "ref_name")
        ref_value = _safe_string(item, "value")
        if ref_name and ref_value:
            refs[ref_name] = ref_value
    return refs


def _has_real_pot_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(candidate.is_file() for candidate in path.rglob("*.POT"))


def _pot_root_candidates(
    spp_step_result: Mapping[str, Any],
    package_step_result: Mapping[str, Any],
) -> list[Path]:
    spp_refs = _artifact_ref_map(spp_step_result)
    package_refs = _artifact_ref_map(package_step_result)
    candidates: list[Path] = []

    for ref_name in ("spp_bundle_path", "spp_final_bundle_path"):
        ref_value = package_refs.get(ref_name) or spp_refs.get(ref_name)
        if not ref_value:
            continue
        bundle_path = Path(ref_value)
        candidates.append(bundle_path / "spp_root")
        candidates.append(bundle_path)

    for ref_name in ("scaled_spp_root", "fit_spp_root", "spp_package_ref"):
        ref_value = spp_refs.get(ref_name)
        if ref_value:
            candidates.append(Path(ref_value))

    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(candidate)
    return unique_candidates


def _select_pot_root(
    spp_step_result: Mapping[str, Any],
    package_step_result: Mapping[str, Any],
) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    for candidate in _pot_root_candidates(spp_step_result, package_step_result):
        if not candidate.exists():
            warnings.append(f"missing_candidate:{candidate}")
            continue
        if not candidate.is_dir():
            warnings.append(f"not_a_directory:{candidate}")
            continue
        if _has_real_pot_files(candidate):
            return candidate, warnings
        warnings.append(f"no_pot_files:{candidate}")
    return None, warnings


def _remove_invalid_guidance_params(request: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    guidance = request.get("guidance")
    if not isinstance(guidance, list):
        return removed
    for item in guidance:
        if not isinstance(item, dict):
            continue
        if item.get("id") != "objective.energy_spp":
            continue
        params = item.get("params")
        if not isinstance(params, dict):
            item["params"] = {}
            continue
        # Keep only the minimal valid parameters for QLIP
        # Remove all SPP-specific parameters that are invalid for QLIP
        invalid_params = [
            key for key in params.keys()
            if isinstance(key, str) and key.strip() and key in [
                "missing_pair_policy", "oob_policy", "pairs_policy", "spp_package_path", "top_k_breakdown"
            ]
        ]
        removed.extend(invalid_params)
        # Keep empty object as valid QLIP guidance parameter
        item["params"] = {}
    return sorted(dict.fromkeys(removed))


def build_corrected_qlip_request_from_spp(
    *,
    invalid_request: Mapping[str, Any],
    spp_step_result: Mapping[str, Any],
    package_step_result: Mapping[str, Any],
    out_dir: str | Path,
) -> dict:
    if not isinstance(invalid_request, Mapping):
        msg = "invalid_request must be a mapping"
        raise TypeError(msg)
    if not isinstance(spp_step_result, Mapping):
        msg = "spp_step_result must be a mapping"
        raise TypeError(msg)
    if not isinstance(package_step_result, Mapping):
        msg = "package_step_result must be a mapping"
        raise TypeError(msg)

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    corrected_request = to_json_dict(invalid_request)
    removed_guidance_params = _remove_invalid_guidance_params(corrected_request)

    pot_root, warnings = _select_pot_root(spp_step_result, package_step_result)
    blocked_reason: str | None = None
    if pot_root is None:
        blocked_reason = "pot_root_unavailable"
    else:
        context = corrected_request.get("context")
        if not isinstance(context, dict):
            context = {}
            corrected_request["context"] = context
        context["pot_root"] = str(pot_root)

    corrected_request_path = root / "corrected_qlip_request.json"
    _write_json(corrected_request_path, corrected_request)

    result = {
        "schema_version": QLIP_RECOVERY_SCHEMA_VERSION,
        "status": "corrected" if pot_root is not None else "blocked",
        "corrected_request_path": str(corrected_request_path),
        "pot_root": str(pot_root) if pot_root is not None else None,
        "removed_guidance_params": removed_guidance_params,
        "warnings": warnings,
        "blocked_reason": blocked_reason,
    }
    assert_json_serializable(result)
    return result


__all__ = [
    "QLIP_RECOVERY_SCHEMA_VERSION",
    "build_corrected_qlip_request_from_spp",
]
