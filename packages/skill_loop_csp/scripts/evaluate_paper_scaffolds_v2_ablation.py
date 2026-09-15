"""Evaluate selected v2 ablation CIFs with frozen SCA/CHGNet protocols."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


REPO = Path(__file__).resolve().parents[1]
SCA = REPO.parent / "Structured_Crystal_Analyser"
if str(SCA) not in sys.path:
    sys.path.insert(0, str(SCA))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sca.evaluators.bonds import evaluate_bonds  # noqa: E402
from sca.evaluators.geometry import evaluate_geometry  # noqa: E402
from sca.evaluators.topology import family_topology_metrics  # noqa: E402
from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import build_family_scaffold_alternatives  # noqa: E402


ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "spp_ablation"
OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_ablation"
CHGNET = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_ablation_chgnet"
REFS = REPO / "artifacts" / "Paper_scaffolds_september" / "final_audit" / "olivine_refs"
POLICY = {"rocksalt": "ROCKSALT", "spinel": "SPINEL", "layered oxide": "LAYERED_OXIDE", "olivine phosphate": "OLIVINE"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_chgnet_manifest() -> None:
    panel = read_json(ARTIFACT / "SPP_V2_ABLATION_PANEL_FREEZE.json")["rows"]
    rows = []
    for frozen in panel:
        for condition in ("request", "global"):
            result = read_json(OUTPUT / frozen["row_id"] / condition / "result.json")
            cif = Path(result["winner"]["selected_cif_path"])
            rows.append({
                "task_id": f"{frozen['row_id']}__{condition}",
                "formula": frozen["formula"],
                "generated_cif_path": str(cif.resolve()),
                "generated_cif_sha256": sha(cif),
            })
    path = ARTIFACT / "SPP_V2_CHGNET_MANIFEST.csv"
    if path.exists():
        existing = list(csv.DictReader(path.open(newline="", encoding="utf-8")))
        if existing != rows:
            raise RuntimeError("frozen CHGNet manifest differs from selected v2 results")
        return
    write_csv(path, rows)


def independent_olivine(structure: Structure) -> tuple[str, int]:
    matcher = StructureMatcher(
        ltol=0.3, stol=0.4, angle_tol=8, primitive_cell=True,
        attempt_supercell=True,
    )
    matches = sum(matcher.fit_anonymous(structure, Structure.from_file(path)) for path in sorted(REFS.glob("*.cif")))
    number = SpacegroupAnalyzer(structure, symprec=0.05).get_space_group_number()
    return ("OLIVINE" if matches and number == 62 else "NOT_OLIVINE"), matches


def orbit_fingerprint(structure: Structure, formula: str, family: str, alternative_id: str) -> dict[str, str]:
    alternatives = build_family_scaffold_alternatives({"formula": formula, "family": family})
    alternative = next(item for item in alternatives if item.alternative_id == alternative_id)
    output_frac = np.asarray(structure.frac_coords)
    fingerprint = {}
    for orbit in alternative.ordered_orbits:
        counts: dict[str, int] = {}
        claimed: set[int] = set()
        for site_index in orbit["site_indices"]:
            delta = np.abs(output_frac - alternative.structure.frac_coords[site_index])
            delta = np.minimum(delta, 1.0 - delta)
            distances = np.linalg.norm(delta, axis=1)
            match = int(np.argmin(distances))
            if distances[match] > 1e-4 or match in claimed:
                raise RuntimeError(f"cannot map {alternative_id}/{orbit['orbit_id']} onto emitted CIF")
            claimed.add(match)
            species = str(structure[match].specie)
            counts[species] = counts.get(species, 0) + 1
        fingerprint[orbit["orbit_id"]] = "+".join(
            species if count == len(orbit["site_indices"]) else f"{species}:{count}"
            for species, count in sorted(counts.items())
        )
    return fingerprint


def spinel_ordering(fingerprint: dict[str, str], family: str) -> str:
    if family != "spinel":
        return "NOT_APPLICABLE"
    tetrahedral = fingerprint["tet_8a"]
    first_oct = fingerprint["oct_ordered_a"]
    second_oct = fingerprint["oct_ordered_b"]
    return "NORMAL" if first_oct == second_oct and tetrahedral != first_oct else "ORDERED_INVERSE"


def evaluate(path: Path, formula: str, family: str) -> dict[str, Any]:
    structure = Structure.from_file(path)
    bonds = evaluate_bonds(structure)
    geometry = evaluate_geometry(structure)
    policy = POLICY[family]
    topology, _details = family_topology_metrics(structure, policy)
    analyzer = SpacegroupAnalyzer(structure, symprec=0.05, angle_tolerance=5)
    independent, matches = independent_olivine(structure) if family == "olivine phosphate" else ("NOT_APPLICABLE", 0)
    return {
        "cif_path": str(path), "cif_sha256": sha(path),
        "exact_composition": structure.composition.reduced_composition == Composition(formula).reduced_composition,
        "ordered": structure.is_ordered, "site_count": len(structure),
        "geometry_ok": geometry.geometry_ok, "bad_contacts": bonds.num_bad_contacts,
        "minimum_distance_A": bonds.min_distance,
        "space_group": analyzer.get_space_group_symbol(), "space_group_number": analyzer.get_space_group_number(),
        "topology_policy": policy, "sca_topology_status": topology["topology_status"],
        "sca_topology_checks": json.dumps(topology["topology_checks"], sort_keys=True),
        "independent_olivine": independent, "anonymous_olivine_reference_matches": matches,
    }


def run_evaluation() -> None:
    panel = read_json(ARTIFACT / "SPP_V2_ABLATION_PANEL_FREEZE.json")["rows"]
    rows = []
    for frozen in panel:
        for condition in ("request", "global"):
            result = read_json(OUTPUT / frozen["row_id"] / condition / "result.json")
            winner = result["winner"]
            task_id = f"{frozen['row_id']}__{condition}"
            initial = Path(winner["selected_cif_path"])
            initial_structure = Structure.from_file(initial)
            fingerprint = orbit_fingerprint(initial_structure, frozen["formula"], frozen["family"], winner["alternative_id"])
            rows.append({
                "row_id": frozen["row_id"], "condition": condition, "stage": "pre_chgnet",
                "formula": frozen["formula"], "family": frozen["family"],
                "selected_alternative": winner["alternative_id"],
                "selected_orbit_assignment": json.dumps(fingerprint, sort_keys=True),
                "spinel_ordering": spinel_ordering(fingerprint, frozen["family"]),
                "solver_status": winner["solver_status"], "solver_objective": winner["solver_objective"],
                "runtime_s": winner["runtime_s"], **evaluate(initial, frozen["formula"], frozen["family"]),
            })
            relaxed_result = CHGNET / "runs" / task_id / "mlip" / "result.json"
            if relaxed_result.is_file():
                relaxation = read_json(relaxed_result)
                if relaxation["relaxation_status"] == "PASS":
                    rows.append({
                        "row_id": frozen["row_id"], "condition": condition, "stage": "post_chgnet",
                        "formula": frozen["formula"], "family": frozen["family"],
                        "selected_alternative": winner["alternative_id"],
                        "selected_orbit_assignment": json.dumps(fingerprint, sort_keys=True),
                        "spinel_ordering": spinel_ordering(fingerprint, frozen["family"]),
                        "solver_status": winner["solver_status"], "solver_objective": winner["solver_objective"],
                        "runtime_s": relaxation["runtime_s"], "chgnet_converged": relaxation["converged"],
                        "chgnet_steps": relaxation["relaxation_steps"],
                        "volume_change_percent": relaxation["volume_change_percent"],
                        **evaluate(Path(relaxation["relaxed_cif_path"]), frozen["formula"], frozen["family"]),
                    })
    write_csv(ARTIFACT / "SPP_V2_SCA_CHGNET_RESULTS.csv", rows)
    (ARTIFACT / "SPP_V2_SCA_CHGNET_RESULTS.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make-chgnet-manifest", action="store_true")
    args = parser.parse_args()
    if args.make_chgnet_manifest:
        make_chgnet_manifest()
    else:
        run_evaluation()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
