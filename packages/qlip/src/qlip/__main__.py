"""
Solve a QLIP placement task using the core API.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from qlip.core.solve import _classify_cif_output, _to_text, solve as core_solve


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LATTICE = {
    "a": 3.9,
    "b": 3.9,
    "c": 3.9,
    "alpha": 90.0,
    "beta": 90.0,
    "gamma": 90.0,
    "units": "angstrom",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Solve a placement task on a uniform grid.")
    parser.add_argument(
        "--chem",
        default="SrTiO3",
        help="Chemical formula to allocate (default: SrTiO3), e.g. BaTiO3, SrZrO3.",
    )
    parser.add_argument(
        "--grid",
        type=int,
        default=8,
        help="Uniform grid density per axis (default: 8 => 512 candidate sites).",
    )
    parser.add_argument(
        "--use-motifs",
        action="store_true",
        help="Enable motif allocation using artifacts under gen_artifacts/.",
    )
    parser.add_argument(
        "--motif-dir",
        type=Path,
        default=REPO_ROOT / "gen_artifacts",
        help="Directory containing motifs.json and instances.json (default: gen_artifacts/).",
    )
    parser.add_argument(
        "--motif-include",
        action="append",
        help="Restrict motif usage to specific names (repeatable).",
    )
    parser.add_argument(
        "--spp-pot-dir",
        type=Path,
        default=None,
        help="Directory containing SPP POT files (optional override).",
    )
    parser.add_argument(
        "--solver",
        choices=["gurobi"],
        default="gurobi",
        help="MILP solver name (fixed to gurobi).",
    )
    return parser.parse_args()


def _build_request(args: argparse.Namespace) -> dict:
    constraints = [
        {
            "id": "proximity.atomic_radii",
            "params": {"scale": 1.0},
        }
    ]
    context = {}
    pot_override = args.spp_pot_dir or os.getenv("QLIP_SPP_POT_DIR")
    if pot_override:
        context["pot_root"] = str(pot_override)

    if args.use_motifs:
        constraints.append(
            {
                "id": "motif.linking",
                "params": {
                    "motif_dir": str(args.motif_dir),
                    "include": args.motif_include,
                },
            }
        )
        context["motif_root"] = str(args.motif_dir)

    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": args.chem},
            "design_space": {
                "template": {"name": "cubic", "lattice": DEFAULT_LATTICE},
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": args.grid}},
            },
            "objective": {"type": "spp_energy"},
        },
        "constraints": constraints,
        "guidance": [],
        "solver": {"name": args.solver},
        "context": context,
    }


def main() -> None:
    args = _parse_args()
    request = _build_request(args)
    result = core_solve(request)
    print(f"Status: {result.status}")
    if result.summary.objective_value is not None:
        print(f"Objective: {result.summary.objective_value}")
    if result.outputs.cif:
        cif_kind, cif_text, _ = _classify_cif_output(result.outputs.cif)
        if cif_kind == "valid_cif_like" and cif_text is not None:
            out = REPO_ROOT / "viz" / "structure.cif"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(cif_text, encoding="utf-8", newline="")
            print(f"Wrote CIF: {out}")
        else:
            print(f"[error] invalid_cif_output: refusing to write {cif_kind} CIF artifact")
    if result.errors:
        for err in result.errors:
            print(f"[error] {err.code}: {_to_text(err.message) or ''}")


if __name__ == "__main__":
    main()
