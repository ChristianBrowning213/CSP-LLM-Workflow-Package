"""Freeze the developed scaffold-v2 method before unseen holdout selection."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2"
TARGET = ROOT / "V2_METHOD_FREEZE.json"
FILES = (
    "src/sok_llm_orchestrator/workflow/paper_scaffolds_library_v2.py",
    "scripts/run_paper_scaffolds_v2_ablation.py",
    "scripts/evaluate_paper_scaffolds_v2_ablation.py",
    "scripts/build_paper_scaffolds_v2_freedom.py",
    "tests/test_paper_scaffolds_library_v2.py",
    "artifacts/Paper_scaffolds_september/scaffold_v2/V2_IMPLEMENTATION_DESIGN.md",
    "artifacts/Paper_scaffolds_september/scaffold_v2/V1_V2_FREEDOM_COMPARISON.csv",
    "artifacts/Paper_scaffolds_september/scaffold_v2/spp_ablation/SPP_V2_ABLATION_PANEL_FREEZE.json",
    "artifacts/Paper_scaffolds_september/scaffold_v2/spp_ablation/SPP_V2_ABLATION_RESULTS.csv",
    "artifacts/Paper_scaffolds_september/scaffold_v2/spp_ablation/SPP_V2_SCA_CHGNET_RESULTS.csv",
    "artifacts/Paper_scaffolds_september/scaffold_v2/spp_ablation/SPP_V2_ABLATION_ANALYSIS.md",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    if TARGET.exists():
        raise FileExistsError(f"v2 is already frozen: {TARGET}")
    missing = [name for name in FILES if not (REPO / name).is_file()]
    if missing:
        raise FileNotFoundError(f"freeze inputs missing: {missing}")
    v1 = REPO / "src" / "sok_llm_orchestrator" / "workflow" / "paper_scaffolds_library.py"
    v1_hash = sha(v1)
    if v1_hash != "0fb5ab282fa5e6d672841daceaa4ddd25e148b8b4c907c821322fe6341757043":
        raise RuntimeError("frozen v1 source hash changed")
    panel = json.loads((ROOT / "spp_ablation" / "SPP_V2_ABLATION_PANEL_FREEZE.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": "paper_scaffolds_library.v2.method_freeze.v1",
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "repo_head": git("rev-parse", "HEAD"),
        "repo_branch": git("branch", "--show-current"),
        "repo_dirty": bool(git("status", "--porcelain")),
        "repo_status_porcelain": git("status", "--porcelain").splitlines(),
        "v1_preservation": {"path": str(v1.relative_to(REPO)), "sha256": v1_hash},
        "source_and_development_hashes": {name: sha(REPO / name) for name in FILES},
        "method": {
            "version": "paper_scaffolds_library.v2",
            "objective": "unchanged QLIP objective.energy_spp; independent geometry solves; feasible objective minimum",
            "ordered_only": True,
            "partial_occupancy": False,
            "disorder": False,
            "target_coordinates_or_lattice_consumed": False,
            "cell_candidates": "target-composition-filtered retrieval VPA quartiles, else frozen broad-corpus quartiles",
            "geometry_candidates": {
                "ROCKSALT": "3 cell scales; B1/Fm-3m",
                "SPINEL": "3 cell scales x oxygen u={0.375,0.386,0.397}; normal + two ordered inverse-compatible occupations",
                "LAYERED_O3": "3 cell scales x oxygen z={0.235,0.241,0.247}; two layer occupations",
                "OLIVINE": "3 cell scales; Pnma framework; fixed explicit tetrahedral former and variable M1/M2 occupation",
            },
            "supported_topology_subclasses": ["ROCKSALT_B1", "SPINEL_NORMAL_OR_ORDERED_INVERSE", "LAYERED_O3_R-3m", "OLIVINE_Pnma"],
            "unsupported_without_new_frozen_evidence": ["LAYERED_P2", "partial/disordered spinel inversion"],
            "solver_scorer_tolerance": 1e-6,
            "chgnet_protocol": "CHGNet 0.4.2 pretrained; FIRE; fmax 0.1 eV/A; max 80 steps; relax_cell=True",
            "sca_thresholds_changed": False,
            "qlip_changed": False,
        },
        "acceptance_criteria": {
            "generation": "candidate CIF emitted only from OPTIMAL or FEASIBLE authoritative solve",
            "composition": "exact reduced composition and no duplicate/partial/disordered occupancy",
            "objective": "solver and independent scorer agree within 1e-6 for every alternative",
            "selection": "minimum objective over all feasible frozen alternatives; deterministic alternative-id tie break",
            "topology": "family SCA verdict retained verbatim; ordered inverse spinel explicitly audited as hard-network Imma; olivine additionally requires Pnma #62 plus anonymous match to frozen ordered references",
            "holdout": "preselected and hashed; no replacements; every failure remains in denominator",
        },
        "development_panel_exclusions": [row["row_id"] for row in panel["rows"]],
        "final_holdout_exclusion_sets": [
            "Dataset A", "Dataset B", "Dataset C", "final-audit holdout",
            "Result D stress40", "Result D SPP ablation", "v2 development panel",
            "all test fixtures used to establish geometry grids",
        ],
        "development_result": {
            "qlip": "144/144 OPTIMAL with solver/scorer parity",
            "request_vs_global_structure_changed": "9/12",
            "spinel": "request normal 3/3; global ordered inverse 3/3",
            "chgnet": "23/24 converged; global inverse Zn(SbO2)2 non-converged retained",
        },
        "prohibitions": ["no post-freeze v2 modification", "no holdout replacement", "no DFT", "no SPP/SCA/CHGNet parameter change"],
    }
    TARGET.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"frozen {TARGET} sha256={sha(TARGET)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
