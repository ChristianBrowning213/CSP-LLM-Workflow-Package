"""Fake Skill-Loop-CSP text entrypoint for intent benchmark tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


NACL_CIF = """data_NaCl
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   5.6402
_cell_length_b   5.6402
_cell_length_c   5.6402
_cell_angle_alpha   90
_cell_angle_beta    90
_cell_angle_gamma   90
_symmetry_Int_Tables_number 1
loop_
 _symmetry_equiv_pos_as_xyz
 'x, y, z'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 Na1 Na 0 0 0 1
 Cl1 Cl 0.5 0.5 0.5 1
"""


BATIO3_CIF = """data_BaTiO3
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   4.02
_cell_length_b   4.02
_cell_length_c   4.02
_cell_angle_alpha   90
_cell_angle_beta    90
_cell_angle_gamma   90
_symmetry_Int_Tables_number 1
loop_
 _symmetry_equiv_pos_as_xyz
 'x, y, z'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 Ba1 Ba 0 0 0 1
 Ti1 Ti 0.5 0.5 0.5 1
 O1 O 0.5 0.5 0 1
 O2 O 0.5 0 0.5 1
 O3 O 0 0.5 0.5 1
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--manifest-row")
    parser.add_argument("--task-spec")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompt.txt").write_text(args.prompt, encoding="utf-8")
    if args.manifest_row:
        (out_dir / "manifest_row.json").write_text(Path(args.manifest_row).read_text(encoding="utf-8"), encoding="utf-8")
    lower = args.prompt.lower()
    if "infeasible" in lower or "below 1.0" in lower or "adversarial" in lower:
        (out_dir / "infeasible_status.json").write_text(
            json.dumps({"solver_status": "infeasible", "reason": "fake adversarial rejection"}, indent=2),
            encoding="utf-8",
        )
        print("Marked prompt infeasible")
        return
    cif_text = BATIO3_CIF if "batio3" in lower or "perovskite" in lower else NACL_CIF
    (out_dir / "candidate_001.cif").write_text(cif_text, encoding="utf-8")
    (out_dir / "retrieval_trace.json").write_text(
        json.dumps({"retrieved": [{"evidence_id": "fake_ev", "formula": "BaTiO3", "family": "perovskite", "parseable": True}]}, indent=2),
        encoding="utf-8",
    )
    (out_dir / "solver_trace.json").write_text(
        json.dumps({"backend": "fake", "solver_status": "optimal", "objective_value": 0.0, "num_variables": 1, "num_constraints": 1}, indent=2),
        encoding="utf-8",
    )
    (out_dir / "final_decision.json").write_text(
        json.dumps({"selected_candidate_id": "candidate_001", "explanation": "Used fake_ev evidence."}, indent=2),
        encoding="utf-8",
    )
    print(f"Generated CIF for seed {args.seed}: {args.prompt}")


if __name__ == "__main__":
    main()
