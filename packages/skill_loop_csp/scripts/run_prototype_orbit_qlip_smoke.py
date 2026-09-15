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
    r"\prototype_orbit_qlip_smoke_10_family_20260704"
)


CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "BaTiO3_perovskite",
        "prompt": "Generate BaTiO3 perovskite using orbit-level prototype scaffold QLIP.",
        "formula": "BaTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
    {
        "case_id": "CsPbBr3_halide_perovskite",
        "prompt": "Generate CsPbBr3 halide perovskite using orbit-level prototype scaffold QLIP.",
        "formula": "CsPbBr3",
        "family": "halide perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
    {
        "case_id": "ZnFe2O4_spinel",
        "prompt": "Generate ZnFe2O4 spinel using orbit-level prototype scaffold QLIP.",
        "formula": "ZnFe2O4",
        "family": "spinel",
        "space_group": "Fd-3m",
        "space_group_number": 227,
        "crystal_system": "cubic",
    },
    {
        "case_id": "NiO_rocksalt",
        "prompt": "Generate NiO rocksalt using orbit-level prototype scaffold QLIP.",
        "formula": "NiO",
        "family": "rocksalt",
        "space_group": "Fm-3m",
        "space_group_number": 225,
        "crystal_system": "cubic",
    },
    {
        "case_id": "CeO2_fluorite",
        "prompt": "Generate CeO2 fluorite using orbit-level prototype scaffold QLIP.",
        "formula": "CeO2",
        "family": "fluorite",
        "space_group": "Fm-3m",
        "space_group_number": 225,
        "crystal_system": "cubic",
    },
    {
        "case_id": "FeS2_pyrite",
        "prompt": "Generate FeS2 pyrite using orbit-level prototype scaffold QLIP.",
        "formula": "FeS2",
        "family": "pyrite",
        "space_group": "Pa-3",
        "space_group_number": 205,
        "crystal_system": "cubic",
    },
    {
        "case_id": "LiCoO2_layered_oxide",
        "prompt": "Generate LiCoO2 layered oxide using orbit-level prototype scaffold QLIP.",
        "formula": "LiCoO2",
        "family": "layered oxide",
        "space_group": "R-3m",
        "space_group_number": 166,
        "crystal_system": "trigonal",
    },
    {
        "case_id": "LiFePO4_olivine_phosphate",
        "prompt": "Generate LiFePO4 olivine phosphate using orbit-level prototype scaffold QLIP.",
        "formula": "LiFePO4",
        "family": "olivine phosphate",
        "space_group": "Pnma",
        "space_group_number": 62,
        "crystal_system": "orthorhombic",
    },
    {
        "case_id": "Li6PS5Cl_argyrodite",
        "prompt": "Generate Li6PS5Cl argyrodite using orbit-level prototype scaffold QLIP.",
        "formula": "Li6PS5Cl",
        "family": "argyrodite",
        "space_group": "F-43m",
        "space_group_number": 216,
        "crystal_system": "cubic",
    },
    {
        "case_id": "TiN_nitride",
        "prompt": "Generate TiN nitride using orbit-level prototype scaffold QLIP.",
        "formula": "TiN",
        "family": "nitride",
        "space_group": "Fm-3m",
        "space_group_number": 225,
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
        "active_symmetry_mode": "prototype_orbit_qlip",
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
        trace_payload = _read_json(symmetry_trace)
        request_payload = _read_json(qlip_request)
        sites_payload = (
            request_payload.get("problem", {})
            .get("design_space", {})
            .get("sites", {})
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
                "pipeline_status": result.status,
                "active_symmetry_mode": trace_payload.get("active_symmetry_mode"),
                "orbit_level_selection": trace_payload.get("orbit_level_selection"),
                "final_cif_source": trace_payload.get("final_cif_source"),
                "symmetry_closed": trace_payload.get("symmetry_closed"),
                "orbit_count": sites_payload.get("orbit_count") if isinstance(sites_payload, dict) else None,
                "site_count": sites_payload.get("site_count") if isinstance(sites_payload, dict) else None,
            }
        )

    manifest_dir = out_root / "manifests"
    manifest_csv = manifest_dir / "prototype_orbit_qlip_smoke_manifest.csv"
    manifest_json = out_root / "targeted_smoke_manifest.json"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema_version": "prototype_orbit_qlip_smoke.v1",
        "scope": "10-family fixed prototype-orbit symmetry-preserving QLIP smoke",
        "out_root": str(out_root),
        "manifest_csv": str(manifest_csv),
        "rows": rows,
    }
    _write_json(manifest_json, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 10-family prototype orbit QLIP smoke.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args()
    summary = run_smoke(args.out_root)
    print(json.dumps({"out_root": summary["out_root"], "rows": len(summary["rows"])}, indent=2))


if __name__ == "__main__":
    main()
