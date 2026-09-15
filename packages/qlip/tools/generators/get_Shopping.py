#!/usr/bin/env python3
"""
get_Shopping.py — Fetch external data for Sr–Ti–O guidance (Materials Project first),
and scaffold placeholders for items that require non-MP sources.

Usage:
  MP_API_KEY=... python get_Shopping.py --chemsys Sr-Ti-O --out data/sto

What this script DOES fetch from MP:
  ✓ Formation energies / energy above hull (stability labels)
  ✓ Band gaps (GGA/GGA+U; summary)
  ✓ Dielectric tensors (where available)
  ✓ Elastic tensors (C_ij, bulk & shear moduli) (where available)
  ✓ Structures (CIFs) for local feature building (optional export)

What this script CANNOT fetch from MP core endpoints (placeholders created):
  ✗ Electron effective masses (m*) — use MPContribs/AMSET runs, JARVIS, or run BoltzTraP2
  ✗ Oxygen-vacancy (V_O) formation/migration data — use Defects@MP, MPContribs, NOMAD, or do DFT
  ✗ Band-edge absolute alignment (CBM/VBM vs vacuum/redox) — use HSE/GW literature, JARVIS
  ✗ Thermal conductivity (κ_th) robust set — AFLOW AEL/AGL, JARVIS (sparse for perovskites)
  ✗ Shannon ionic radii / per-type volumes (constants) — handbooks (Shannon 1976), CRC/NIST

The script writes:
  data/sto/
    raw/                     # raw MP pulls (JSONL/Parquet)
      mp_summary.parquet
      mp_dielectric.parquet
      mp_elastic.parquet
      structures/ *.cif      # optional CIF dump
    alpha_energy_labels.parquet     # labels for later α fitting (formation energies etc.)
    beta_gap_labels.parquet         # labels for later β_gap fitting
    beta_kappa_labels.parquet       # labels for later β_kappa fitting
    beta_C11_labels.parquet         # labels for later β_C11 fitting
    # Placeholders you must fill later from non-MP sources:
    beta_mstar.parquet              # (empty scaffold) effective mass β table
    beta_vo_motif.parquet           # (empty scaffold) oxygen vacancy motif β
    beta_cbm.parquet                # (empty scaffold) CBM alignment β
    beta_vbm.parquet                # (empty scaffold) VBM alignment β
    beta_kth.parquet                # (empty scaffold) thermal conductivity β
    per_type_volume.json            # (placeholder constants; edit)
    cell.json                       # (placeholder; edit or regenerate per cell)
    reference_values.json           # (starter refs; edit/expand)

Note: This script only fetches LABELS from MP. Converting labels into pair/motif β tables
is a separate "fit" step in your pipeline (regression from local descriptors). This keeps
the “outside data” collection cleanly separated from model-building.
"""

from __future__ import annotations
import os, sys, json, gzip, argparse, pathlib, itertools
from dataclasses import dataclass
from typing import Iterable, Optional, List, Dict, Any

import pandas as pd

try:
    from mp_api.client import MPRester
except ImportError:
    print("ERROR: mp-api not installed. Run: pip install mp-api", file=sys.stderr)
    sys.exit(1)

try:
    from tqdm import tqdm
    TQDM = True
