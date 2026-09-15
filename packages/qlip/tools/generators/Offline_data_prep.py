#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline_data_prep.py — One-stop offline data prep for Sr–Ti–O guidance.
Place in /Genorator. Run subcommands to generate the missing external pieces.

Installs you may need:
  pip install pandas pyarrow tqdm

What this script prepares (all under data/sto/ by default):

1) Electron effective mass (m*)
   - From MPContribs/AMSET summary if available:
       python Offline_data_prep.py mstar-mp --out data/sto --chemsys Sr-Ti-O
     (uses MP_API_KEY; tries summary.transport_properties)
   - From a JARVIS/other CSV you export:
       python Offline_data_prep.py mstar-csv --csv path/to/jarvis_transport.csv --mid-col material_id --me-col me_eff
   - From your BoltzTraP2 JSON outputs:
       python Offline_data_prep.py mstar-bt2 --runs runs_sto --pattern bt2_out.json
   => writes: data/sto/beta_mstar_labels.parquet  (material_id, me_eff[, mh_eff])

2) Oxygen-vacancy motifs β (formation/migration → motif β)
   - You provide a defects labels parquet with columns:
       [material_id, motif_key, E_form_eV, Emig_eV(optional)]
   - And a CSV mapping: motif_key,motif_id
       python Offline_data_prep.py vo-motifs --defects data/sto/defects_vo_labels.parquet --map data/sto/motif_key_to_id.csv
   => writes: data/sto/beta_vo_motif.parquet (motif_id, beta)
      (beta = scaled median of -E_form_eV per motif_id; tweak scaling flags below.)

3) Band-edge alignment labels (CBM/VBM vs vacuum)
   - Provide a CSV/Parquet with columns: material_id, cbm_ev, vbm_ev
       python Offline_data_prep.py edges --file data/sto/edge_align_labels.csv
   => writes: data/sto/beta_cbm_labels.parquet, data/sto/beta_vbm_labels.parquet

4) Lattice thermal conductivity labels (κ_L)
   - Provide a CSV/Parquet with columns: material_id, kappa_L_WmK
       python Offline_data_prep.py kth --file data/sto/kappa_L_labels.csv
   => writes: data/sto/beta_kth_labels.parquet

5) Density constants
   - Either write simple placeholders, or compute V_cell from a0:
       python Offline_data_prep.py density --out data/sto --a0 3.905
       # OR specify explicit values:
       python Offline_data_prep.py density --out data/sto --Vcell 59.3 --vol Sr:1.0 Ti:0.75 O:0.50
   => writes: data/sto/per_type_volume.json, data/sto/cell.json

Notes
- This script **does not** fit pair β tables; use fit_beta_pairs.py for that step.
- For CSV inputs that don’t have MP material_id, create a small mapping CSV first
  (e.g., formula → material_id) and merge externally, or add a --map CSV with two cols:
  source_key,material_id and pass --merge-on <source_key>.
