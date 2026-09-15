"""Build CHGNet manifest and SCA pre/post results for frozen v2 holdout."""

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
for path in (SCA, REPO / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from sca.evaluators.bonds import evaluate_bonds  # noqa: E402
from sca.evaluators.geometry import evaluate_geometry  # noqa: E402
from sca.evaluators.topology import family_topology_metrics  # noqa: E402
from sok_llm_orchestrator.workflow.paper_scaffolds_library_v2 import build_family_scaffold_alternatives  # noqa: E402


ARTIFACT = REPO / "artifacts" / "Paper_scaffolds_september" / "scaffold_v2" / "final_holdout"
OUTPUT = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_holdout"
CHGNET = REPO / "outputs" / "Paper_scaffolds_september" / "scaffold_v2_holdout_chgnet"
HOLDOUT = ARTIFACT / "V2_HOLDOUT.csv"
FREEZE = ARTIFACT / "V2_HOLDOUT_FREEZE.json"
REFS = REPO / "artifacts" / "Paper_scaffolds_september" / "final_audit" / "olivine_refs"
POLICY = {"ROCKSALT": "ROCKSALT", "SPINEL": "SPINEL", "LAYERED_O3": "LAYERED_OXIDE", "OLIVINE": "OLIVINE"}
FAMILY = {"ROCKSALT": "rocksalt", "SPINEL": "spinel", "LAYERED_O3": "layered oxide", "OLIVINE": "olivine phosphate"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rows() -> list[dict[str, str]]:
    frozen = read_json(FREEZE)
    if sha(HOLDOUT) != frozen["holdout_sha256"]:
        raise RuntimeError("holdout hash mismatch")
    with HOLDOUT.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, values: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in values for key in row))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(values)