except Exception:
    TQDM = False


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def ensure_dir(p: pathlib.Path) -> pathlib.Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def write_parquet(df: pd.DataFrame, path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # If empty, still write a schema via an empty df
    df.to_parquet(path, index=False)

def write_json(obj: Any, path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

def tqdm_wrap(iterable, **kwargs):
    if TQDM:
        return tqdm(iterable, **kwargs)
    return iterable


# ──────────────────────────────────────────────────────────────────────────────
# MP fetchers
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MPFetchConfig:
    chemsys: str = "Sr-Ti-O"
    # Optional: expand to related ABO3 (BaTiO3, CaTiO3) by toggling below.
    include_related: bool = False
    # If True, also export CIFs to raw/structures
    dump_cifs: bool = True
    # Max docs (0 or None = no cap)
    max_docs: Optional[int] = None


def mp_summary_fetch(mpr: MPRester, cfg: MPFetchConfig) -> pd.DataFrame:
    """
    Fetch MP summary docs for chemsys filter(s).
    Fields: material_id, formula_pretty, chemsys, formation_energy_per_atom, energy_above_hull,
            band_gap, density, nsites, structure (dict), deprecated flags, etc.
    """
    filters = [cfg.chemsys]
    if cfg.include_related:
        # Example related: Ba-Ti-O, Ca-Ti-O
        filters += ["Ba-Ti-O", "Ca-Ti-O"]

    rows = []
    for cs in filters:
        # The summary endpoint is generous and fast; we select a fields subset to keep files light.
        # If you need more, expand "fields".
        docs = mpr.materials.summary.search(
            chemsys=cs,
            fields=[
                "material_id",
                "formula_pretty",
                "chemsys",
                "formation_energy_per_atom",
                "energy_above_hull",
                "band_gap",
                "density",
                "nsites",
                "structure",
                "deprecated",
            ],
            num_chunks=200, chunk_size=1000,
        )
        for d in docs:
            rows.append({
                "material_id": d.material_id,
                "formula_pretty": d.formula_pretty,
                "chemsys": d.chemsys,
                "formation_energy_per_atom": d.formation_energy_per_atom,
                "energy_above_hull": d.energy_above_hull,
                "band_gap": d.band_gap,
                "density": d.density,
                "nsites": d.nsites,
                "structure": d.structure.as_dict() if getattr(d, "structure", None) else None,
                "deprecated": getattr(d, "deprecated", False),
            })
            if cfg.max_docs and len(rows) >= cfg.max_docs:
                break
        if cfg.max_docs and len(rows) >= cfg.max_docs:
            break

    df = pd.DataFrame(rows).drop_duplicates(subset=["material_id"])
    return df


def mp_dielectric_fetch(mpr: MPRester, material_ids: Iterable[str]) -> pd.DataFrame:
    """
    Fetch dielectric tensors for given material_ids (where available).
    Fields: material_id, e_total, e_electronic, e_ionic, n
    """
    rows = []
    # mp-api dielectric endpoint supports search by material_ids batch
    chunks = _chunks(list(material_ids), 200)
    for chunk in tqdm_wrap(chunks, desc="dielectric batches"):
        docs = mpr.materials.dielectric.search(material_ids=chunk, fields=[
            "material_id", "warnings",
            "e_total", "e_electronic", "e_ionic", "n",
        ])
        for d in docs:
            rows.append({
                "material_id": d.material_id,
                "e_total": d.e_total,           # 3x3 or scalar (mp-api returns tensor; store raw)
                "e_electronic": d.e_electronic,
                "e_ionic": d.e_ionic,
                "n": d.n,                       # refractive index if present
                "dielectric_warnings": getattr(d, "warnings", None),
            })
    return pd.DataFrame(rows)


def mp_elastic_fetch(mpr, material_ids):
    """
    Fetch elasticity using new route + field names, and RETURN ONLY SCALARS:
      material_id, C11_proxy, bulk_modulus_vrh, shear_modulus_vrh,
      homogeneous_poisson, universal_anisotropy
    This avoids serializing ElasticTensorDoc into Parquet.
    """
    from math import isnan

    def _c11_from_doc(doc):
        try:
            et = getattr(doc, "elastic_tensor", None)
            # MP returns ElasticTensorDoc with attribute ".raw" (6x6)
            raw = getattr(et, "raw", None)
            if raw and isinstance(raw, (list, tuple)) and len(raw) == 6 and len(raw[0]) == 6:
                return float(raw[0][0])
        except Exception:
            pass
        return None

    def _vrh_or_scalar(x):
        # bulk_modulus / shear_modulus may be dicts with 'vrh' or a scalar
        if isinstance(x, dict):
            for k in ("vrh", "VRH", "Voigt-Reuss-Hill"):
                if k in x and x[k] is not None:
                    try: return float(x[k])
                    except Exception: pass
            # fallback to any numeric
            for _, v in x.items():
                try: return float(v)
                except Exception: pass
            return None
        try:
            return float(x)
        except Exception:
            return None

    rows = []
    for chunk in _chunks(list(material_ids), 200):
        docs = mpr.materials.elasticity.search(
            material_ids=chunk,
            fields=[
                "material_id",
                "elastic_tensor",
                "bulk_modulus",
                "shear_modulus",
                "homogeneous_poisson",
                "universal_anisotropy",
                "warnings",
            ],
        )
        for d in docs:
            rows.append({
                "material_id": d.material_id,
                "C11_proxy": _c11_from_doc(d),
                "bulk_modulus_vrh": _vrh_or_scalar(getattr(d, "bulk_modulus", None)),
                "shear_modulus_vrh": _vrh_or_scalar(getattr(d, "shear_modulus", None)),
                "homogeneous_poisson": getattr(d, "homogeneous_poisson", None),
                "universal_anisotropy": getattr(d, "universal_anisotropy", None),
                # keep warnings if you want, but NOT the tensors themselves
                "elastic_warnings": getattr(d, "warnings", None),
            })
    import pandas as pd
    return pd.DataFrame(rows)




def export_cifs_from_summary(df_summary: pd.DataFrame, out_dir: pathlib.Path):
    """
    Dump CIFs from the summary 'structure' payloads for downstream feature building / sanity checks.
    """
    ensure_dir(out_dir)
    n = 0
    for _, r in tqdm_wrap(df_summary.iterrows(), total=len(df_summary), desc="write CIFs"):
        struct = r.get("structure")
        mid = r["material_id"]
        if not struct:
            continue
        cif_path = out_dir / f"{mid}.cif"
        try:
            # Lazy import to avoid hard dependency; fall back to JSON if pymatgen absent.
            from pymatgen.core.structure import Structure
            s = Structure.from_dict(struct)
            s.to(filename=str(cif_path))
            n += 1
        except Exception:
            # Write JSON as fallback
            with open(out_dir / f"{mid}.json", "w", encoding="utf-8") as f:
                json.dump(struct, f)
            n += 1
    return n


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


# ──────────────────────────────────────────────────────────────────────────────
# Writers for your guidance shopping list
# (labels now; β fitting is a separate step)
# ──────────────────────────────────────────────────────────────────────────────

def write_alpha_energy_labels(df_summary: pd.DataFrame, out_path: pathlib.Path):
    """
    For α (energy) fitting later: we store labels compatible with α regression
    (formation_energy_per_atom, energy_above_hull) keyed by material_id.
    """
    cols = ["material_id", "formula_pretty", "chemsys",
            "formation_energy_per_atom", "energy_above_hull", "density", "nsites"]
    df = df_summary[cols].copy()
    write_parquet(df, out_path)


def write_beta_gap_labels(df_summary: pd.DataFrame, out_path: pathlib.Path):
    """
    For β_gap fitting later: store band_gap labels keyed by material_id.
    """
    cols = ["material_id", "formula_pretty", "chemsys", "band_gap"]
    df = df_summary[cols].copy()
    write_parquet(df, out_path)


def write_beta_kappa_labels(df_dielectric: pd.DataFrame, out_path: pathlib.Path):
    """
    For β_kappa fitting later: store (scalarized) dielectric 'kappa' labels.
    We derive a single scalar kappa from e_total as trace(e_total)/3 when tensor is present.
    """
    if df_dielectric.empty:
        write_parquet(pd.DataFrame(columns=["material_id", "kappa_scalar"]), out_path)
        return

    def _scalarize_kappa(et):
        # et may be a list[list] 3x3; return average diagonal if plausible
        try:
            if isinstance(et, (list, tuple)) and len(et) == 3 and all(isinstance(r, (list, tuple)) and len(r) == 3 for r in et):
                return float((et[0][0] + et[1][1] + et[2][2]) / 3.0)
        except Exception:
            pass
        # fallback: None
        return None

    df = df_dielectric[["material_id", "e_total"]].copy()
    df["kappa_scalar"] = df["e_total"].map(_scalarize_kappa)
    df = df.dropna(subset=["kappa_scalar"])
    write_parquet(df[["material_id", "kappa_scalar"]], out_path)

def write_beta_C11_labels(df_elastic: pd.DataFrame, out_path: pathlib.Path):
    """
    Pass through scalarized elasticity labels to Parquet.
    Expects df_elastic to already contain:
      - material_id
      - C11_proxy
      - bulk_modulus_vrh
      - shear_modulus_vrh
    Any missing columns are created empty.
    """
    import pandas as pd

    need = ["material_id", "C11_proxy", "bulk_modulus_vrh", "shear_modulus_vrh"]
    if df_elastic is None or df_elastic.empty:
        df = pd.DataFrame(columns=need)
    else:
        df = df_elastic.copy()
        for col in need:
            if col not in df.columns:
                df[col] = pd.NA
        df = df[need]

    write_parquet(df, out_path)



def scaffold_placeholders(out_dir: pathlib.Path):
    """
    Create empty, schema-stable files for items not obtainable directly from MP.
    """
    # Effective mass β table (pairs)
    write_parquet(pd.DataFrame(columns=["i","j","t","u","shell","beta"]),
                  out_dir / "beta_mstar.parquet")

    # Oxygen vacancy motif β table (motifs)
    write_parquet(pd.DataFrame(columns=["motif_id","beta"]),
                  out_dir / "beta_vo_motif.parquet")

    # Band-edge alignment β tables
    write_parquet(pd.DataFrame(columns=["i","j","t","u","shell","beta"]),
                  out_dir / "beta_cbm.parquet")
    write_parquet(pd.DataFrame(columns=["i","j","t","u","shell","beta"]),
                  out_dir / "beta_vbm.parquet")

    # Thermal conductivity β table
    write_parquet(pd.DataFrame(columns=["i","j","t","u","shell","beta"]),
                  out_dir / "beta_kth.parquet")

    # Constants (you will edit these)
    per_type_volume = {"Sr": 1.00, "Ti": 0.75, "O": 0.50}  # placeholders (replace with Shannon/handbook-derived)
    write_json(per_type_volume, out_dir / "per_type_volume.json")
    write_json({"V_cell": 59.3}, out_dir / "cell.json")

    # Reference values (starter sanity checks; edit/expand)
    refs = {
        "SrTiO3": {
            "a0_A": 3.905,
            "Eg_room_eV": 3.2,
            "kappa_room": 300
        },
        "notes": "Edit with literature values you trust; used only for sanity checks."
    }
    write_json(refs, out_dir / "reference_values.json")


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Fetch MP data for Sr–Ti–O guidance and scaffold missing pieces.")
    ap.add_argument("--chemsys", default="Sr-Ti-O", help="Chemical system filter (default: Sr-Ti-O)")
    ap.add_argument("--out", default="data/sto", help="Output folder (default: data/sto)")
    ap.add_argument("--related", action="store_true", help="Also include related ABO3 like Ba-Ti-O, Ca-Ti-O")
    ap.add_argument("--no-cif", action="store_true", help="Do not export CIFs")
    ap.add_argument("--max-docs", type=int, default=0, help="Cap the number of summary docs (0 = no cap)")
    args = ap.parse_args()

    out_root = ensure_dir(pathlib.Path(args.out))
    out_raw = ensure_dir(out_root / "raw")
    out_structs = ensure_dir(out_raw / "structures")

    api_key = os.getenv("MP_API_KEY")
    if not api_key:
        print("ERROR: MP_API_KEY not set in environment.", file=sys.stderr)
        sys.exit(2)

    cfg = MPFetchConfig(
        chemsys=args.chemsys,
        include_related=bool(args.related),
        dump_cifs=not args.no_cif,
        max_docs=(None if args.max_docs in (0, None) else args.max_docs),
    )

    print("Connecting to Materials Project…")
    with MPRester(api_key) as mpr:
        print(f"- Fetching summary for {cfg.chemsys} (related={cfg.include_related}) …")
        df_summary = mp_summary_fetch(mpr, cfg)
        write_parquet(df_summary.drop(columns=["structure"], errors="ignore"),
              out_raw / "mp_summary.parquet")

        print(f"  wrote: {out_raw / 'mp_summary.parquet'}  (n={len(df_summary)})")

        mids = df_summary["material_id"].tolist()

        print("- Fetching dielectric tensors …")
        df_diel = mp_dielectric_fetch(mpr, mids)
        write_parquet(df_diel, out_raw / "mp_dielectric.parquet")
        print(f"  wrote: {out_raw / 'mp_dielectric.parquet'}  (n={len(df_diel)})")

        print("- Fetching elastic tensors …")
        df_el = mp_elastic_fetch(mpr, mids)
        write_parquet(df_el, out_raw / "mp_elastic.parquet")
        print(f"  wrote: {out_raw / 'mp_elastic.parquet'}  (n={len(df_el)})")

        if cfg.dump_cifs:
            print("- Exporting CIFs from summary structures …")
            n_cif = export_cifs_from_summary(df_summary, out_structs)
            print(f"  wrote: {n_cif} structure files to {out_structs}")

    # Write label tables for later β/α fitting
    print("- Writing label tables for later fitting …")
    write_alpha_energy_labels(df_summary, out_root / "alpha_energy_labels.parquet")
    write_beta_gap_labels(df_summary, out_root / "beta_gap_labels.parquet")
    write_beta_kappa_labels(df_diel, out_root / "beta_kappa_labels.parquet")
    write_beta_C11_labels(df_el, out_root / "beta_C11_labels.parquet")
    print(f"  wrote: alpha_energy_labels.parquet, beta_gap_labels.parquet, beta_kappa_labels.parquet, beta_C11_labels.parquet")

    # Placeholders for non-MP sources
    print("- Scaffolding placeholders for non-MP data …")
    scaffold_placeholders(out_root)
    print(f"  wrote placeholders in {out_root}")

    # Friendly recap
    print("\nDONE. Next steps:")
    print("  1) Fit α/β tables from these labels using your pair/motif features (separate step).")
    print("  2) Fill non-MP placeholders from: MPContribs/AMSET (m*), Defects@MP/NOMAD (V_O), JARVIS (dielectric/elastic/alignments), AFLOW (κ_th), Shannon radii (per_type_volume).")
    print("  3) Drop the fitted α/β files into qlip/experimental/guidance properties as per your Sr–Ti–O guidance spec.\n")


if __name__ == "__main__":
    main()
