"""Recompute SPP objectives for generated pair-aware development candidates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pymatgen.core import Structure

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from sok_llm_orchestrator.workflow.evidence import required_pairs_for_formula  # noqa: E402
from sok_llm_orchestrator.workflow.spp import compile_spp_components, score_spp_components  # noqa: E402


def main() -> int:
    root = REPO_ROOT.parent / "Crystal-DB" / "artifacts" / "spp_only_oxide_benchmark_v1" / "development_pair_aware_v1"
    rows = []
    for summary_path in sorted(root.glob("runs/*/*/run_summary.json")):
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        candidate = summary_path.parent / "generated" / "candidate.cif"
        if not summary.get("candidate_generated") or not candidate.is_file():
            continue
        strict = json.loads((summary_path.parent / "spp" / "artifact_preflight.json").read_text(encoding="utf-8"))
        request_root = Path(strict["pot_audit"]["pot_root"])
        fit_manifests = sorted((summary_path.parent / "spp").glob("fit_round_*/spp_build_manifest.json"))
        manifest = json.loads(fit_manifests[-1].read_text(encoding="utf-8"))
        pair_rows = list(manifest["request_pair_results"])
        regulator_root = Path(pair_rows[0]["regulator_pot_path"]).parents[1]
        pair_names = required_pairs_for_formula(str(summary["formula"]))
        pairs = [tuple(pair.split("-", 1)) for pair in pair_names]
        request, regulator, _ = compile_spp_components(
            request_pot_root=request_root, regulator_pot_root=regulator_root, pairs=pairs,
            cutoff=11.0, regulator_weight=2.0, allow_request_fallback=False,
        )
        structure = Structure.from_file(candidate)
        atoms = structure.to_ase_atoms()
        components = score_spp_components(
            symbols=atoms.get_chemical_symbols(), positions=atoms.positions, cell=atoms.cell.array,
            request=request, regulator=regulator, regulator_weight=2.0,
            request_guidance_weight=10.0, pairs=pairs,
            request_pair_statuses={pair: "REQUEST_USABLE" for pair in pair_names},
        )
        solver = float(summary["qlip_objective"])
        difference = abs(solver - components.solver_objective)
        rows.append({
            "experiment_id": summary["experiment_id"], "solver_objective": solver,
            "independent_objective": components.solver_objective,
            "absolute_difference": difference, "agreement_tolerance": 1e-6,
            "OBJECTIVE_AGREEMENT": difference <= 1e-6,
            "required_pair_count": len(pair_names),
            "request_supported_pair_count": components.number_request_supported_pairs,
            "regulator_fallback_pair_count": components.number_regulator_fallback_pairs,
            "unsupported_pair_count": components.number_unsupported_pairs,
        })
    payload = {
        "schema_version": "spp_only_development_objective_audit.v1", "rows": rows,
        "all_objectives_agree": bool(rows) and all(row["OBJECTIVE_AGREEMENT"] for row in rows),
    }
    output = root / "DEVELOPMENT_OBJECTIVE_AUDIT.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["all_objectives_agree"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
