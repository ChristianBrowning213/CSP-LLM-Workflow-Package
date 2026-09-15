import os, json, math
import numpy as np
from typing import List, Dict, Tuple
from pymatgen.ext.matproj import MPRester
from pymatgen.analysis.local_env import CrystalNN

def _frac_wrap(v):
    v = (np.array(v) + 0.5) % 1.0 - 0.5
    return v.tolist()

def _canonicalize(frac_offsets: List[List[float]], snap_half=True, tol=0.08):
    X = np.array(frac_offsets, float)
    # PCA alignment
    X = (X + 0.5) % 1.0 - 0.5
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    Xp = X @ Vt.T
    if snap_half:
        snap = np.round(Xp * 2) / 2
        if np.linalg.norm((snap - Xp), axis=1).mean() < tol:
            Xp = snap
    return [tuple(row.tolist()) for row in Xp]

def mine_units_for_structure(struct, max_neighbors=6, max_unit_size=4):
    """Return small fragments (≤4 atoms): center + up to 3 nearest neighbors."""
    cnn = CrystalNN()
    units = []
    for i, site in enumerate(struct):
        center = site.specie.symbol
        nn = cnn.get_nn_info(struct, i)
        nn = sorted(nn, key=lambda d: d['site'].distance(site))
        for k in range(0, min(max_unit_size-1, len(nn)) + 1):
            comp = [center] + [nn[j]['site'].specie.symbol for j in range(k)]
            offs = [[0.0,0.0,0.0]]
            for j in range(k):
                dv = struct.lattice.get_fractional_coords(nn[j]['site'].coords - site.coords)
                offs.append(_frac_wrap(dv))
            offs_can = _canonicalize(offs)
            units.append({
                "name": f"{''.join(comp)}_CN{len(comp)-1}",
                "composition": comp,
                "anchor_index": 0,
                "frac_offsets": offs_can
            })
    # Dedup by (composition, offsets)
    key = lambda u: (tuple(u["composition"]), tuple(u["frac_offsets"]))
    return list({key(u): u for u in units}.values())

def fetch_mp_structures(chemsys="O-Sr-Ti", n=20):
    key = os.getenv("MP_API_KEY")
    if not key:
        raise RuntimeError("MP_API_KEY not set.")
    with MPRester(key) as mpr:
        docs = mpr.summary.search(chemsys=chemsys, num_documents=n)
        ids = [d.material_id for d in docs]
        return [mpr.get_structure_by_material_id(i) for i in ids]

def mine_units_from_mp(chemsys="O-Sr-Ti", n=20, max_neighbors=6, max_unit_size=4):
    structs = fetch_mp_structures(chemsys=chemsys, n=n)
    out = []
    for s in structs:
        out.extend(mine_units_for_structure(s, max_neighbors=max_neighbors, max_unit_size=max_unit_size))
    # Final dedup
    key = lambda u: (tuple(u["composition"]), tuple(u["frac_offsets"]))
    return list({key(u): u for u in out}.values())
