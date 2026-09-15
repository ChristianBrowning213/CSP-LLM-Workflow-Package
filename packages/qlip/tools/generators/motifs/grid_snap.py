# grid_snap.py
import numpy as np

def snap_frac_to_grid(u, g, tol=1e-6):
    idx = np.round((np.array(u)%1.0)*g).astype(int) % g
    snapped = idx / g
    err = np.linalg.norm((((snapped - u)+0.5)%1.0)-0.5)
    return (tuple(idx.tolist()), True) if err <= (0.5/g + tol) else (None, False)

def prepare_motif_instances(motif, grid_frac, g):
    # grid_frac: list of site fractional coords (uniform(g))
    inst = []
    # Optional: shift anchor_frac to the nearest grid site index; or assume anchor sits on a grid center
    for i, ui in enumerate(grid_frac):
        ok = True; js=[]
        for (s, dv) in motif["neighbors"]:
            uj = (np.array(ui) + np.array(dv)) % 1.0
            idx, ok_snap = snap_frac_to_grid(uj, g)
            if not ok_snap: ok=False; break
            j = idx[0]*g*g + idx[1]*g + idx[2]
            js.append((s, j))
        if ok:
            inst.append((i, js))   # (anchor_site, [(species, neighbor_site), ...])
    return inst
