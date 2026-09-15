from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


DEFAULT_OUT_ROOT = Path(
    r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs"
    r"\prototype_orbit_variable_qlip_smoke_20260704"
)


CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "BaTiO3_perovskite_A_site_orbit",
        "prompt": "Generate BaTiO3 perovskite using variable orbit-level prototype scaffold QLIP.",
        "formula": "BaTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
    {
        "case_id": "CaTiO3_perovskite_A_site_orbit",
        "prompt": "Generate CaTiO3 perovskite using variable orbit-level prototype scaffold QLIP.",
        "formula": "CaTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
    {
        "case_id": "SrTiO3_perovskite_A_site_orbit",
        "prompt": "Generate SrTiO3 perovskite using variable orbit-level prototype scaffold QLIP.",
        "formula": "SrTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
)


def _settings_for_workspace(workspace: Path) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workspace
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    return settings


def _partial_spp_fallback(workspace: Path) -> dict[str, Any]:
    regularisation_dir = workspace / "regularisation_spp"
    regularisation_dir.mkdir(parents=True, exist_ok=True)
    return {
        "active_symmetry_mode": "prototype_orbit_variable_qlip",
        "allow_qlip_without_spp": True,
        "allow_partial_spp_guidance": True,
        "spp_regularisation_dir": str(regularisation_dir),
        "spp_regularisation_weight": 1.0,
        "spp_missing_pair_policy": "soft_repulsive",
    }


def _task_spec(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_text": case["prompt"],
        "composition_target": case["formula"],
        "target_space_group": case["space_group"],
        "target_space_group_number": case["space_group_number"],
        "target_crystal_system": case["crystal_system"],
        "target_structure_family": case["family"],
        "prototype": case["family"],
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_smoke(out_root: Path) -> dict[str, Any]:
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in CASES:
        workspace = out_root / case["case_id"]
        workspace.mkdir(parents=True, exist_ok=True)
        result = run_csp_pipeline(
            query=None,
            with_spp=True,
            mode="stub",
            workspace=workspace,
            settings=_settings_for_workspace(workspace),
            execution_overrides=_partial_spp_fallback(workspace),
            task_spec_payload=_task_spec(case),
        )
        artifacts = Path(result.run_dir) / "artifacts"
        solution_cif = artifacts / "qlip" / "solution.cif"
        qlip_request = artifacts / "qlip_request.json"
        symmetry_trace = artifacts / "symmetry_trace.json"
        orbit_solution = artifacts / "orbit_solution.json"
        orbit_candidates = artifacts / "orbit_candidates.json"
        trace_payload = _read_json(symmetry_trace)
        request_payload = _read_json(qlip_request)
        sites_payload = (
            request_payload.get("problem", {}).get("design_space", {}).get("sites", {})
            if isinstance(request_payload.get("problem"), dict)
            else {}
        )
        rows.append(
            {
                "prompt_id": case["case_id"],
                "benchmark_id": case["case_id"],
                "input_text": case["prompt"],
                "target_formula": case["formula"],
                "target_structure_family": case["family"],
                "target_space_group": case["space_group"],
                "target_space_group_number": case["space_group_number"],
                "target_crystal_system": case["crystal_system"],
                "cif_path": str(solution_cif),
                "run_dir": str(result.run_dir),
                "raw_run_dir": str(result.run_dir),
                "qlip_request": str(qlip_request),
                "symmetry_trace": str(symmetry_trace),
                "orbit_solution": str(orbit_solution),
                "orbit_candidates": str(orbit_candidates),
                "pipeline_status": result.status,
                "active_symmetry_mode": trace_payload.get("active_symmetry_mode"),
                "orbit_level_selection": trace_payload.get("orbit_level_selection"),
                "variable_orbit_selection": trace_payload.get("variable_orbit_selection"),
                "final_cif_source": trace_payload.get("final_cif_source"),
                "symmetry_closed": trace_payload.get("symmetry_closed"),
                "selected_species_by_orbit": json.dumps(trace_payload.get("selected_species_by_orbit") or {}, sort_keys=True),
                "orbit_count": sites_payload.get("orbit_count") if isinstance(sites_payload, dict) else None,
                "site_count": sites_payload.get("site_count") if isinstance(sites_payload, dict) else None,
            }
        )

    manifest_dir = out_root / "manifests"
    manifest_csv = manifest_dir / "prototype_orbit_variable_qlip_smoke_manifest.csv"
    manifest_json = out_root / "targeted_smoke_manifest.json"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema_version": "prototype_orbit_variable_qlip_smoke.v1",
        "scope": "first variable orbit-level symmetry-preserving QLIP smoke",
        "out_root": str(out_root),
        "manifest_csv": str(manifest_csv),
        "rows": rows,
    }
    _write_json(manifest_json, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the variable prototype orbit QLIP smoke.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()
    summary = run_smoke(args.out_root)
    print(json.dumps({"out_root": summary["out_root"], "rows": len(summary["rows"])}, indent=2))


if __name__ == "__main__":
    main()
