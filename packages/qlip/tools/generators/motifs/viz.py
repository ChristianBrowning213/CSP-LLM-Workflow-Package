# /tools/generators/motifs/viz.py
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import matplotlib.pyplot as plt
from pymatgen.core import Lattice, Structure

# ---------- utilities

def _species_colors():
    # simple, deterministic colors
    return {
        "Sr": "tab:blue",
        "Ti": "tab:orange",
        "O":  "tab:green",
        # fallback
        "_":  "tab:gray",
    }

def _as_array(x):
    return np.array(x, dtype=float)

def _wrap01(frac):
    f = _as_array(frac)
    return (f % 1.0)

def _index_to_frac(idx: int, g: int) -> np.ndarray:
    # consistent with uniform(g) ordering: x major, then y, then z
    x = idx // (g*g)
    y = (idx // g) % g
    z = idx % g
    return np.array([x, y, z], float) / g

def _ensure_dir(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)

# ---------- build small structures for VESTA/ASE

def motif_template_to_structure(motif: Dict, a: float = 3.9) -> Structure:
    """
    Build a single-cell structure with the motif at the center.
    Anchor at [0.5, 0.5, 0.5]; neighbors by fractional offsets.
    """
    lat = Lattice.cubic(a)
    species = [motif["anchor"]]
    coords  = [np.array([0.5, 0.5, 0.5])]
    for sp, dv in motif["neighbors"]:
        dv = np.array(dv, float)
        pt = (coords[0] + dv) % 1.0
        species.append(sp)
        coords.append(pt)
    return Structure(lat, species, coords, to_unit_cell=True)

def save_motif_cif(motif: Dict, out_path: str = "viz/motif.cif", a: float = 3.9):
    _ensure_dir(Path(out_path))
    struct = motif_template_to_structure(motif, a=a)
    Path(out_path).write_text(struct.to(fmt="cif"))
    return out_path

def save_motif_poscar(motif: Dict, out_path: str = "viz/POSCAR.motif", a: float = 3.9):
    _ensure_dir(Path(out_path))
    struct = motif_template_to_structure(motif, a=a)
    Path(out_path).write_text(struct.to(fmt="poscar"))
    return out_path

# ---------- quick 3D plots

def plot_motif_template(motif: Dict, out_png: str = "viz/motif_template.png", a: float = 3.9):
    _ensure_dir(Path(out_png))
    colors = _species_colors()

    anchor = np.array([0.5,0.5,0.5])
    neighs = [(sp, (anchor + np.array(dv, float)) % 1.0) for sp, dv in motif["neighbors"]]

    fig = plt.figure(figsize=(5.5,5.5))
    ax = fig.add_subplot(111, projection="3d")

    # draw cube
    for s in [0,1]:
        for ax_ix in range(3):
            for t in np.linspace(0,1,2):
                p0 = np.array([0,0,0], float); p1 = np.array([0,0,0], float)
                p0[ax_ix] = s; p1[ax_ix] = s
                p0[(ax_ix+1)%3] = 0; p1[(ax_ix+1)%3] = 1
                p0[(ax_ix+2)%3] = t; p1[(ax_ix+2)%3] = t
                ax.plot([p0[0],p1[0]], [p0[1],p1[1]], [p0[2],p1[2]], lw=0.6, color="#999999")

    # plot anchor
    ax.scatter([anchor[0]],[anchor[1]],[anchor[2]], s=80,
               color=colors.get(motif["anchor"], colors["_"]), label=motif["anchor"])

    # plot neighbors
    for sp, p in neighs:
        ax.scatter([p[0]],[p[1]],[p[2]], s=50, color=colors.get(sp, colors["_"]))
        # edge to anchor (shortest wrapped vector)
        dv = (p - anchor + 0.5) % 1.0 - 0.5
        seg = np.stack([anchor, anchor + dv], axis=0)
        ax.plot(seg[:,0], seg[:,1], seg[:,2], lw=1.0, color="#666666")

    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_zlim(0,1)
    ax.set_xlabel("a"); ax.set_ylabel("b"); ax.set_zlabel("c")
    ax.set_title(motif["name"])
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close(fig)
    return out_png

def plot_motif_instance(motif: Dict, instance: Tuple[int, List[Tuple[str,int]]],
                        g: int, out_png: str = "viz/motif_instance.png"):
    """
    instance = (anchor_site_idx, [(species, neighbor_site_idx), ...])
    Plots on the unit cube with grid sites shown faintly.
    """
    _ensure_dir(Path(out_png))
    colors = _species_colors()

    i_anchor, neighs = instance
    anchor = _index_to_frac(i_anchor, g)
    pts = [(motif["anchor"], anchor)]
    for sp, j in neighs:
        pts.append((sp, _index_to_frac(j, g)))

    fig = plt.figure(figsize=(5.5,5.5))
    ax = fig.add_subplot(111, projection="3d")

    # grid sites (faint)
    us = np.linspace(0, 1, g, endpoint=False)
    gx, gy, gz = np.meshgrid(us, us, us, indexing="ij")
    ax.scatter(gx.flatten(), gy.flatten(), gz.flatten(), s=5, alpha=0.15, color="#aaaaaa")

    # draw cube edges
    for s in [0,1]:
        for ax_ix in range(3):
            for t in np.linspace(0,1,2):
                p0 = np.array([0,0,0], float); p1 = np.array([0,0,0], float)
                p0[ax_ix] = s; p1[ax_ix] = s
                p0[(ax_ix+1)%3] = 0; p1[(ax_ix+1)%3] = 1
                p0[(ax_ix+2)%3] = t; p1[(ax_ix+2)%3] = t
                ax.plot([p0[0],p1[0]], [p0[1],p1[1]], [p0[2],p1[2]], lw=0.6, color="#999999")

    # plot points
    for k,(sp,p) in enumerate(pts):
        size = 80 if k==0 else 50
        ax.scatter([p[0]],[p[1]],[p[2]], s=size, color=colors.get(sp, colors["_"]))
        # anchor links
        if k>0:
            dv = (p - anchor + 0.5) % 1.0 - 0.5
            seg = np.stack([anchor, anchor + dv], axis=0)
            ax.plot(seg[:,0], seg[:,1], seg[:,2], lw=1.0, color="#666666")

    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_zlim(0,1)
    ax.set_xlabel("a"); ax.set_ylabel("b"); ax.set_zlabel("c")
    ax.set_title(f"{motif['name']} @ grid g={g}")
    plt.tight_layout()
    plt.savefig(out_png, dpi=160)
    plt.close(fig)
    return out_png

# ---------- CLI

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Visualize motif templates and snapped instances.")
    ap.add_argument("--motifs", required=True, help="Path to motifs.json")
    ap.add_argument("--instances", help="Path to instances.json")
    ap.add_argument("--name", required=True, help="Motif name to visualize (e.g., TiO6)")
    ap.add_argument("--grid", type=int, default=4, help="Grid size g (for instance plotting)")
    ap.add_argument("--a", type=float, default=3.9, help="Cubic lattice parameter for CIF/POSCAR")
    ap.add_argument("--out_dir", default="viz", help="Output dir for PNG/CIF/POSCAR")
    args = ap.parse_args()

    motifs = {m["name"]: m for m in json.loads(Path(args.motifs).read_text())}
    if args.name not in motifs:
        raise SystemExit(f"Motif '{args.name}' not found. Available: {list(motifs.keys())[:8]}...")

    motif = motifs[args.name]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # template renders
    png_tpl = plot_motif_template(motif, out_png=str(out_dir / f"{args.name}_template.png"), a=args.a)
    cif_tpl = save_motif_cif(motif, out_path=str(out_dir / f"{args.name}.cif"), a=args.a)
    pos_tpl = save_motif_poscar(motif, out_path=str(out_dir / f"POSCAR_{args.name}"), a=args.a)
    print("[viz] wrote:", png_tpl, "|", cif_tpl, "|", pos_tpl)

    # instance renders (if instances provided)
    if args.instances:
        inst_map = json.loads(Path(args.instances).read_text())
        insts = inst_map.get(args.name, [])
        if insts:
            # pick the first placement to preview
            anchor_idx, neighs = insts[0][0], insts[0][1]
            png_inst = plot_motif_instance(motif, (anchor_idx, neighs), g=args.grid,
                                           out_png=str(out_dir / f"{args.name}_instance.png"))
            print("[viz] wrote:", png_inst)
        else:
            print(f"[viz] no instances for motif '{args.name}' in {args.instances}")

if __name__ == "__main__":
    main()
