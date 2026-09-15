"""Tiny fake CIF generator used by E2E benchmark tests and smoke runs."""

from __future__ import annotations

import argparse
from pathlib import Path


TINY_NACL = """data_NaCl
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--attempts", type=int, required=True)
    parser.add_argument("--fail", action="store_true")
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.fail:
        raise SystemExit(2)
    for index in range(1, args.attempts + 1):
        (out_dir / f"attempt_{index:03d}.cif").write_text(TINY_NACL, encoding="utf-8")
    print(f"Generated {args.attempts} CIFs for: {args.prompt}")


if __name__ == "__main__":
    main()
