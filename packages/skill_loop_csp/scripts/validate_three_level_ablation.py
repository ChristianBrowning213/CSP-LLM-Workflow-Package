"""Run the frozen public validation stack over every emitted ablation CIF."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages


CHGNET_PROTOCOL = "chgnet_0.4.2_fire_fmax0.1_steps200_cell_v1"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("ablation_root", type=Path); args = parser.parse_args()
    root = args.ablation_root.resolve(); stages = ProductionWorkflowStages(); results = []
    for path in sorted((root / "runs").rglob("RESULTS.csv")):
        results.extend(read_csv(path))
    validated, chgnet = [], []
    for row in results:
        base = {"row_id": row["row_id"], "formula": row["formula"], "workflow_status": row["workflow_status"]}
        if row.get("cif_generated") != "YES":
            validated.append(base | {"validation_status": "NOT_APPLICABLE_NO_CIF"}); continue
        cif = Path(row["cif_path"]).resolve(); structure = Structure.from_file(cif)
        task = stages.normalise(row["formula"]); sca = stages.evaluate(cif, task)
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5)
        exact = structure.composition.reduced_composition == Composition(row["formula"]).reduced_composition
        status = "PASS" if sca.get("pre_dft_valid") is True and sca.get("topology_status") in {"PASS", "NOT_APPLICABLE"} else "PARTIAL" if sca.get("parse_ok") else "FAIL"
        validated.append(base | {
            "cif_path": str(cif), "cif_sha256": sha256(cif), "valid_cif": bool(sca.get("parse_ok")),
            "composition_exact": exact, "validation_status": status,
            "pymatgen_space_group": analyzer.get_space_group_symbol(),
            "pymatgen_crystal_system": analyzer.get_crystal_system(), "initial_volume": float(structure.volume),
            "geometry_ok": sca.get("geometry_ok"), "minimum_distance_A": sca.get("min_distance"),
            "minimum_distance_pair": sca.get("min_distance_pair"), "severe_contact_count": sca.get("num_bad_contacts"),
            "topology_status": sca.get("topology_status"), "topology_policy": sca.get("topology_policy"),
            "topology_backend": sca.get("topology_backend"), "topology_checks": sca.get("topology_checks"),
            "sca_backend": "sca.pipelines.evaluate_one_cif",
            "symmetry_backend": "pymatgen.symmetry.analyzer.SpacegroupAnalyzer",
        })
        chgnet.append({"row_id": row["row_id"], "formula": row["formula"], "cif_path": str(cif), "cif_sha256": sha256(cif), "protocol_id": CHGNET_PROTOCOL})
    write_csv(root / "SCA_FULL_RESULTS.csv", validated)
    write_csv(root / "CHGNET_INPUTS.csv", chgnet)
    (root / "VALIDATOR_AUDIT.md").write_text(
        "# Validator Audit\n\n"
        "- CIF parsing and exact reduced composition: `pymatgen.core.Structure` and `pymatgen.core.Composition`.\n"
        "- Initial symmetry and crystal system: `pymatgen.symmetry.analyzer.SpacegroupAnalyzer` with symprec 0.01 Å and angle tolerance 5°.\n"
        "- Geometry and contacts: `sca.pipelines.evaluate_one_cif`, backed by pymatgen structures and SCA bond/geometry evaluators; minimum distance, pair, bad-contact count, and geometry status are retained separately.\n"
        "- Family topology: `sca.evaluators.topology.family_topology_metrics`, whose local-environment backend is `pymatgen.analysis.local_env.CrystalNN`; policy is recorded row-wise.\n"
        "- Relaxation: CHGNet 0.4.2 `StructOptimizer`, FIRE, fmax 0.1 eV/Å, at most 200 steps, cell relaxation enabled.\n"
        "- Initial/relaxed comparison: `pymatgen.analysis.structure_matcher.StructureMatcher` with ltol 0.2, stol 0.3, angle_tol 5, no primitive scaling or supercell.\n"
        "- Initial and relaxed space group/crystal system/volume are recorded by the CHGNet table runner.\n"
        "- No scalar realism score is created.\n",
        encoding="utf-8",
    )
    print(f"validated={len(validated)} chgnet_inputs={len(chgnet)}")


if __name__ == "__main__": main()
