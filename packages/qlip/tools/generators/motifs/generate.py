#!/usr/bin/env python3
"""
CLI wrapper for chemistry-agnostic motif generation.

Examples:
  python -m tools.generators.motifs.generate --chem LiFePO4 --grid 8 --a 10.33 --out gen_artifacts --source mp --mp-max 40 --emit-cifs
  python -m tools.generators.motifs.generate --chem SrTiO3 --grid 6 --a 3.9 --out gen_artifacts --source mp+local --local-cif "extra_structs\\*.cif" --mp-max 20 --emit-cifs
"""
from __future__ import annotations

import argparse
import glob
import inspect
import os
from pathlib import Path
from typing import List

from .mp_miner import mine


def _expand_local_globs(patterns: List[str]) -> List[str]:
    expanded: List[str] = []
    for pattern in patterns or []:
        matches = glob.glob(pattern, recursive=True)
        if not matches:
            print(f"[miner] local pattern matched 0 files: {pattern}")
        for match in matches:
            path = Path(match)
            if path.exists() and path.is_file():
                expanded.append(str(path.resolve()))
    return expanded


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine motifs and instances (chemistry-agnostic).")
    parser.add_argument("--chem", required=True, help="Formula label (used in metadata when running local-only).")
    parser.add_argument("--grid", type=int, required=True, help="Uniform grid size g for a g x g x g lattice.")
    parser.add_argument("--a", type=float, required=True, help="Target cubic cell length in Angstrom (scales structures and CIFs).")
    parser.add_argument("--out", type=Path, default=Path("gen_artifacts"), help="Output directory.")
    parser.add_argument("--source", default="mp", help="mp, local, or mp+local.")
    parser.add_argument("--mp-max", type=int, default=30, help="Maximum number of MP documents to scan.")
    parser.add_argument("--local-cif", nargs="*", help="Local CIF paths (globs accepted) for 'local' or 'mp+local'.")
    parser.add_argument("--snap-tol-frac", type=float, default=0.08, help="Snapping tolerance in fractional coordinates.")
    parser.add_argument("--emit-cifs", action="store_true", help="Emit CIFs for templates and instances.")
    parser.add_argument("--viz-limit", type=int, default=16, help="Maximum instances per motif to emit CIFs for.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Expand local CIF glob patterns up-front.
    local_cifs = _expand_local_globs(args.local_cif or [])

    # Resolve MP API key(s) from the environment.
    mp_key = (
        os.getenv("MP_API_KEY")
        or os.getenv("MAPI_KEY")
        or os.getenv("MP_API_KEY_V2")
    )

    source_lower = args.source.lower()
    if "mp" in source_lower:
        print(f"[miner] MP requested. API key {'FOUND' if mp_key else 'NOT FOUND'}")
    if "local" in source_lower:
        print(f"[miner] local CIFs found: {len(local_cifs)}")
        if not local_cifs:
            print(f"[miner] cwd={os.getcwd()}  (tip: quote the glob and use backslashes on Windows)")

    # Build a superset of kwargs we might pass...
    candidate_kwargs = dict(
        formula=args.chem,
        grid_g=args.grid,
        a=args.a,
        out_dir=args.out,
        source=args.source,
        mp_api_key=mp_key,
        mp_max=args.mp_max,
        local_cifs=local_cifs or None,
        snap_tol_frac=args.snap_tol_frac,
        emit_cifs=args.emit_cifs,
        emit_instances_limit=(args.viz_limit if args.emit_cifs else None),
    )

    # ...then filter to only what the miner actually supports.
    miner_params = set(inspect.signature(mine).parameters.keys())
    safe_kwargs = {key: value for key, value in candidate_kwargs.items() if key in miner_params and value is not None}

    templates, instances, meta = mine(**safe_kwargs)

    kept = sum(len(items) for items in instances.values())
    print(f"[genorator] chemistry={args.chem}  grid={args.grid}  a={args.a:.3f} Angstrom  source={args.source}")
    print(f"[genorator] motifs ({len(templates)}): {[template.name for template in templates]}")
    per_motif = ", ".join([f"{name}:{len(items)}" for name, items in instances.items()])
    print(f"[genorator] instances: {kept} total placements ({per_motif})")
    print(f"[genorator] wrote: {args.out / 'motifs.json'}, {args.out / 'instances.json'}")
    if args.emit_cifs:
        print(f"[genorator] CIFs: {(args.out / 'motifs_cif')}, {(args.out / 'instances_cif')}")


if __name__ == "__main__":
    main()