"""

from __future__ import annotations
import os, sys, json, argparse, pathlib
from typing import Optional, List
import pandas as pd

try:
    from tqdm import tqdm
    TQDM = True
except Exception:
    TQDM = False

def tqdmit(it, **kw):
    return tqdm(it, **kw) if TQDM else it

# --------------------------------------------------------------------------- #
# Utilities
# --------------------------------------------------------------------------- #

def ensure_dir(p: pathlib.Path) -> pathlib.Path:
    p.mkdir(parents=True, exist_ok=True); return p

def write_parquet(df: pd.DataFrame, path: pathlib.Path):
    ensure_dir(path.parent)
    df.to_parquet(path, index=False)

def write_json(obj, path: pathlib.Path):
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

# --------------------------------------------------------------------------- #
# 1) m* labels
# --------------------------------------------------------------------------- #

def mstar_from_mpcontribs(chemsys: str, out_root: pathlib.Path):
    """
    Try to extract effective mass from MP Summary 'transport_properties' (AMSET/MPContribs).
    Coverage is sparse; treat as best-effort.
    """
    api = os.getenv("MP_API_KEY")
    if not api:
        sys.exit("MP_API_KEY not set. Export it and retry.")
    try:
        from mp_api.client import MPRester
    except Exception as e:
        sys.exit("mp-api not installed. pip install mp-api")

    rows = []
    with MPRester(api) as mpr:
        docs = mpr.summary.search(chemsys=chemsys, fields=["material_id","transport_properties"], num_chunks=200, chunk_size=1000)
        for d in docs:
            tp = getattr(d, "transport_properties", None)
            if isinstance(tp, dict) and ("me_eff" in tp or "mh_eff" in tp):
                me = tp.get("me_eff", None)
                mh = tp.get("mh_eff", None)
                rows.append({"material_id": d.material_id,
                             "me_eff": float(me) if me is not None else None,
                             "mh_eff": float(mh) if mh is not None else None})

    df = pd.DataFrame(rows).drop_duplicates(subset=["material_id"])
    out = out_root / "beta_mstar_labels.parquet"
    write_parquet(df, out)
    print(f"[m*] wrote {out}  (n={len(df)})")


def mstar_from_csv(csv_path: pathlib.Path, out_root: pathlib.Path, mid_col: str, me_col: str, mh_col: Optional[str], map_csv: Optional[pathlib.Path], merge_on: Optional[str]):
    """
    Import m* labels from a CSV you exported (JARVIS/your pipeline).
    If the CSV lacks 'material_id', provide a mapping CSV with columns [<merge_on>, material_id].
    """
    df = pd.read_csv(csv_path)
    if "material_id" not in df.columns:
        if not map_csv or not merge_on or merge_on not in df.columns:
            sys.exit("The CSV lacks 'material_id'. Provide --map CSV with columns [<merge_on>,material_id] and --merge-on <col>.")
        m = pd.read_csv(map_csv)
        if "material_id" not in m.columns or merge_on not in m.columns:
            sys.exit("Mapping CSV must have columns [<merge_on>, material_id].")
        df = df.merge(m[[merge_on, "material_id"]], on=merge_on, how="inner")

    cols = ["material_id", me_col] + ([mh_col] if mh_col else [])
    df = df[cols].rename(columns={me_col: "me_eff", mh_col or "": "mh_eff"}).dropna(subset=["me_eff"])
    out = out_root / "beta_mstar_labels.parquet"
    write_parquet(df[["material_id", "me_eff"] + (["mh_eff"] if mh_col else [])], out)
    print(f"[m*] wrote {out}  (n={len(df)})")


def mstar_from_bt2(runs_dir: pathlib.Path, out_root: pathlib.Path, pattern: str = "bt2_out.json"):
    """
    Parse BoltzTraP2 outputs located under runs_dir/<material_id>/<pattern>.
    Expect a JSON with a field like 'cbm_mass_tensor_eigs' = [mx,my,mz].
    """
    rows = []
    for mid_dir in tqdmit([p for p in runs_dir.iterdir() if p.is_dir()], desc="bt2 dirs"):
        p = mid_dir / pattern
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            eigs = data.get("cbm_mass_tensor_eigs") or data.get("meff_eigs") or None
            if eigs and isinstance(eigs, (list, tuple)) and len(eigs) == 3:
                # geometric mean as a scalar m*
                mstar = float((eigs[0]*eigs[1]*eigs[2]) ** (1/3))
                rows.append({"material_id": mid_dir.name, "me_eff": mstar})
        except Exception as e:
            print(f"warn: failed {p}: {e}")

    df = pd.DataFrame(rows).drop_duplicates(subset=["material_id"])
    out = out_root / "beta_mstar_labels.parquet"
    write_parquet(df, out)
    print(f"[m*] wrote {out}  (n={len(df)})")

# --------------------------------------------------------------------------- #
# 2) V_O motif β from defects labels + mapping
# --------------------------------------------------------------------------- #

def vo_motifs_from_defects(defects_parquet: pathlib.Path, mapping_csv: pathlib.Path, out_root: pathlib.Path,
                           use_median: bool = True, scale: float = 10.0, clip: float = 15.0):
    """
    defects_parquet columns: [material_id, motif_key, E_form_eV, Emig_eV(optional)]
    mapping_csv columns: motif_key,motif_id
    β_vo: scaled median (or mean) of -E_form_eV per motif_id
    """
    df = pd.read_parquet(defects_parquet)
    mp = pd.read_csv(mapping_csv)
    if "motif_key" not in df.columns or "E_form_eV" not in df.columns:
        sys.exit("defects parquet must have columns [motif_key, E_form_eV, material_id].")
    if "motif_key" not in mp.columns or "motif_id" not in mp.columns:
        sys.exit("mapping CSV must have columns [motif_key, motif_id].")
    df = df.merge(mp[["motif_key", "motif_id"]], on="motif_key", how="left").dropna(subset=["motif_id"])

    df["_raw_beta"] = -df["E_form_eV"]  # lower formation energy → higher β (more favorable)
    group = df.groupby("motif_id")["_raw_beta"]
    agg = group.median() if use_median else group.mean()
    ser = agg.copy()

    # robust scale to O(1–10)
    med = float(ser.median()) if len(ser) else 0.0
    mad = float((ser - med).abs().median()) or 1.0
    ser = scale * (ser - med) / mad
    ser = ser.clip(-clip, clip)

    out_df = ser.reset_index().rename(columns={0: "beta", "_raw_beta": "beta"})
    out = out_root / "beta_vo_motif.parquet"
    write_parquet(out_df.rename(columns={0: "beta"}), out)
    print(f"[VO] wrote {out}  (n={len(out_df)})")

# --------------------------------------------------------------------------- #
# 3) Band-edge alignment labels (CBM/VBM)
# --------------------------------------------------------------------------- #

def edges_from_labels(file_path: pathlib.Path, out_root: pathlib.Path):
    """
    Input CSV/Parquet with columns: material_id, cbm_ev, vbm_ev
    Writes two parquet files the fitter can consume later.
    """
    df = pd.read_csv(file_path) if file_path.suffix.lower() in (".csv", ".txt") else pd.read_parquet(file_path)
    need = {"material_id", "cbm_ev", "vbm_ev"}
    if not need.issubset(df.columns):
        sys.exit(f"{file_path} must contain columns {need}")
    cbm = df[["material_id", "cbm_ev"]].dropna()
    vbm = df[["material_id", "vbm_ev"]].dropna()
    write_parquet(cbm.rename(columns={"cbm_ev": "cbm"}), out_root / "beta_cbm_labels.parquet")
    write_parquet(vbm.rename(columns={"vbm_ev": "vbm"}), out_root / "beta_vbm_labels.parquet")
    print(f"[edges] wrote beta_cbm_labels.parquet (n={len(cbm)}), beta_vbm_labels.parquet (n={len(vbm)})")

# --------------------------------------------------------------------------- #
# 4) Lattice thermal conductivity labels (κ_L)
# --------------------------------------------------------------------------- #

def kth_from_labels(file_path: pathlib.Path, out_root: pathlib.Path, mid_col: str = "material_id", k_col: str = "kappa_L_WmK"):
    """
    Input CSV/Parquet with columns: material_id, kappa_L_WmK
    Writes: beta_kth_labels.parquet
    """
    df = pd.read_csv(file_path) if file_path.suffix.lower() in (".csv", ".txt") else pd.read_parquet(file_path)
    if mid_col not in df.columns or k_col not in df.columns:
        sys.exit(f"{file_path} must contain columns [{mid_col}, {k_col}]")
    out = out_root / "beta_kth_labels.parquet"
    write_parquet(df[[mid_col, k_col]].rename(columns={mid_col: "material_id", k_col: "kappa_L_WmK"}), out)
    print(f"[kth] wrote {out}  (n={len(df)})")

# --------------------------------------------------------------------------- #
# 5) Density constants
# --------------------------------------------------------------------------- #

def density_constants(out_root: pathlib.Path, Vcell: Optional[float], a0: Optional[float], vols: Optional[List[str]]):
    """
    Write per_type_volume.json and cell.json.
    - If a0 is provided (Å): V_cell = a0^3.
    - Else if Vcell provided, use that.
    - vols is a list of entries like Sr:1.0 Ti:0.75 O:0.50 ; defaults used if not provided.
    """
    if a0 and not Vcell:
        Vcell = float(a0) ** 3
    if not Vcell:
        Vcell = 59.3  # placeholder; edit later

    per_type_volume = {"Sr": 1.00, "Ti": 0.75, "O": 0.50}
    if vols:
        for tok in vols:
            if ":" not in tok: continue
            k, v = tok.split(":", 1)
            try:
                per_type_volume[k.strip()] = float(v)
            except Exception:
                pass

    write_json(per_type_volume, out_root / "per_type_volume.json")
    write_json({"V_cell": Vcell}, out_root / "cell.json")
    print(f"[density] wrote per_type_volume.json and cell.json (V_cell={Vcell:.4f} Å^3)")

# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Offline data prep for Sr–Ti–O guidance")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # m* from MPContribs/summary
    sp = sub.add_parser("mstar-mp", help="m* labels from MP Summary (transport_properties) for a chemsys")
    sp.add_argument("--chemsys", default="Sr-Ti-O")
    sp.add_argument("--out", default="data/sto")

    # m* from CSV (e.g., JARVIS export)
    sp = sub.add_parser("mstar-csv", help="m* labels from CSV; expect material_id or provide --map")
    sp.add_argument("--csv", required=True, type=pathlib.Path)
    sp.add_argument("--out", default="data/sto")
    sp.add_argument("--mid-col", default="material_id")
    sp.add_argument("--me-col", default="me_eff")
    sp.add_argument("--mh-col", default=None)
    sp.add_argument("--map", type=pathlib.Path, help="mapping CSV with [<merge-on>, material_id]")
    sp.add_argument("--merge-on", type=str, help="column name present in --csv and --map to join on")

    # m* from BoltzTraP2 runs
    sp = sub.add_parser("mstar-bt2", help="m* labels from BoltzTraP2 JSON outputs")
    sp.add_argument("--runs", required=True, type=pathlib.Path, help="directory with subfolders named by material_id")
    sp.add_argument("--pattern", default="bt2_out.json")
    sp.add_argument("--out", default="data/sto")

    # VO motif β
    sp = sub.add_parser("vo-motifs", help="β_vo from defects labels + motif_key→motif_id map")
    sp.add_argument("--defects", required=True, type=pathlib.Path)
    sp.add_argument("--map", required=True, type=pathlib.Path, dest="map_csv")
    sp.add_argument("--out", default="data/sto")
    sp.add_argument("--use-median", action="store_true", help="use median (default) instead of mean")
    sp.add_argument("--mean", dest="use_median", action="store_false", help="use mean instead of median")
    sp.add_argument("--scale", type=float, default=10.0)
    sp.add_argument("--clip", type=float, default=15.0)

    # Band edges labels
    sp = sub.add_parser("edges", help="CBM/VBM labels from CSV/Parquet (material_id, cbm_ev, vbm_ev)")
    sp.add_argument("--file", required=True, type=pathlib.Path)
    sp.add_argument("--out", default="data/sto")

    # Thermal conductivity labels
    sp = sub.add_parser("kth", help="κ_L labels from CSV/Parquet (material_id, kappa_L_WmK)")
    sp.add_argument("--file", required=True, type=pathlib.Path)
    sp.add_argument("--out", default="data/sto")
    sp.add_argument("--mid-col", default="material_id")
    sp.add_argument("--k-col", default="kappa_L_WmK")

    # Density constants
    sp = sub.add_parser("density", help="write per_type_volume.json and cell.json")
    sp.add_argument("--out", default="data/sto")
    sp.add_argument("--Vcell", type=float, default=None, help="Cell volume in Å^3")
    sp.add_argument("--a0", type=float, default=None, help="If given, sets V_cell = a0^3")
    sp.add_argument("--vol", nargs="*", default=None, help="Per-type volumes like Sr:1.0 Ti:0.75 O:0.50")

    args = ap.parse_args()
    out_root = ensure_dir(pathlib.Path(args.out))

    if args.cmd == "mstar-mp":
        mstar_from_mpcontribs(args.chemsys, out_root)

    elif args.cmd == "mstar-csv":
        mstar_from_csv(args.csv, out_root, args.mid_col, args.me_col, args.mh_col, args.map, args.merge_on)

    elif args.cmd == "mstar-bt2":
        mstar_from_bt2(args.runs, out_root, args.pattern)

    elif args.cmd == "vo-motifs":
        vo_motifs_from_defects(args.defects, args.map_csv, out_root, use_median=args.use_median, scale=args.scale, clip=args.clip)

    elif args.cmd == "edges":
        edges_from_labels(args.file, out_root)

    elif args.cmd == "kth":
        kth_from_labels(args.file, out_root, mid_col=args.mid_col, k_col=args.k_col)

    elif args.cmd == "density":
        density_constants(out_root, args.Vcell, args.a0, args.vol)

    else:
        sys.exit("Unknown subcommand")

if __name__ == "__main__":
    main()
