# api.py
import json
from pathlib import Path
from typing import Dict, List, Tuple
import numpy as np

# local helpers (you already have these in /tools/generators from earlier)
from .chem_registry import plan_for
from .motif_extract import perovskite_TiO6_motif, perovskite_SrO12_motif
from .grid_snap import prepare_motif_instances
from ..sources.mp_miner import mine_units_from_mp


def _uniform_grid(g: int) -> List[Tuple[float, float, float]]:
    # even g strongly recommended; returns fractional coordinates
    us = np.linspace(0, 1, g, endpoint=False)
    return [(float(x), float(y), float(z)) for x in us for y in us for z in us]

def _emit_motifs(motif_emitters: List[str]) -> List[Dict]:
    # call motif factory functions by name
    name_to_fn = {
        "perovskite_TiO6_motif": perovskite_TiO6_motif,
        "perovskite_SrO12_motif": perovskite_SrO12_motif,
    }
    motifs = []
    for k in motif_emitters:
        if k not in name_to_fn:
            raise ValueError(f"Unknown motif emitter: {k}")
        motifs.append(name_to_fn[k]())
    return motifs

def _decorate_structure(struct, decorator: Dict[str, str]):
    # Map prototype labels (A,B,X,...) to real species (Sr,Ti,O,...)
    sp = [decorator.get(str(s), str(s)) for s in struct.species]
    struct.remove_sites(range(len(struct)))  # nuke then re-add
    # Rebuild with decorated species at same fractional coords
    # (A simple rebuild; you may prefer a safer rewrite if you keep site properties)
    from pymatgen.core import Structure as PMGStructure
    pmg = PMGStructure(struct.lattice, sp, struct.frac_coords, to_unit_cell=True)
    return pmg



def generate_motifs_for(chem: str, grid: int = 4, a: float = 3.90,
                        out_dir: str = None, write_instances=True,
                        source: str = "local+mp", mp_docs: int = 20):
    """
    source: "local" | "mp" | "local+mp"
    """
    # 1) grid
    import numpy as np
    us = np.linspace(0,1,grid,endpoint=False)
    grid_frac = [(float(x),float(y),float(z)) for x in us for y in us for z in us]

    # 2) deterministic motifs for SrTiO3 (TiO6, SrO12)
    from .motif_extract import perovskite_TiO6_motif, perovskite_SrO12_motif
    motifs = [perovskite_TiO6_motif(), perovskite_SrO12_motif()] if chem.lower().replace(" ","") in {"srtio3"} else []

    # 3) optionally mine MP units for O–Sr–Ti, and treat as motifs too
    mined = []
    if source in {"mp","local+mp"} and chem.lower().replace(" ","") in {"srtio3"}:
        try:
            units = mine_units_from_mp(chemsys="O-Sr-Ti", n=mp_docs)
            mined = units  # keep a copy for audit

            # Convert units → motif dicts (anchor = first species in composition)
            for u in units:
                comp = u["composition"]                 # e.g., ["Ti","O","O"]
                anchor = comp[0]
                neighbors = []
                for idx, dv in enumerate(u["frac_offsets"][1:], start=1):
                    neighbors.append([comp[idx], list(dv)])

                motifs.append({
                    "name": f"MINED_{''.join(comp)}",
                    "anchor": anchor,
                    "anchor_frac": [0.0, 0.0, 0.0],     # relative template; placed at grid sites
                    "neighbors": neighbors,
                    "orientations": [[[1,0,0],[0,1,0],[0,0,1]]],
                })
        except Exception as e:
            print("[genorator] MP mining skipped:", e)

    # 4) precompute instances on grid
    instances = { m["name"]: prepare_motif_instances(m, grid_frac, grid) for m in motifs }

    # 5) write artifacts
    if out_dir:
        from pathlib import Path, PurePath
        import json
        od = Path(out_dir); od.mkdir(parents=True, exist_ok=True)
        with open(od/"motifs.json","w") as f: json.dump(motifs,f,indent=2)
        if write_instances:
            with open(od/"instances.json","w") as f:
                json.dump({k: [[i, neigh] for (i, neigh) in v] for k,v in instances.items()}, f, indent=2)
        # (optional) keep the raw mined units for audit
        if mined:
            with open(od/"mp_mined_units.json","w") as f: json.dump(mined,f,indent=2)

    return motifs, instances
