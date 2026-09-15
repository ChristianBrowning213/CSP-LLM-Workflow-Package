from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _error(code: str, message: str, path: str | Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        payload["path"] = str(path)
    return payload


def _canonical_pair(a: str, b: str) -> str:
    parts = sorted([a.strip().title(), b.strip().title()], key=lambda value: value.lower())
    return f"{parts[0]}-{parts[1]}"


def required_pairs_from_formula(formula: str | None) -> list[str]:
    """Return unordered self/cross element pairs required by a formula."""
    if not isinstance(formula, str) or not formula.strip():
        return []
    elements = []
    for match in re.finditer(r"([A-Z][a-z]?)(?:[0-9]+(?:\.[0-9]+)?)?", formula):
        element = match.group(1)
        if element not in elements:
            elements.append(element)
    pairs = {
        _canonical_pair(elements[i], elements[j])
        for i in range(len(elements))
        for j in range(i, len(elements))
    }
    return sorted(pairs, key=str.lower)


def _normalize_required_pairs(required_pairs: list[str] | tuple[str, ...] | None) -> list[str]:
    out = set()
    for item in required_pairs or []:
        if not isinstance(item, str) or "-" not in item:
            continue
        left, right = item.split("-", 1)
        left = left.strip()
        right = right.strip()
        if left and right:
            out.add(_canonical_pair(left, right))
    return sorted(out, key=str.lower)


def _pair_key(pair: str) -> str:
    if "-" not in pair:
        return pair.strip().lower()
    left, right = pair.split("-", 1)
    return "-".join(sorted([left.strip().lower(), right.strip().lower()]))


def _available_pairs_from_pot_root(spp_root: Path) -> set[str]:
    pairs: set[str] = set()
    if not spp_root.is_dir():
        return pairs
    for pot_file in spp_root.rglob("*.POT"):
        if "-" not in pot_file.stem:
            continue
        pairs.add(_pair_key(pot_file.stem))
    return pairs


def _coverage_error(
    *,
    run_path: Path,
    required_pairs: list[str],
    available_pairs: set[str],
    nearest_candidate_roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    missing_pairs = [pair for pair in required_pairs if _pair_key(pair) not in available_pairs]
    message = "Published SPP POT root does not cover required pair coverage: " + ", ".join(missing_pairs)
    error = _error("pot_pair_coverage_missing", message, run_path / "spp_root")
    error["required_pairs"] = required_pairs
    error["missing_pairs"] = missing_pairs
    error["available_pair_count"] = len(available_pairs)
    if nearest_candidate_roots is not None:
        error["nearest_candidate_roots"] = nearest_candidate_roots
    return error


def _parse_compat_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")

    def _number(label: str) -> int | None:
        match = re.search(rf"^{re.escape(label)}:\s*(\d+)\s*$", text, flags=re.MULTILINE)
        return int(match.group(1)) if match else None

    checked = _number("POT files checked")
    passed = _number("Passed")
    failed = _number("Failed")
    parsed: dict[str, Any] = {}
    if checked is not None:
        parsed["checked"] = checked
    if passed is not None:
        parsed["passed"] = passed
    if failed is not None:
        parsed["failed"] = failed
    parsed["strict"] = True
    return parsed


def _compat_from_publish_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = _load_json(path)
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    compat = checks.get("compat") if isinstance(checks.get("compat"), dict) else {}
    out: dict[str, Any] = {}
    for key in ("checked", "passed", "failed"):
        value = compat.get(key)
        if isinstance(value, int):
            out[key] = value
    if isinstance(compat.get("strict"), bool):
        out["strict"] = compat["strict"]
    return out


def _manifest_paths_missing(manifest_path: Path, spp_root: Path) -> int:
    if not manifest_path.is_file():
        return 0
    manifest = _load_json(manifest_path)
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list):
        return 0
    missing = 0
    for item in pairs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        if not (spp_root / item["path"]).is_file():
            missing += 1
    return missing


def _resolve_published_run(
    qlip_outputs_root: str | Path | None,
    published_spp_rel: str | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    if qlip_outputs_root is None:
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root was not provided.")]
    qlip_outputs = Path(qlip_outputs_root).resolve()
    if not qlip_outputs.is_dir():
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root does not exist.", qlip_outputs)]

    if published_spp_rel:
        run_path = qlip_outputs / published_spp_rel
        if run_path.is_dir():
            return run_path, []
        return None, [_error("pot_root_missing", "Published SPP run path does not exist.", run_path)]

    latest_path = qlip_outputs / "SPP" / "latest.txt"
    if not latest_path.is_file():
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs/SPP/latest.txt does not exist.", latest_path)]
    latest_rel = latest_path.read_text(encoding="utf-8").strip()
    if not latest_rel:
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs/SPP/latest.txt is empty.", latest_path)]
    run_path = qlip_outputs / latest_rel
    if not run_path.is_dir():
        return None, [_error("pot_root_missing", "Latest SPP run path does not exist.", run_path)]
    return run_path, []


def _candidate_run_paths(qlip_outputs_root: Path, published_spp_rel: str | None) -> list[Path]:
    paths: list[Path] = []
    if published_spp_rel:
        paths.append(qlip_outputs_root / published_spp_rel)
    latest_path = qlip_outputs_root / "SPP" / "latest.txt"
    if latest_path.is_file():
        latest_rel = latest_path.read_text(encoding="utf-8").strip()
        if latest_rel:
            paths.append(qlip_outputs_root / latest_rel)
    runs_root = qlip_outputs_root / "SPP" / "runs"
    if runs_root.is_dir():
        paths.extend(sorted((item for item in runs_root.iterdir() if item.is_dir()), reverse=True))

    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _select_published_run_for_pairs(
    *,
    qlip_outputs_root: str | Path | None,
    published_spp_rel: str | None,
    required_pairs: list[str],
) -> tuple[Path | None, list[dict[str, Any]], list[dict[str, Any]]]:
    if not required_pairs:
        run_path, errors = _resolve_published_run(qlip_outputs_root, published_spp_rel)
        return run_path, errors, []

    if qlip_outputs_root is None:
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root was not provided.")], []
    qlip_outputs = Path(qlip_outputs_root).resolve()
    if not qlip_outputs.is_dir():
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root does not exist.", qlip_outputs)], []

    candidates: list[dict[str, Any]] = []
    for run_path in _candidate_run_paths(qlip_outputs, published_spp_rel):
        spp_root = run_path / "spp_root"
        available_pairs = _available_pairs_from_pot_root(spp_root)
        missing_pairs = [pair for pair in required_pairs if _pair_key(pair) not in available_pairs]
        candidate = {
            "run_path": str(run_path),
            "pot_root": str(spp_root),
            "available_pair_count": len(available_pairs),
            "covered_pairs": [pair for pair in required_pairs if _pair_key(pair) in available_pairs],
            "missing_pairs": missing_pairs,
        }
        candidates.append(candidate)
        if run_path.is_dir() and not missing_pairs:
            return run_path, [], candidates

    if not candidates:
        return None, [_error("qlip_outputs_missing", "No published SPP runs were found.", qlip_outputs / "SPP" / "runs")], []
    best = sorted(candidates, key=lambda item: (len(item["missing_pairs"]), -int(item["available_pair_count"])))[0]
    error = _error("pot_pair_coverage_missing", "No published SPP POT root covers all required pairs.", best["pot_root"])
    error["required_pairs"] = required_pairs
    error["missing_pairs"] = best["missing_pairs"]
    error["available_pair_count"] = best["available_pair_count"]
    error["nearest_candidate_roots"] = candidates[:5]
    return Path(str(best["run_path"])), [error], candidates


def discover_published_spp_pot_root(
    *,
    qlip_outputs_root: str | Path | None,
    published_spp_rel: str | None = None,
    required_pairs: list[str] | tuple[str, ...] | None = None,
    material_system: str | None = None,
) -> dict[str, Any]:
    """Locate and validate a real published QLIP_Outputs SPP POT root."""
    normalized_required_pairs = _normalize_required_pairs(required_pairs)
    if not normalized_required_pairs:
        normalized_required_pairs = required_pairs_from_formula(material_system)
    run_path, errors, candidate_roots = _select_published_run_for_pairs(
        qlip_outputs_root=qlip_outputs_root,
        published_spp_rel=published_spp_rel,
        required_pairs=normalized_required_pairs,
    )
    if run_path is None:
        return {
            "ok": False,
            "run_path": None,
            "pot_root": None,
            "pot_count": 0,
            "compat": {},
            "artifact_refs": [],
            "required_pairs": normalized_required_pairs,
            "missing_pairs": normalized_required_pairs,
            "available_pair_count": 0,
            "nearest_candidate_roots": candidate_roots,
            "errors": errors,
        }

    pot_root = run_path / "spp_root"
    manifest_path = run_path / "manifest.json"
    compat_report_path = run_path / "compat_report.txt"
    publish_meta_path = run_path / "publish_meta.json"
    errors = []
    if not pot_root.is_dir():
        errors.append(_error("pot_root_missing", "Published SPP run is missing spp_root.", pot_root))
    pot_count = len(list(pot_root.rglob("*.POT"))) if pot_root.is_dir() else 0
    if pot_root.is_dir() and pot_count == 0:
        errors.append(_error("pot_root_no_pot_files", "Published SPP root contains no .POT files.", pot_root))
    available_pairs = _available_pairs_from_pot_root(pot_root)
    missing_pairs = [
        pair for pair in normalized_required_pairs if _pair_key(pair) not in available_pairs
    ]
    if missing_pairs:
        errors.append(
            _coverage_error(
                run_path=run_path,
                required_pairs=normalized_required_pairs,
                available_pairs=available_pairs,
                nearest_candidate_roots=candidate_roots[:5],
            )
        )
    if not manifest_path.is_file():
        errors.append(_error("pot_root_missing", "Published SPP run is missing manifest.json.", manifest_path))

    compat = _compat_from_publish_meta(publish_meta_path)
    compat_from_report = _parse_compat_report(compat_report_path)
    compat = {**compat_from_report, **compat}
    failed = compat.get("failed")
    if isinstance(failed, int) and failed > 0:
        errors.append(_error("pot_compat_failed", f"Published SPP POT compatibility failed for {failed} files.", compat_report_path))

    missing_manifest_paths = _manifest_paths_missing(manifest_path, pot_root)
    if missing_manifest_paths:
        errors.append(_error("pot_root_missing", f"Manifest references {missing_manifest_paths} missing POT files.", manifest_path))

    artifact_refs = [
        {"ref_name": "pot_root", "value": str(pot_root), "kind": "directory"},
        {"ref_name": "spp_manifest_json", "value": str(manifest_path), "kind": "file"},
    ]
    if compat_report_path.is_file():
        artifact_refs.append({"ref_name": "spp_compat_report_txt", "value": str(compat_report_path), "kind": "file"})
    if publish_meta_path.is_file():
        artifact_refs.append({"ref_name": "spp_publish_meta_json", "value": str(publish_meta_path), "kind": "file"})

    return {
        "ok": not errors,
        "run_path": str(run_path),
        "pot_root": str(pot_root) if pot_root.is_dir() else None,
        "pot_count": pot_count,
        "compat": compat,
        "artifact_refs": artifact_refs,
        "required_pairs": normalized_required_pairs,
        "missing_pairs": missing_pairs,
        "available_pair_count": len(available_pairs),
        "nearest_candidate_roots": candidate_roots[:5],
        "errors": errors,
    }


def create_spp_guidance_package(
    spp_run_root: str | Path,
    calibration_json: str | Path | None,
    out_dir: str | Path,
    name: str,
    qlip_outputs_root: str | Path | None = None,
    published_spp_rel: str | None = None,
    required_pairs: list[str] | tuple[str, ...] | None = None,
    material_system: str | None = None,
) -> dict[str, Any]:
    """Create a QLIP guidance handoff package from real SPP run artifacts."""
    run_root = Path(spp_run_root)
    if calibration_json is not None:
        calibration_path = Path(calibration_json)
    else:
        calibration_path = run_root / "calibrate" / "calibration.json"
        if not calibration_path.exists() and (run_root / "calibration.json").exists():
            calibration_path = run_root / "calibration.json"
    output_root = Path(out_dir)

    if not run_root.exists():
        raise FileNotFoundError(f"SPP run root does not exist: {run_root}")
    if not calibration_path.exists():
        raise FileNotFoundError(f"Calibration file does not exist: {calibration_path}")

    package_json_path = run_root / "package" / "package.json"
    if not package_json_path.exists():
        package_json_path = run_root / "package.json"
    if not package_json_path.exists():
        raise FileNotFoundError(f"package.json not found in SPP run root: {run_root}")

    bundle_name = f"{name}_bundle" if name else "_bundle"
    bundle_root = output_root / bundle_name
    guidance_package_path = bundle_root / "guidance_package"
    guidance_package_path.mkdir(parents=True, exist_ok=True)

    fit_spp_root = run_root / "fit" / "spp_root"
    if not fit_spp_root.exists() and (run_root / "fit_spp").exists():
        fit_spp_root = run_root / "fit_spp"
    scaled_spp_root = run_root / "calibrate" / "scaled_spp_root"
    if not scaled_spp_root.exists() and (run_root / "scaled_spp").exists():
        scaled_spp_root = run_root / "scaled_spp"
    final_bundle = run_root.parents[1] / "Final_QLIP_output" / run_root.name if len(run_root.parents) > 1 else run_root / "final_bundle"
    if (run_root / "final_bundle").exists():
        final_bundle = run_root / "final_bundle"
    log_path = run_root / "logs" / "timings.json"
    if not log_path.exists() and (run_root / "run.log").exists():
        log_path = run_root / "run.log"

    pot_handoff = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs_root,
        published_spp_rel=published_spp_rel,
        required_pairs=required_pairs,
        material_system=material_system,
    )
    compat_evidence = pot_handoff.get("compat") if isinstance(pot_handoff.get("compat"), dict) else {}
    pot_root = pot_handoff.get("pot_root") if isinstance(pot_handoff.get("pot_root"), str) else None
    qlip_solve_compatible = bool(pot_handoff.get("ok") and pot_root)
    missing_pairs = pot_handoff.get("missing_pairs") if isinstance(pot_handoff.get("missing_pairs"), list) else []
    required_pairs_out = pot_handoff.get("required_pairs") if isinstance(pot_handoff.get("required_pairs"), list) else []
    if qlip_solve_compatible:
        missing = []
    elif missing_pairs:
        missing = ["pot_pair_coverage"]
    else:
        missing = ["context.pot_root"]
    reason = (
        "Real published SPP POT root found and validated."
        if qlip_solve_compatible
        else (
            "No published SPP POT root covers required pairs: " + ", ".join(missing_pairs)
            if missing_pairs
            else "SPP outputs are statistical guidance artifacts; no native QLIP POT root is available."
        )
    )
    compatibility = {
        "qlip_version": "1.0",
        "spp_maker_version": "runtime",
        "qlip_solve_compatible": qlip_solve_compatible,
        "reason": reason,
        "missing": missing,
        "required_pairs": required_pairs_out,
        "missing_pairs": missing_pairs,
        "available_pair_count": pot_handoff.get("available_pair_count", 0),
        "pot_compat": compat_evidence,
        "recommended_next": "Add QLIP native SPP guidance mode or implement real POT export.",
        "accepted_parameters": ["spp_package_path"],
        "removed_parameters": [
            "pairs_policy",
            "oob_policy",
            "missing_pair_policy",
            "lambda_override",
            "convention_override",
            "r_cut",
            "top_k_breakdown",
            "weighting_profile",
            "structure_perturbation_profile",
            "base_weight_scale",
            "guidance_weight_scale",
            "template_seed_profile",
            "lattice_candidate_profile",
            "symmetry_relaxation_profile",
            "ordering_perturbation_profile",
        ],
    }
    files = {
        "package_manifest.json": {
            "spp_run_root": str(run_root),
            "calibration_json": str(calibration_path),
            "fit_spp_root": str(fit_spp_root),
            "scaled_spp_root": str(scaled_spp_root),
            "final_bundle": str(final_bundle),
            "package_json": str(package_json_path),
            "log_path": str(log_path),
        },
        "calibration_refs.json": {
            "calibration_json": str(calibration_path),
            "calibration_data": _load_json(calibration_path),
        },
        "statistical_refs.json": {
            "fit_spp_root": str(fit_spp_root),
            "scaled_spp_root": str(scaled_spp_root),
            "final_bundle": str(final_bundle),
            "package_json": str(package_json_path),
            "log_path": str(log_path),
        },
        "compatibility.json": compatibility,
        "pot_handoff.json": {
            "context": {"pot_root": pot_root} if pot_root else {},
            "summary": (
                f"Real published SPP POT root found with {pot_handoff.get('pot_count', 0)} .POT files."
                if qlip_solve_compatible
                else "No solve-compatible published SPP POT root was found."
            ),
            "published_spp_run_path": pot_handoff.get("run_path"),
            "pot_count": pot_handoff.get("pot_count", 0),
            "required_pairs": required_pairs_out,
            "missing_pairs": missing_pairs,
            "available_pair_count": pot_handoff.get("available_pair_count", 0),
            "nearest_candidate_roots": pot_handoff.get("nearest_candidate_roots", []),
            "compat": compat_evidence,
            "artifact_refs": pot_handoff.get("artifact_refs", []),
            "errors": pot_handoff.get("errors", []),
        },
        "provenance.json": {
            "tool": "SPP-Maker-QLIP",
            "source": str(run_root),
            "calibration_source": str(calibration_path),
        },
    }
    for filename, payload in files.items():
        (guidance_package_path / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    created_files = sorted(files)
    output_bytes = sum((guidance_package_path / filename).stat().st_size for filename in created_files)
    return {
        "guidance_package_path": str(guidance_package_path),
        "contents": created_files,
        "compatibility": compatibility,
        "context": {"pot_root": pot_root} if pot_root else {},
        "artifact_refs": pot_handoff.get("artifact_refs", []),
        "summary": (
            f"Real published SPP POT root found with {pot_handoff.get('pot_count', 0)} .POT files."
            if qlip_solve_compatible
            else (
                "No solve-compatible published SPP POT root covers required pairs: "
                + ", ".join(missing_pairs)
                if missing_pairs
                else "No solve-compatible published SPP POT root was found."
            )
        ),
        "errors": pot_handoff.get("errors", []),
        "required_pairs": required_pairs_out,
        "missing_pairs": missing_pairs,
        "available_pair_count": pot_handoff.get("available_pair_count", 0),
        "provenance": {
            "git_sha": None,
            "tool": "SPP-Maker-QLIP",
            "tool_version": "runtime",
            "params_hash": None,
            "content_hash": "runtime-hash",
        },
        "output_bytes": output_bytes,
    }
