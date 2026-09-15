# qlip/experimental/guidance/properties/_io.py
from __future__ import annotations
import pathlib
import pandas as pd
from typing import Dict, Tuple

# Pair table schema: i,j,t,u,shell,beta  (your fit files use i=j=-1 with type-level (t,u,shell))
def load_pair_beta(path: str | pathlib.Path) -> Dict[Tuple[str, str, int], float]:
    df = pd.read_parquet(path)
    if not {"t","u","shell","beta"}.issubset(df.columns):
        raise ValueError(f"pair table missing columns in {path}")
    out = {}
    for _, r in df.iterrows():
        t = str(r["t"]); u = str(r["u"])
        sh = int(r["shell"])
        out[(t,u,sh)] = float(r["beta"])
    return out

# Motif table schema: motif_id, beta
def load_motif_beta(path: str | pathlib.Path) -> Dict[str, float]:
    df = pd.read_parquet(path)
    if not {"motif_id","beta"}.issubset(df.columns):
        raise ValueError(f"motif table missing columns in {path}")
    return {str(r["motif_id"]): float(r["beta"]) for _, r in df.iterrows()}
