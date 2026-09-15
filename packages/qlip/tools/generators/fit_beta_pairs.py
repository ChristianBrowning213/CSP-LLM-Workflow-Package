#!/usr/bin/env python3
"""
fit_beta_pairs.py — fit pair-level β (and α) tables for Sr–Ti–O from MP labels.

This script:
  1) Loads MP label parquet files produced by get_Shopping.py
  2) Builds pair-by-shell feature matrices φ_s for each structure from CIFs
  3) Fits Ridge regression (per property)  y ≈ φ_s · β
  4) Emits β tables with schema:  i,j,t,u,shell,beta
     (Site indices i,j are set to -1 to indicate "type-level" coefficients;
      guidance uses the same β for every site pair (i,j) of types (t,u) in a shell.)

Why type-level β?
  - We don’t know your final lattice indices at fit time.
  - Using (t,u,shell) generalizes across cells; guidance can broadcast β over all (i,j) with types (t,u) in that shell.

Neighbor extraction (configurable):
  - By default we use Pymatgen's CrystalNN to determine neighbors, then bucket by distance into shells.
  - You can switch to a fixed radial-slice scheme via --shell-cuts (e.g., 2.2,3.2,4.5) if you prefer.

Usage:
  python fit_beta_pairs.py --root data/sto --shell-cuts 2.4 3.6 5.0 --alpha --gap --kappa --c11

Outputs:
  data/sto/alpha_energy.parquet
  data/sto/beta_gap.parquet
  data/sto/beta_kappa.parquet
  data/sto/beta_C11.parquet
"""

from __future__ import annotations
import os, sys, argparse, pathlib, json, math
from typing import List, Dict, Tuple, Any
from collections import defaultdict

import pandas as pd
import numpy as np
from tqdm import tqdm

from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

# ───────────── Config & utilities ─────────────

TYPE_SET = ("Sr", "Ti", "O")

def ensure_dir(p: pathlib.Path) -> pathlib.Path:
    p.mkdir(parents=True, exist_ok=True); return p

def list_cifs(struct_dir: pathlib.Path) -> List[pathlib.Path]:
    return sorted([p for p in struct_dir.glob("*.cif")])

def load_labels(root: pathlib.Path) -> dict:
    labels = {}
    labels["summary"]  = pd.read_parquet(root/"raw/mp_summary.parquet")
    # Already scalarized in get_Shopping.py:
    labels["kappa"]    = pd.read_parquet(root/"beta_kappa_labels.parquet")
    labels["gap"]      = pd.read_parquet(root/"beta_gap_labels.parquet")
    labels["elastic"]  = pd.read_parquet(root/"beta_C11_labels.parquet")
    return labels

# ───────────── Neighbor & feature building ─────────────

def build_pair_features_for_cif(cif_path: pathlib.Path, shell_edges: List[float]) -> Dict[Tuple[str,str,int], int]:
    """
    Returns counts of (t,u,shell_id) pairs for the structure.
    Symmetric counting: count both (t,u) and (u,t) to align with how Y[(i,j,t,u)] exists in guidance.
    """
    from pymatgen.core.structure import Structure
    from pymatgen.analysis.local_env import CrystalNN

    s: Structure = Structure.from_file(str(cif_path))
    cn = CrystalNN()
    # Pre-cache site types
    site_types = [str(sp) for sp in s.species]
    # Collect pair distances (unordered i<j) + types
    pairs: List[Tuple[str,str,float]] = []
    for i in range(len(s)):
        neighs = cn.get_nn_info(s, i)
        ti = site_types[i]
        for n in neighs:
            j = n["site_index"]
            if j <= i:  # avoid double counting; we'll symmetrize later
                continue
            tj = site_types[j]
            d = float(n["site"].distance(s[i]))
            pairs.append((ti, tj, d))

    # Bin into shells
    shell_ids = lambda r: next((k for k,edge in enumerate(shell_edges, start=1) if r <= edge), len(shell_edges)+1)
    counts: Dict[Tuple[str,str,int], int] = defaultdict(int)
    for (a,b,r) in pairs:
        sh = shell_ids(r)
        counts[(a,b,sh)] += 1
        counts[(b,a,sh)] += 1  # symmetric
    return counts

def assemble_design_matrix(cif_paths: List[pathlib.Path], shell_edges: List[float]) -> Tuple[pd.DataFrame, List[Tuple[str,str,int]]]:
    """
    Builds a design matrix X with columns keyed by (t,u,shell).
    Returns (X_df, columns_key).
    """
    # Build universe of columns
    col_keys: List[Tuple[str,str,int]] = []
    for t in TYPE_SET:
        for u in TYPE_SET:
            for sh in range(1, len(shell_edges)+2):
                col_keys.append((t,u,sh))

    rows = []
    mids = []
    for p in tqdm(cif_paths, desc="features"):
        mid = p.stem
        cnts = build_pair_features_for_cif(p, shell_edges)
        row = {("Sr","Sr",1):0}  # dummy to create dict; we'll overwrite below
        row = {}
        for key in col_keys:
            row[key] = cnts.get(key, 0)
        rows.append(row)
        mids.append(mid)

    X = pd.DataFrame(rows, index=mids)
    X.index.name = "material_id"
    return X, col_keys