def make_chgnet_manifest() -> None:
    values = []
    for frozen in rows():
        result_path = OUTPUT / frozen["row_id"] / "v2_result.json"
        if not result_path.is_file():
            continue
        result = read_json(result_path)
        cif = Path(result["winner"]["selected_cif_path"])
        values.append({"task_id": frozen["row_id"], "formula": frozen["formula"], "generated_cif_path": str(cif), "generated_cif_sha256": sha(cif)})
    path = ARTIFACT / "V2_HOLDOUT_CHGNET_MANIFEST.csv"
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            if list(csv.DictReader(handle)) != values:
                raise RuntimeError("existing CHGNet manifest differs")
    else:
        write_csv(path, values)
        (ARTIFACT / "V2_HOLDOUT_CHGNET_MANIFEST_FREEZE.json").write_text(json.dumps({"holdout_freeze_sha256": sha(FREEZE), "generated_row_count": len(values), "manifest_sha256": sha(path)}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def olivine(structure: Structure) -> tuple[str, int]:
    matcher = StructureMatcher(ltol=0.3, stol=0.4, angle_tol=8, primitive_cell=True, attempt_supercell=True)
    matches = sum(matcher.fit_anonymous(structure, Structure.from_file(path)) for path in sorted(REFS.glob("*.cif")))
    number = SpacegroupAnalyzer(structure, symprec=0.05).get_space_group_number()
    return ("OLIVINE" if matches and number == 62 else "NOT_OLIVINE"), matches


def orbit_fingerprint(structure: Structure, frozen: dict[str, str], alternative_id: str) -> dict[str, str]:
    alternatives = build_family_scaffold_alternatives({"formula": frozen["formula"], "family": FAMILY[frozen["policy"]], "topology_subclass": "O3" if frozen["policy"] == "LAYERED_O3" else None})
    alternative = next(item for item in alternatives if item.alternative_id == alternative_id)
    output_frac = np.asarray(structure.frac_coords)
    fingerprint = {}
    all_claimed: set[int] = set()
    for orbit in alternative.ordered_orbits:
        counts: dict[str, int] = {}
        for site_index in orbit["site_indices"]:
            delta = np.abs(output_frac - alternative.structure.frac_coords[site_index])
            delta = np.minimum(delta, 1.0 - delta)
            distances = np.linalg.norm(delta, axis=1)
            for match in np.argsort(distances):
                match = int(match)
                if match not in all_claimed:
                    break
            if distances[match] > 1e-4:
                raise RuntimeError(f"cannot map {alternative_id}/{orbit['orbit_id']}")
            all_claimed.add(match)
            species = str(structure[match].specie)
            counts[species] = counts.get(species, 0) + 1
        fingerprint[orbit["orbit_id"]] = "+".join(species if count == len(orbit["site_indices"]) else f"{species}:{count}" for species, count in sorted(counts.items()))
    return fingerprint


def evaluate(path: Path, frozen: dict[str, str]) -> dict[str, Any]:
    structure = Structure.from_file(path)
    bonds = evaluate_bonds(structure)
    geometry = evaluate_geometry(structure)
    topology, _ = family_topology_metrics(structure, POLICY[frozen["policy"]])
    symmetry = SpacegroupAnalyzer(structure, symprec=0.05, angle_tolerance=5)
    independent, matches = olivine(structure) if frozen["policy"] == "OLIVINE" else ("NOT_APPLICABLE", 0)
    return {
        "cif_path": str(path), "cif_sha256": sha(path),
        "generated": True, "exact_composition": structure.composition.reduced_composition == Composition(frozen["formula"]).reduced_composition,
        "ordered": structure.is_ordered, "site_count": len(structure), "geometry_ok": geometry.geometry_ok,
        "bad_contacts": bonds.num_bad_contacts, "minimum_distance_A": bonds.min_distance,
        "space_group": symmetry.get_space_group_symbol(), "space_group_number": symmetry.get_space_group_number(),
        "sca_topology_status": topology["topology_status"], "sca_topology_checks": json.dumps(topology["topology_checks"], sort_keys=True),
        "independent_olivine": independent, "anonymous_olivine_reference_matches": matches,
    }


def run() -> None:
    values = []
    for frozen in rows():
        root = OUTPUT / frozen["row_id"]
        result_path = root / "v2_result.json"
        if not result_path.is_file():
            failure = read_json(root / "v2_failure.json") if (root / "v2_failure.json").is_file() else {"error_type": "NOT_RUN", "error": ""}
            values.append({"row_id": frozen["row_id"], "policy": frozen["policy"], "formula": frozen["formula"], "stage": "generation", "generated": False, "generation_failure_type": failure["error_type"], "generation_failure": failure["error"], "no_replacement": True})
            continue
        result = read_json(result_path)
        winner = result["winner"]
        initial = Path(winner["selected_cif_path"])
        fingerprint = orbit_fingerprint(Structure.from_file(initial), frozen, winner["alternative_id"])
        ordering = "NOT_APPLICABLE"
        if frozen["policy"] == "SPINEL":
            ordering = "NORMAL" if fingerprint["oct_ordered_a"] == fingerprint["oct_ordered_b"] != fingerprint["tet_8a"] else "ORDERED_INVERSE"
        common = {
            "row_id": frozen["row_id"], "policy": frozen["policy"], "formula": frozen["formula"],
            "selected_alternative": winner["alternative_id"], "selected_vpa_A3_per_atom": winner["vpa_A3_per_atom"],
            "selected_internal_parameter": winner["internal_parameter"], "selected_orbit_assignment": json.dumps(fingerprint, sort_keys=True),
            "spinel_ordering": ordering, "solver_status": winner["solver_status"], "solver_objective": winner["solver_objective"],
            "objective_difference": abs(float(winner["solver_objective"]) - float(winner["independent_objective"])),
            "feasible_states_per_geometry": winner["feasible_state_count"], "geometry_alternative_count": result["alternative_count"],
            "qlip_runtime_s": sum(float(item["runtime_s"]) for item in result["alternatives"]),
            "retrieved_count": result["retrieved_count"], "spp_evidence_count": result["spp_evidence_count"],
            "target_reference_excluded": result["target_reference_excluded"], "no_replacement": True,
        }
        values.append({**common, "stage": "pre_chgnet", **evaluate(initial, frozen)})
        relaxation_path = CHGNET / "runs" / frozen["row_id"] / "mlip" / "result.json"
        if relaxation_path.is_file():
            relaxation = read_json(relaxation_path)
            if relaxation["relaxation_status"] == "PASS":
                values.append({
                    **common, "stage": "post_chgnet", "chgnet_converged": relaxation["converged"],
                    "chgnet_steps": relaxation["relaxation_steps"], "chgnet_runtime_s": relaxation["runtime_s"],
                    "volume_change_percent": relaxation["volume_change_percent"],
                    **evaluate(Path(relaxation["relaxed_cif_path"]), frozen),
                })
            else:
                values.append({**common, "stage": "post_chgnet", "generated": True, "chgnet_converged": False, "chgnet_failure": relaxation["error"]})
    write_csv(ARTIFACT / "V2_HOLDOUT_RESULTS.csv", values)
    (ARTIFACT / "V2_HOLDOUT_RESULTS.json").write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make-chgnet-manifest", action="store_true")
    args = parser.parse_args()
    if args.make_chgnet_manifest:
        make_chgnet_manifest()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
