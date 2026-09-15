from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline
from sok_llm_orchestrator.structures.prototype_scaffold import (
    ideal_prototype_structure,
    prototype_orbit_solution_from_request,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "benchmarks" / "full_100_seeded_20260626" / "prototype_orbit_variable_spp_30_smoke_manifest.csv"
DEFAULT_OUT_ROOT = Path(
    r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs"
    r"\prototype_orbit_variable_spp_30_smoke_20260704"
)
VARIABLE_SPP_MODE = "prototype_orbit_variable_spp_qlip"
FIXED_ORBIT_MODE = "prototype_orbit_qlip"


_THREE_ROW_SCRIPT = Path(__file__).with_name("run_prototype_orbit_variable_spp_qlip_smoke.py")
_THREE_ROW_SPEC = importlib.util.spec_from_file_location("prototype_orbit_variable_spp_three_smoke", _THREE_ROW_SCRIPT)
if _THREE_ROW_SPEC is None or _THREE_ROW_SPEC.loader is None:
    raise RuntimeError(f"Unable to load {_THREE_ROW_SCRIPT}")
_THREE_ROW_MODULE = importlib.util.module_from_spec(_THREE_ROW_SPEC)
_THREE_ROW_SPEC.loader.exec_module(_THREE_ROW_MODULE)
build_spp_preflight = _THREE_ROW_MODULE.build_spp_preflight


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _settings_for_workspace(workspace: Path, pot_dir: Path | None) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workspace
    read_roots = [workspace.resolve(), REPO_ROOT.resolve()]
    if pot_dir is not None:
        read_roots.append(pot_dir.resolve())
        settings.qlip_allowed_path_roots = [*settings.qlip_allowed_path_roots, pot_dir.resolve()]
    settings.allowed_read_roots = read_roots
    settings.allowed_write_roots = [workspace.resolve()]
    return settings


def _load_rows(manifest: Path, max_rows: int) -> list[dict[str, Any]]:
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[:max_rows]


def _task_spec(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_text": f"Generate {row['formula']} as a {row['target_family']} prototype orbit validation smoke row.",
        "composition_target": row["formula"],
        "target_space_group": row["requested_space_group"],
        "target_space_group_number": int(row["requested_space_group_number"]),
        "target_crystal_system": row["requested_crystal_system"],
        "target_structure_family": row["target_family"],
        "prototype": row["target_family"],
    }


def _pipeline_overrides(row: dict[str, Any], workspace: Path) -> dict[str, Any]:
    regularisation_dir = workspace / "regularisation_spp"
    regularisation_dir.mkdir(parents=True, exist_ok=True)
    return {
        "active_symmetry_mode": row["requested_mode"],
        "allow_qlip_without_spp": True,
        "allow_partial_spp_guidance": True,
        "spp_regularisation_dir": str(regularisation_dir),
        "spp_regularisation_weight": 1.0,
        "spp_missing_pair_policy": "soft_repulsive",
    }


def _supported(row: dict[str, Any]) -> bool:
    try:
        ideal_prototype_structure(row["target_family"], row["formula"])
    except Exception:  # noqa: BLE001
        return False
    return True


def _request_mutator(preflight: dict[str, Any], preflight_path: Path, requested_mode: str):
    def _mutate(request: dict[str, Any]) -> dict[str, Any]:
        context = request.setdefault("context", {})
        if isinstance(context, dict) and preflight.get("pot_dir"):
            context["pot_root"] = str(preflight["pot_dir"])
        sites = request.setdefault("problem", {}).setdefault("design_space", {}).setdefault("sites", {})
        if isinstance(sites, dict):
            sites["requested_mode"] = requested_mode
            sites["spp_source"] = str(preflight.get("source_type") or "unavailable")
            sites["spp_source_type"] = str(preflight.get("source_type") or "unavailable")
            sites["spp_pot_dir"] = preflight.get("pot_dir")
            sites["spp_preflight_path"] = str(preflight_path)
            sites["spp_preflight_final_status"] = preflight.get("final_status")
            sites["required_pairs"] = list(preflight.get("required_pairs") or [])
            sites["loaded_pair_count"] = int(preflight.get("loaded_pair_count") or 0)
            sites["missing_pairs"] = list(preflight.get("missing_pairs") or [])
            if requested_mode == VARIABLE_SPP_MODE:
                sites["site_mode"] = "prototype_orbit_variable"
                solution = prototype_orbit_solution_from_request(request)
                if solution is not None:
                    sites["selected_species_by_orbit"] = solution.selected_species_by_orbit or {}
                    sites["selected_candidate_id"] = solution.selected_candidate_id
                    sites["objective_value"] = solution.objective_value
                    sites["spp_scoring_status"] = solution.spp_scoring_status
                    sites["spp_objective_enabled"] = solution.spp_scoring_status in {"scored", "test_fixture"}
                    sites["spp_source"] = solution.spp_source
                    sites["spp_source_type"] = solution.spp_source_type
                    sites["spp_pot_dir"] = solution.spp_pot_dir
                    sites["spp_fallback_reason"] = solution.spp_fallback_reason
                    sites["selected_pair_score_breakdown"] = solution.selected_pair_score_breakdown or []
        return request

    return _mutate


def _canonical_element(symbol: str) -> str:
    stripped = str(symbol).strip()
    return stripped[:1].upper() + stripped[1:].lower() if stripped else stripped


def _canonical_pair(pair: str) -> str:
    parts = [part for part in str(pair).replace("_", "-").split("-") if part]
    return "-".join(sorted((_canonical_element(part) for part in parts), key=str.lower)) if len(parts) == 2 else str(pair)


def _load_pot_curves(pot_dir: Path | None) -> dict[str, list[tuple[float, float]]]:
    if pot_dir is None or not pot_dir.is_dir():
        return {}
    curves: dict[str, list[tuple[float, float]]] = {}
    for pot_file in pot_dir.rglob("*.POT"):
        points: list[tuple[float, float]] = []
        for line in pot_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.replace(",", " ").split()
            if len(parts) < 2:
                continue
            try:
                points.append((float(parts[0]), float(parts[1])))
            except ValueError:
                continue
        if points:
            curves[_canonical_pair(pot_file.stem)] = sorted(points)
    return curves


def _interpolate(curve: list[tuple[float, float]], distance: float) -> float:
    if len(curve) == 1 or distance <= curve[0][0]:
        return float(curve[0][1])
    for (left_distance, left_value), (right_distance, right_value) in zip(curve, curve[1:]):
        if distance <= right_distance:
            span = right_distance - left_distance
            return float(right_value) if abs(span) < 1e-12 else float(left_value + (distance - left_distance) * (right_value - left_value) / span)
    return float(curve[-1][1])


def _score_cif(cif_path: Path, curves: dict[str, list[tuple[float, float]]]) -> dict[str, Any]:
    structure = Structure.from_file(cif_path)
    score = 0.0
    missing: set[str] = set()
    breakdown: list[dict[str, Any]] = []
    for left_index, left_site in enumerate(structure):
        for right_index in range(left_index + 1, len(structure)):
            right_site = structure[right_index]
            pair = _canonical_pair(f"{left_site.specie}-{right_site.specie}")
            curve = curves.get(pair)
            if curve is None:
                missing.add(pair)
                continue
            distance = float(structure.get_distance(left_index, right_index))
            pair_score = _interpolate(curve, distance)
            score += pair_score
            breakdown.append({"site_indices": [left_index, right_index], "pair": pair, "distance": distance, "score": pair_score})
    if missing:
        return {"status": "partial", "objective_value": None, "missing_pairs": sorted(missing), "pair_score_breakdown": breakdown}
    return {"status": "scored", "objective_value": score, "missing_pairs": [], "pair_score_breakdown": breakdown}


def _formula_satisfied(cif_path: Path, target_formula: str) -> bool | None:
    if not cif_path.is_file():
        return None
    try:
        actual = Structure.from_file(cif_path).composition.reduced_composition
        target = Composition(target_formula).reduced_composition
    except Exception:  # noqa: BLE001
        return None
    return actual == target


def _update_artifacts_for_fixed_scoring(artifacts: Path, score: dict[str, Any], preflight: dict[str, Any], row: dict[str, Any]) -> None:
    for name in ("symmetry_trace.json", "orbit_solution.json"):
        path = artifacts / name
        payload = _read_json(path)
        if not payload:
            continue
        payload["requested_mode"] = row["requested_mode"]
        payload["actual_mode"] = FIXED_ORBIT_MODE
        payload["validation_tier"] = "fixed_orbit_scored" if score["status"] == "scored" else "fixed_orbit_unscored"
        payload["spp_scoring_status"] = score["status"]
        payload["spp_source_type"] = preflight.get("source_type")
        payload["spp_pot_dir"] = preflight.get("pot_dir")
        payload["objective_value"] = score["objective_value"]
        payload["missing_pairs"] = score["missing_pairs"]
        payload["selected_pair_score_breakdown"] = score["pair_score_breakdown"]
        payload["formula_satisfied"] = payload.get("formula_satisfied")
        _write_json(path, payload)
    candidates_path = artifacts / "orbit_candidates.json"
    if not candidates_path.exists():
        _write_json(
            candidates_path,
            {
                "schema_version": "prototype_scaffold_fixed_orbit_candidates.v1",
                "mode": FIXED_ORBIT_MODE,
                "formula": row["formula"],
                "family": row["target_family"],
                "candidates": [],
                "spp_scoring_status": score["status"],
                "objective_value": score["objective_value"],
                "missing_pairs": score["missing_pairs"],
                "pair_score_breakdown": score["pair_score_breakdown"],
                "selection_note": "fixed prototype orbit assignment scored after scaffold generation; not variable orbit optimization",
            },
        )


def _validation_tier(row: dict[str, Any], trace: dict[str, Any], score: dict[str, Any] | None) -> str:
    if row["requested_mode"] == VARIABLE_SPP_MODE:
        return "variable_spp_scored" if trace.get("spp_scoring_status") == "scored" and trace.get("objective_value") is not None else "failed"
    if row["requested_mode"] == FIXED_ORBIT_MODE:
        return "fixed_orbit_scored" if score and score.get("status") == "scored" else "fixed_orbit_unscored"
    return "scaffold_output"


def run_smoke(
    *,
    manifest: Path = DEFAULT_MANIFEST,
    out_root: Path = DEFAULT_OUT_ROOT,
    pot_dir: Path | None,
    require_real_spp: bool,
    allow_spp_unavailable: bool,
    max_rows: int,
    strict_supported_only: bool,
) -> dict[str, Any]:
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    rows = _load_rows(manifest, max_rows=max_rows)
    curves_by_dir: dict[str, dict[str, list[tuple[float, float]]]] = {}
    summary_rows: list[dict[str, Any]] = []
    generated_rows: list[dict[str, Any]] = []
    real_spp_failures = 0
    for row in rows:
        prompt_id = row["prompt_id"]
        workspace = out_root / prompt_id
        workspace.mkdir(parents=True, exist_ok=True)
        task_spec = _task_spec(row)
        _write_json(workspace / "task_spec.json", task_spec)
        supported = _supported(row)
        if not supported and strict_supported_only:
            summary_rows.append(_unsupported_summary_row(row, workspace, "strict_supported_only_excluded"))
            continue
        settings = _settings_for_workspace(workspace, pot_dir)
        preflight_case = {
            "case_id": prompt_id,
            "formula": row["formula"],
            "family": row["target_family"],
            "space_group": row["requested_space_group"],
            "space_group_number": int(row["requested_space_group_number"]),
            "crystal_system": row["requested_crystal_system"],
        }
        preflight = build_spp_preflight(
            case=preflight_case,
            settings=settings,
            workspace=workspace,
            pot_dir=pot_dir,
            run_service_probes=True,
        )
        preflight_path = workspace / "spp_preflight.json"
        _write_json(preflight_path, preflight)
        if require_real_spp and preflight["final_status"] != "ready":
            real_spp_failures += 1
            summary_rows.append(_failed_spp_summary_row(row, workspace, preflight))
            continue
        if preflight["final_status"] != "ready" and not allow_spp_unavailable:
            summary_rows.append(_failed_spp_summary_row(row, workspace, preflight))
            continue
        try:
            result = run_csp_pipeline(
                query=None,
                with_spp=True,
                mode="stub",
                workspace=workspace,
                settings=settings,
                qlip_request_mutator=_request_mutator(preflight, preflight_path, row["requested_mode"]),
                execution_overrides=_pipeline_overrides(row, workspace),
                task_spec_payload=task_spec,
            )
        except Exception as exc:  # noqa: BLE001
            summary_rows.append(_exception_summary_row(row, workspace, preflight, exc))
            continue
        artifacts = Path(result.run_dir) / "artifacts"
        shutil.copyfile(preflight_path, artifacts / "spp_preflight.json")
        solution_cif = artifacts / "qlip" / "solution.cif"
        qlip_request = artifacts / "qlip_request.json"
        symmetry_trace = artifacts / "symmetry_trace.json"
        orbit_solution = artifacts / "orbit_solution.json"
        orbit_candidates = artifacts / "orbit_candidates.json"
        trace = _read_json(symmetry_trace)
        score: dict[str, Any] | None = None
        if row["requested_mode"] == FIXED_ORBIT_MODE and solution_cif.is_file():
            pot_root = preflight.get("pot_dir")
            curves = curves_by_dir.setdefault(str(pot_root), _load_pot_curves(Path(pot_root)) if pot_root else {})
            score = _score_cif(solution_cif, curves) if curves else {"status": "unavailable", "objective_value": None, "missing_pairs": preflight.get("missing_pairs", []), "pair_score_breakdown": []}
            _update_artifacts_for_fixed_scoring(artifacts, score, preflight, row)
            trace = _read_json(symmetry_trace)
        tier = _validation_tier(row, trace, score)
        formula_satisfied = _formula_satisfied(solution_cif, row["formula"])
        summary_row = {
            "prompt_id": prompt_id,
            "formula": row["formula"],
            "target_formula": row["formula"],
            "target_family": row["target_family"],
            "target_structure_family": row["target_family"],
            "target_space_group": row["requested_space_group"],
            "target_space_group_number": row["requested_space_group_number"],
            "target_crystal_system": row["requested_crystal_system"],
            "requested_mode": row["requested_mode"],
            "actual_mode": trace.get("active_symmetry_mode") or row["requested_mode"],
            "validation_tier": tier,
            "spp_scoring_status": (score or {}).get("status") or trace.get("spp_scoring_status"),
            "spp_source_type": preflight.get("source_type"),
            "objective_value": (score or {}).get("objective_value", trace.get("objective_value")),
            "missing_pairs": json.dumps((score or {}).get("missing_pairs", preflight.get("missing_pairs") or [])),
            "final_cif_source": trace.get("final_cif_source"),
            "formula_satisfied": formula_satisfied,
            "symmetry_closed": trace.get("symmetry_closed"),
            "pipeline_status": result.status,
            "cif_path": str(solution_cif) if solution_cif.is_file() else "",
            "run_dir": str(result.run_dir),
            "qlip_request": str(qlip_request),
            "symmetry_trace": str(symmetry_trace),
            "orbit_solution": str(orbit_solution),
            "orbit_candidates": str(orbit_candidates),
            "spp_preflight": str(artifacts / "spp_preflight.json"),
            "notes": row.get("notes", ""),
        }
        summary_rows.append(summary_row)
        if solution_cif.is_file():
            generated_rows.append(summary_row)
    manifest_dir = out_root / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = manifest_dir / "prototype_orbit_variable_spp_30_smoke_summary.csv"
    generated_csv = manifest_dir / "prototype_orbit_variable_spp_30_smoke_generated_manifest.csv"
    _write_csv(summary_csv, summary_rows)
    _write_csv(generated_csv, generated_rows)
    summary = {
        "schema_version": "prototype_orbit_variable_spp_30_smoke.v1",
        "out_root": str(out_root),
        "input_manifest": str(manifest),
        "summary_csv": str(summary_csv),
        "generated_manifest_csv": str(generated_csv),
        "intended_rows": len(rows),
        "generated_rows": len(generated_rows),
        "unsupported_rows": sum(1 for item in summary_rows if item.get("validation_tier") == "unsupported"),
        "failed_rows": sum(1 for item in summary_rows if item.get("validation_tier") == "failed"),
        "real_spp_failures": real_spp_failures,
        "rows": summary_rows,
    }
    _write_json(out_root / "targeted_smoke_manifest.json", summary)
    if real_spp_failures and require_real_spp:
        raise SystemExit(f"{real_spp_failures} rows lacked required real SPP POT coverage; see {summary_csv}")
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _unsupported_summary_row(row: dict[str, Any], workspace: Path, reason: str) -> dict[str, Any]:
    return {
        "prompt_id": row["prompt_id"],
        "formula": row["formula"],
        "target_formula": row["formula"],
        "target_family": row["target_family"],
        "target_structure_family": row["target_family"],
        "target_space_group": row["requested_space_group"],
        "target_space_group_number": row["requested_space_group_number"],
        "target_crystal_system": row["requested_crystal_system"],
        "requested_mode": row["requested_mode"],
        "actual_mode": "unsupported",
        "validation_tier": "unsupported",
        "spp_scoring_status": "unavailable",
        "spp_source_type": "unavailable",
        "objective_value": None,
        "missing_pairs": "[]",
        "final_cif_source": None,
        "formula_satisfied": None,
        "symmetry_closed": None,
        "pipeline_status": "UNSUPPORTED",
        "cif_path": "",
        "run_dir": str(workspace),
        "qlip_request": "",
        "symmetry_trace": "",
        "orbit_solution": "",
        "orbit_candidates": "",
        "spp_preflight": "",
        "notes": f"{row.get('notes', '')}; {reason}".strip("; "),
    }


def _failed_spp_summary_row(row: dict[str, Any], workspace: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    payload = _unsupported_summary_row(row, workspace, str(preflight.get("failure_reason") or "spp_unavailable"))
    payload["actual_mode"] = row["requested_mode"]
    payload["validation_tier"] = "failed"
    payload["pipeline_status"] = "FAILED_SPP_PREFLIGHT"
    payload["missing_pairs"] = json.dumps(preflight.get("missing_pairs") or [])
    payload["spp_preflight"] = str(workspace / "spp_preflight.json")
    return payload


def _exception_summary_row(row: dict[str, Any], workspace: Path, preflight: dict[str, Any], exc: Exception) -> dict[str, Any]:
    payload = _failed_spp_summary_row(row, workspace, preflight)
    payload["pipeline_status"] = "FAILED_EXCEPTION"
    payload["notes"] = f"{row.get('notes', '')}; {type(exc).__name__}: {exc}".strip("; ")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 30-row prototype orbit variable/fixed SPP validation smoke.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--pot-dir", type=Path, default=None)
    parser.add_argument("--require-real-spp", action="store_true")
    parser.add_argument("--allow-spp-unavailable", action="store_true")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--max-rows", type=int, default=30)
    parser.add_argument("--strict-supported-only", action="store_true")
    args = parser.parse_args()
    summary = run_smoke(
        manifest=args.manifest,
        out_root=args.out_root,
        pot_dir=args.pot_dir,
        require_real_spp=args.require_real_spp,
        allow_spp_unavailable=args.allow_spp_unavailable,
        max_rows=args.max_rows,
        strict_supported_only=args.strict_supported_only,
    )
    print(json.dumps({key: summary[key] for key in ("out_root", "intended_rows", "generated_rows", "failed_rows")}, indent=2))


if __name__ == "__main__":
    main()