def join_labels(X: pd.DataFrame, lbls: dict, prop: str) -> pd.DataFrame:
    """
    Join design matrix with labels for a given property.
    Returns DataFrame indexed by material_id with columns: ['target', <feature tuples...>]
    """
    if prop == "alpha":
        df = lbls["summary"][["material_id","formation_energy_per_atom","energy_above_hull"]].copy()
        df["target"] = df["formation_energy_per_atom"].fillna(df["energy_above_hull"])
        df = df[["material_id","target"]]
    elif prop == "gap":
        df = lbls["gap"][["material_id","band_gap"]].rename(columns={"band_gap":"target"})
    elif prop == "kappa":
        df = lbls["kappa"][["material_id","kappa_scalar"]].rename(columns={"kappa_scalar":"target"})
    elif prop == "c11":
        base = lbls["elastic"][["material_id","C11_proxy","bulk_modulus_vrh","shear_modulus_vrh"]].copy()
        base["target"] = base["C11_proxy"].fillna(base["bulk_modulus_vrh"]).fillna(base["shear_modulus_vrh"])
        df = base[["material_id","target"]]
    else:
        raise ValueError(prop)

    df = df.dropna(subset=["target"])
    Y = df.set_index("material_id").join(X, how="inner")
    # Feature matrix should be numeric; ensure no NaNs in features
    feature_cols = [c for c in Y.columns if c != "target"]
    Y[feature_cols] = Y[feature_cols].fillna(0.0)
    return Y



# ───────────── Fitting & export ─────────────
def fit_ridge_and_export(Y: pd.DataFrame, columns_key: List[Tuple[str,str,int]], out_path: pathlib.Path):
    """
    Fits Ridge: target ~ X (counts). Writes parquet with schema i,j,t,u,shell,beta.
    Uses only tuple-named feature columns (t,u,shell).
    If any expected feature is missing, its coefficient is exported as 0.0.
    """
    # Determine feature columns present in Y
    tuple_cols_present = [c for c in Y.columns if isinstance(c, tuple)]
    if not tuple_cols_present:
        raise RuntimeError("No tuple-named feature columns found in joined table.")

    # Build X in the order of the present tuple columns
    X = Y[tuple_cols_present].fillna(0.0).astype(float).values
    y = Y["target"].astype(float).values

    pipe = Pipeline([
        ("scaler", StandardScaler(with_mean=False)),
        ("ridge", Ridge(alpha=1.0, fit_intercept=True, random_state=0)),
    ])
    pipe.fit(X, y)

    # Map coefs back to present columns
    coef_map = dict(zip(tuple_cols_present, pipe.named_steps["ridge"].coef_))

    # Export in the canonical columns_key order, zero for missing
    out_rows = []
    for key in columns_key:
        b = float(coef_map.get(key, 0.0))
        t, u, sh = key
        out_rows.append({"i": -1, "j": -1, "t": t, "u": u, "shell": sh, "beta": b})

    pd.DataFrame(out_rows).to_parquet(out_path, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/sto", help="Data root (default: data/sto)")
    ap.add_argument("--shell-cuts", nargs="*", type=float, default=[2.4,3.6,5.0],
                    help="Radial shell cutoffs in Å (sorted). Last shell is (prev, +inf).")
    ap.add_argument("--alpha", action="store_true", help="Fit α (energy) table")
    ap.add_argument("--gap",   action="store_true", help="Fit β_gap table")
    ap.add_argument("--kappa", action="store_true", help="Fit β_kappa table")
    ap.add_argument("--c11",   action="store_true", help="Fit β_C11 table")
    args = ap.parse_args()

    root = pathlib.Path(args.root).resolve()
    struct_dir = root / "raw" / "structures"
    if not struct_dir.exists():
        print(f"ERROR: CIF dir not found: {struct_dir}. Re-run get_Shopping.py with CIF export.", file=sys.stderr)
        sys.exit(2)

    lbls = load_labels(root)
    cif_paths = list_cifs(struct_dir)
    if not cif_paths:
        print(f"ERROR: No CIFs found in {struct_dir}", file=sys.stderr)
        sys.exit(2)

    print(f"- Building features for {len(cif_paths)} CIFs using shells: {args.shell_cuts}")
    X, col_keys = assemble_design_matrix(cif_paths, args.shell_cuts)

    ensure_dir(root)

    if args.alpha:
        Ya = join_labels(X, lbls, "alpha")
        if len(Ya) >= 5:
            fit_ridge_and_export(Ya, col_keys, root / "alpha_energy.parquet")
            print("wrote:", root / "alpha_energy.parquet")
        else:
            print("WARN: not enough alpha label rows after join; skipping.")

    if args.gap:
        Yg = join_labels(X, lbls, "gap")
        if len(Yg) >= 5:
            fit_ridge_and_export(Yg, col_keys, root / "beta_gap.parquet")
            print("wrote:", root / "beta_gap.parquet")
        else:
            print("WARN: not enough gap label rows after join; skipping.")

    if args.kappa:
        Yk = join_labels(X, lbls, "kappa")
        if len(Yk) >= 5:
            fit_ridge_and_export(Yk, col_keys, root / "beta_kappa.parquet")
            print("wrote:", root / "beta_kappa.parquet")
        else:
            print("WARN: not enough kappa label rows after join; skipping.")

    if args.c11:
        Yc = join_labels(X, lbls, "c11")
        if len(Yc) >= 5:
            fit_ridge_and_export(Yc, col_keys, root / "beta_C11.parquet")
            print("wrote:", root / "beta_C11.parquet")
        else:
            print("WARN: not enough C11 label rows after join; skipping.")

if __name__ == "__main__":
    main()
