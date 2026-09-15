from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.spp_regularisation import find_spp_pot_root, formula_pairs
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline
from sok_llm_orchestrator.structures.prototype_scaffold import prototype_orbit_solution_from_request


DEFAULT_OUT_ROOT = Path(
    r"C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs"
    r"\prototype_orbit_variable_spp_scored_smoke_20260704"
)


CASES: tuple[dict[str, Any], ...] = (
    {
        "case_id": "BaTiO3_perovskite_A_site_orbit_spp",
        "prompt": "Generate BaTiO3 perovskite using SPP-scored variable orbit-level prototype scaffold QLIP.",
        "formula": "BaTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
    {
        "case_id": "CaTiO3_perovskite_A_site_orbit_spp",
        "prompt": "Generate CaTiO3 perovskite using SPP-scored variable orbit-level prototype scaffold QLIP.",
        "formula": "CaTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
    {
        "case_id": "SrTiO3_perovskite_A_site_orbit_spp",
        "prompt": "Generate SrTiO3 perovskite using SPP-scored variable orbit-level prototype scaffold QLIP.",
        "formula": "SrTiO3",
        "family": "perovskite",
        "space_group": "Pm-3m",
        "space_group_number": 221,
        "crystal_system": "cubic",
    },
)


def _settings_for_workspace(workspace: Path, pot_dir: Path | None = None) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workspace
    read_roots = [workspace.resolve(), Path.cwd().resolve()]
    if pot_dir is not None:
        read_roots.append(pot_dir.resolve())
        settings.qlip_allowed_path_roots = [*settings.qlip_allowed_path_roots, pot_dir.resolve()]
    settings.allowed_read_roots = read_roots
    settings.allowed_write_roots = [workspace.resolve()]
    return settings


def _partial_spp_fallback(workspace: Path) -> dict[str, Any]:
    regularisation_dir = workspace / "regularisation_spp"
    regularisation_dir.mkdir(parents=True, exist_ok=True)
    return {
        "active_symmetry_mode": "prototype_orbit_variable_spp_qlip",
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


def _canonical_pair(pair: str) -> str:
    parts = [part for part in str(pair).replace("_", "-").split("-") if part]
    return "-".join(sorted((_canonical_element(part) for part in parts), key=str.lower)) if len(parts) == 2 else str(pair)


def _canonical_element(symbol: str) -> str:
    stripped = str(symbol).strip()
    if not stripped:
        return stripped
    return stripped[:1].upper() + stripped[1:].lower()


def _loaded_pot_pairs(pot_dir: Path | None) -> tuple[list[str], int]:
    if pot_dir is None or not pot_dir.is_dir():
        return [], 0
    pairs: set[str] = set()
    count = 0
    for pot_file in pot_dir.rglob("*.POT"):
        count += 1
        pairs.add(_canonical_pair(pot_file.stem))
    return sorted(pairs), count


def _http_status(url: str) -> str:
    try:
        request = Request(url, method="GET")
        with urlopen(request, timeout=2) as response:
            return "available" if 200 <= int(response.status) < 500 else f"unavailable_http_{response.status}"
    except (OSError, URLError, ValueError) as exc:
        return f"unavailable:{type(exc).__name__}"


def _docker_status() -> str:
    try:
        completed = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable:{type(exc).__name__}"
    return "available" if completed.returncode == 0 else "unavailable"


def _discover_exported_pot_dir(settings: Settings, formula: str) -> Path | None:
    roots = [root.resolve() for root in settings.qlip_allowed_path_roots if Path(root).exists()]
    discovered = find_spp_pot_root(roots, formula)
    return Path(discovered) if discovered else None


def build_spp_preflight(
    *,
    case: dict[str, Any],
    settings: Settings,
    workspace: Path,
    pot_dir: Path | None,
    run_service_probes: bool,
) -> dict[str, Any]:
    required_pairs = sorted(_canonical_pair(pair) for pair in formula_pairs(str(case["formula"])))
    source_type = "direct_pot_dir" if pot_dir is not None else "unavailable"
    resolved_pot_dir = pot_dir.resolve() if pot_dir is not None else _discover_exported_pot_dir(settings, str(case["formula"]))
    if pot_dir is None and resolved_pot_dir is not None:
        source_type = "discovered_exported_pot_dir"
    loaded_pairs, pot_count = _loaded_pot_pairs(resolved_pot_dir)
    missing_pairs = sorted(set(required_pairs) - set(loaded_pairs))
    pot_status = "ready" if resolved_pot_dir is not None and resolved_pot_dir.is_dir() else "unavailable"
    export_status = "ready" if pot_count and not missing_pairs else "missing_required_pairs" if pot_count else "unavailable"
    final_status = "ready" if pot_status == "ready" and export_status == "ready" else "unavailable"
    failure_reason = None if final_status == "ready" else "spp_pot_curves_unavailable"
    direct_bypass = pot_dir is not None
    llm_status = "skipped_direct_pot_dir" if direct_bypass else "not_checked"
    ollama_status = "skipped_direct_pot_dir" if direct_bypass else "not_checked"
    lm_studio_status = "skipped_direct_pot_dir" if direct_bypass else "not_checked"
    docker_status = "skipped_direct_pot_dir" if direct_bypass else "not_checked"
    crystaldb_status = "skipped_direct_pot_dir" if direct_bypass else "unavailable_no_exported_pot_dir"
    vector_status = "skipped_direct_pot_dir" if direct_bypass else "unavailable_no_exported_pot_dir"
    if run_service_probes and not direct_bypass:
        llm_base = str(settings.llm_base_url or "http://localhost:1234/v1").rstrip("/")
        lm_studio_status = _http_status(f"{llm_base}/models")
        llm_status = lm_studio_status
        ollama_status = _http_status("http://127.0.0.1:11434/api/tags")
        docker_status = _docker_status()
        crystaldb_status = "ready_exported_pot_dir_found" if resolved_pot_dir is not None else "unavailable_no_exported_pot_dir"
        vector_status = "ready_exported_pot_dir_found" if resolved_pot_dir is not None else "unavailable_no_exported_pot_dir"
    return {
        "schema_version": "prototype_orbit_variable_spp_preflight.v1",
        "case_id": case["case_id"],
        "formula": case["formula"],
        "family": case["family"],
        "llm_status": llm_status,
        "ollama_status": ollama_status,
        "lm_studio_status": lm_studio_status,
        "docker_status": docker_status,
        "crystaldb_status": crystaldb_status,
        "vector_query_status": vector_status,
        "retrieval_candidate_count": 0,
        "retrieved_cif_count": 0,
        "spp_corpus_status": "direct_pot_dir" if direct_bypass else ("exported_pot_dir_found" if resolved_pot_dir else "unavailable"),
        "pot_export_status": export_status,
        "pot_dir": str(resolved_pot_dir) if resolved_pot_dir is not None else None,
        "pot_count": pot_count,
        "required_pairs": required_pairs,
        "loaded_pairs": loaded_pairs,
        "loaded_pair_count": len(loaded_pairs),
        "missing_pairs": missing_pairs,
        "source_type": source_type if final_status == "ready" else "unavailable",
        "site_mode": "prototype_orbit",
        "orbit_count": 3,
        "site_count": 5,
        "target_space_group": case["space_group"],
        "target_space_group_number": case["space_group_number"],
        "target_crystal_system": case["crystal_system"],
        "target_family": case["family"],
        "workspace": str(workspace),
        "final_status": final_status,
        "failure_reason": failure_reason,
    }


def _request_mutator_for_preflight(preflight: dict[str, Any], preflight_path: Path):
    def _mutate(request: dict[str, Any]) -> dict[str, Any]:
        context = request.setdefault("context", {})
        if isinstance(context, dict):
            if preflight.get("pot_dir"):
                context["pot_root"] = str(preflight["pot_dir"])
        sites = request.setdefault("problem", {}).setdefault("design_space", {}).setdefault("sites", {})
        if isinstance(sites, dict):
            sites["site_mode"] = "prototype_orbit_variable"
            sites["spp_source"] = str(preflight.get("source_type") or "unavailable")
            sites["spp_source_type"] = str(preflight.get("source_type") or "unavailable")
            sites["spp_pot_dir"] = preflight.get("pot_dir")
            sites["spp_preflight_path"] = str(preflight_path)
            sites["spp_preflight_final_status"] = preflight.get("final_status")
            sites["required_pairs"] = list(preflight.get("required_pairs") or [])
            sites["loaded_pair_count"] = int(preflight.get("loaded_pair_count") or 0)
            sites["missing_pairs"] = list(preflight.get("missing_pairs") or [])
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


def run_smoke(
    out_root: Path,
    *,
    require_real_spp: bool = False,
    pot_dir: Path | None = None,
    run_spp_preflight: bool = False,
    allow_spp_unavailable: bool = False,
) -> dict[str, Any]:
    out_root = out_root.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in CASES:
        workspace = out_root / case["case_id"]
        workspace.mkdir(parents=True, exist_ok=True)
        settings = _settings_for_workspace(workspace, pot_dir)
        preflight = build_spp_preflight(
            case=case,
            settings=settings,
            workspace=workspace,
            pot_dir=pot_dir,
            run_service_probes=run_spp_preflight,
        )
        preflight_path = workspace / "spp_preflight.json"
        _write_json(preflight_path, preflight)
        if require_real_spp and preflight["final_status"] != "ready":
            raise SystemExit(
                "Real SPP curves are required but unavailable for "
                f"{case['case_id']}; see {preflight_path} ({preflight['failure_reason']})."
            )
        if not allow_spp_unavailable and not require_real_spp and preflight["final_status"] != "ready":
            print(f"SPP preflight unavailable for {case['case_id']}; preserving fallback mode.")
        result = run_csp_pipeline(
            query=None,
            with_spp=True,
            mode="stub",
            workspace=workspace,
            settings=settings,
            qlip_request_mutator=_request_mutator_for_preflight(preflight, preflight_path),
            execution_overrides=_partial_spp_fallback(workspace),
            task_spec_payload=_task_spec(case),
        )
        artifacts = Path(result.run_dir) / "artifacts"
        artifact_preflight = artifacts / "spp_preflight.json"
        artifact_preflight.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(preflight_path, artifact_preflight)
        solution_cif = artifacts / "qlip" / "solution.cif"
        qlip_request = artifacts / "qlip_request.json"
        symmetry_trace = artifacts / "symmetry_trace.json"
        orbit_solution = artifacts / "orbit_solution.json"
        orbit_candidates = artifacts / "orbit_candidates.json"
        trace_payload = _read_json(symmetry_trace)
        request_payload = _read_json(qlip_request)
        solution_payload = _read_json(orbit_solution)
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
                "spp_scoring_status": trace_payload.get("spp_scoring_status"),
                "spp_source_type": trace_payload.get("spp_source_type"),
                "spp_pot_dir": trace_payload.get("spp_pot_dir"),
                "spp_preflight": str(artifact_preflight),
                "spp_preflight_final_status": preflight.get("final_status"),
                "spp_fallback_reason": trace_payload.get("spp_fallback_reason"),
                "objective_value": trace_payload.get("objective_value"),
                "selected_candidate_id": trace_payload.get("selected_candidate_id"),
                "selected_species_by_orbit": json.dumps(trace_payload.get("selected_species_by_orbit") or {}, sort_keys=True),
                "orbit_count": sites_payload.get("orbit_count") if isinstance(sites_payload, dict) else None,
                "site_count": sites_payload.get("site_count") if isinstance(sites_payload, dict) else None,
                "orbit_solution_spp_status": solution_payload.get("spp_scoring_status"),
            }
        )

    manifest_dir = out_root / "manifests"
    manifest_csv = manifest_dir / "prototype_orbit_variable_spp_qlip_smoke_manifest.csv"
    manifest_json = out_root / "targeted_smoke_manifest.json"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema_version": "prototype_orbit_variable_spp_qlip_smoke.v1",
        "scope": "first orbit-level variable prototype SPP smoke with real-curve preflight diagnostics",
        "out_root": str(out_root),
        "manifest_csv": str(manifest_csv),
        "rows": rows,
    }
    _write_json(manifest_json, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the SPP-hooked variable prototype orbit QLIP smoke.")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--require-real-spp", action="store_true")
    parser.add_argument("--pot-dir", type=Path, default=None)
    parser.add_argument("--run-spp-preflight", action="store_true")
    parser.add_argument("--allow-spp-unavailable", action="store_true")
    args = parser.parse_args()
    summary = run_smoke(
        args.out_root,
        require_real_spp=args.require_real_spp,
        pot_dir=args.pot_dir,
        run_spp_preflight=args.run_spp_preflight,
        allow_spp_unavailable=args.allow_spp_unavailable,
    )
    print(json.dumps({"out_root": summary["out_root"], "rows": len(summary["rows"])}, indent=2))


if __name__ == "__main__":
    main()
