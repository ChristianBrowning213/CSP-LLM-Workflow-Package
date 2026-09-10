from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, List, Tuple, Iterable

import numpy as np
from ase import Atoms
from ase.io import write


# headless-safe MPL
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
except Exception:
    plt = None

# optional (for polyhedra faces)
try:
    from scipy.spatial import ConvexHull
except Exception:
    ConvexHull = None

# ----------------------------- Radii & Colors -------------------------------
# Shannon-like ionic radii map (Å). The manuscript uses Shannon radii; keep consistent.
# (O2-, Ti4+, Sr2+, plus a few common cations you might add later)
SHANNON = {
    "O": 1.35, "O2-": 1.35,
    "Ti": 0.42, "Ti4+": 0.42,
    "Sr": 1.18, "Sr2+": 1.18,
    # add others here if needed
}

COLORS = {
    "O":  "#e41a1c",  # red
    "Sr": "#4daf4a",  # green
    "Ti": "#377eb8",  # blue
}

MARKERS = {"O": "o", "Sr": "s", "Ti": "^"}

# ----------------------------- Model extraction -----------------------------

def _find_assignment_var(model):
    """Locate a 2D (site,species) or (species,site) Var with binary-ish bounds."""
    try:
        v = getattr(model, "x", None)
        if v is not None:
            return v
    except Exception:
        pass
    try:
        from pyomo.core import Var
        candidates = []
        for var in model.component_objects(Var, active=True):
            try:
                idx0 = next(iter(var.index_set()))
            except StopIteration:
                continue
            if not isinstance(idx0, tuple) or len(idx0) != 2:
                continue
            # crude binary check
            v0 = var[idx0]
            lb, ub = v0.lb, v0.ub
            if (lb is not None and lb >= 0) and (ub is not None and ub <= 1):
                candidates.append(var)
        # prefer name 'x'
        for var in candidates:
            if var.name.lower() == "x" or var.name.lower().endswith(".x"):
                return var
        return candidates[0] if candidates else None
    except Exception:
        return None


def _extract_placements(task) -> Dict[str, List[Tuple[float, float, float]]]:
    """
    Return fractional placements by species: {"O":[(fx,fy,fz),...], "Sr":[...], "Ti":[...]}
    Robust to (i,t) or (t,i) indexing.
    """
    from pyomo.environ import value

    m = task.m
    atoms: Atoms = task.positions
    frac = atoms.get_scaled_positions()  # (N,3)
    N = len(frac)

    def _as_site_idx(x):
        try:
            k = int(x)
            if 0 <= k < N:
                return k
        except Exception:
            pass
        return None

    xvar = _find_assignment_var(m)
    if xvar is None:
        raise RuntimeError("Could not find placement Var (expected 2D binary var like m.x).")

    # discover species labels
    species = set()
    for idx in xvar.index_set():
        if not isinstance(idx, tuple) or len(idx) != 2:
            continue
        a, b = idx
        ia, ib = _as_site_idx(a), _as_site_idx(b)
        if ia is not None and ib is None:
            species.add(str(b))
        elif ib is not None and ia is None:
            species.add(str(a))
        else:
            if isinstance(a, str): species.add(a)
            if isinstance(b, str): species.add(b)

    placements: Dict[str, List[Tuple[float, float, float]]] = {s: [] for s in sorted(species)}
    for idx in xvar.index_set():
        if not isinstance(idx, tuple) or len(idx) != 2:
            continue
        a, b = idx
        ia, ib = _as_site_idx(a), _as_site_idx(b)
        if ia is not None and ib is None:
            site = ia; sp = str(b)
        elif ib is not None and ia is None:
            site = ib; sp = str(a)
        else:
            if isinstance(a, str) and _as_site_idx(b) is not None:
                sp = a; site = int(b)
            elif isinstance(b, str) and _as_site_idx(a) is not None:
                sp = b; site = int(a)
            else:
                continue
        try:
            if value(xvar[idx]) > 0.5:
                fx, fy, fz = map(float, frac[site])
                placements.setdefault(sp, []).append((fx, fy, fz))
        except KeyError:
            continue

    return placements


def _placements_to_atoms(placements: Dict[str, List[Tuple[float, float, float]]],
                         cell: Tuple[float, float, float]) -> Atoms:
    symbols, scaled = [], []
    for el, pts in placements.items():
        for fx, fy, fz in pts:
            symbols.append(el)
            scaled.append((float(fx), float(fy), float(fz)))
    a = Atoms(symbols=symbols, cell=list(cell), pbc=True)
    if scaled:
        a.set_scaled_positions(np.asarray(scaled, dtype=float))
    return a


# ----------------------------- I/O helpers ----------------------------------

def save_cif(task, path: str = "viz/structure.cif") -> str:
    placements = _extract_placements(task)
    A, B, C = task.positions.cell.lengths()
    atoms = _placements_to_atoms(placements, (A, B, C))
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    write(str(out), atoms)
    return str(out.resolve())


def save_poscar(task, path: str = "viz/POSCAR") -> str:
    placements = _extract_placements(task)
    A, B, C = task.positions.cell.lengths()
    atoms = _placements_to_atoms(placements, (A, B, C))
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    write(str(out), atoms, format="vasp")
    return str(out.resolve())


# ----------------------------- Rendering ------------------------------------

def _species_key(el: str) -> str:
    # normalize for lookup (strip charge)
    if el in SHANNON: return el
    base = ''.join([c for c in el if c.isalpha()])
    return base if base in SHANNON else el

def _r_ionic(el: str, fallback: float = 1.0) -> float:
    return SHANNON.get(_species_key(el), fallback)

def _color_for(el: str) -> str:
    return COLORS.get(_species_key(el), "#444444")

def _marker_for(el: str) -> str:
    return MARKERS.get(_species_key(el), "o")

def _supercell_cart(atoms: Atoms, reps=(1,1,1)) -> Tuple[np.ndarray, List[str], np.ndarray]:
    """Return (cart_coords, symbols, cell_vectors) for a*reps supercell."""
    rep_atoms = atoms.repeat(reps)
    pos = rep_atoms.get_positions()
    syms = rep_atoms.get_chemical_symbols()
    cell = rep_atoms.cell.array  # 3x3
    return pos, syms, cell

def _bond_edges(cart: np.ndarray,
                syms: List[str],
                tol: float = 0.15,
                allowed: set | None = None) -> List[Tuple[int,int]]:
    """
    Bonds by ionic radii: d_ij <= (r_i + r_j)*(1+tol).
    If `allowed` is given, only keep pairs whose (A,B) or (B,A) is in that set,
    where A,B are species keys like 'Ti','O','Sr'.
    """
    N = len(syms)
    rad = np.array([_r_ionic(s, 1.0) for s in syms], dtype=float)
    edges: List[Tuple[int,int]] = []
    for i in range(N):
        si = _species_key(syms[i])
        for j in range(i+1, N):
            sj = _species_key(syms[j])
            if allowed and ((si, sj) not in allowed and (sj, si) not in allowed):
                continue
            rij = np.linalg.norm(cart[j] - cart[i])
            if rij <= (rad[i] + rad[j]) * (1.0 + tol):
                edges.append((i, j))
    return edges

def _draw_cell(ax, cell: np.ndarray):
    # draw the unit cell box given 3x3 cell vectors
    a, b, c = cell
    O = np.array([0,0,0])
    verts = [
        O, a, a+b, b, O, O+c, a+c, a+b+c, b+c, O+c
    ]
    verts = np.array(verts)
    ax.plot(verts[:4,0], verts[:4,1], verts[:4,2], lw=1.0)
    ax.plot(verts[5:9,0], verts[5:9,1], verts[5:9,2], lw=1.0)
    for k in range(4):
        ax.plot([verts[k,0], verts[k+5,0]],
                [verts[k,1], verts[k+5,1]],
                [verts[k,2], verts[k+5,2]], lw=1.0)

def _polyhedra_faces(center: np.ndarray, shell: np.ndarray) -> List[np.ndarray]:
    """
    Build faces for a coordination polyhedron around center using ConvexHull of shell.
    Returns list of (3D polygon) arrays suitable for Poly3DCollection.
    """
    if ConvexHull is None or len(shell) < 4:
        return []
    # shift shell to center, hull on shell positions
    rel = shell - center
    hull = ConvexHull(rel)
    faces = []
    for tri in hull.simplices:
        faces.append(shell[tri])
    return faces

def render_crystal_png(task,
                       path: str = "viz/structure.png",
                       style: str = "polyhedra",
                       supercell: Tuple[int,int,int] = (2,2,2),
                       bond_tol: float = 0.15,
                       poly_central: Iterable[str] = ("Ti",),
                       sphere_scale: float = 0.35,
                       dpi: int = 220,
                       figsize: Tuple[float,float] = (6.5,6.5)) -> str:
    """
    Make a chemistry-grade PNG:
      - 'ball_and_stick': spheres (scaled by ionic radii) + bonds
      - 'polyhedra'    : coordination polyhedra for selected central species + bonds + atoms
    Bonds built from Shannon radii (paper uses Shannon radii; see Methods).  # manuscript basis
    """
    if plt is None:
        raise RuntimeError("matplotlib is not available; `pip install matplotlib`")

    placements = _extract_placements(task)
    A, B, C = task.positions.cell.lengths()
    atoms = _placements_to_atoms(placements, (A,B,C))

    cart, syms, cell = _supercell_cart(atoms, reps=supercell)
    edges = _bond_edges(cart, syms, tol=bond_tol)

    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax = fig.add_subplot(111, projection="3d")

    # cell: draw the primitive box of the original cell, repeated visually at origin
    _draw_cell(ax, atoms.cell.array)

    # bonds (thin cylinders approximated by lines)
    for i, j in edges:
        xi, xj = cart[i], cart[j]
        ax.plot([xi[0], xj[0]], [xi[1], xj[1]], [xi[2], xj[2]], lw=0.8, color="#666666")

    # optional polyhedra for selected centres (e.g., TiO6)
    if style.lower() == "polyhedra":
        centers = {k for k in poly_central}
        # For each central atom (e.g., Ti), take neighbors within bond cutoff (usually O)
        for idx, sym in enumerate(syms):
            base = _species_key(sym)
            if base not in centers:  # e.g., only Ti
                continue
            neigh = [j for (u,v) in edges for j in ([v] if u==idx else ([u] if v==idx else []))]
            shell = cart[neigh] if neigh else np.zeros((0,3))
            faces = _polyhedra_faces(cart[idx], shell)
            if faces:
                poly = Poly3DCollection(faces, facecolor=_color_for(sym), alpha=0.25, edgecolor="none")
                ax.add_collection3d(poly)

    # atoms (spheres approximated by scatter with radius scaling)
    # scale radii to point size roughly ~ (Å)*scale factor
    sizes = []
    for s in syms:
        r = _r_ionic(s, 1.0)
        sizes.append(max(10.0, (r / 1.0) * (120.0 * sphere_scale)))
    sizes = np.array(sizes)

    # scatter per species for consistent colors/markers
    species_order = []
    for s in syms:
        k = _species_key(s)
        if k not in species_order:
            species_order.append(k)

    for sp in species_order:
        mask = [(_species_key(s) == sp) for s in syms]
        pts = cart[mask]
        if pts.size == 0: continue
        mk = _marker_for(sp)
        ax.scatter(pts[:,0], pts[:,1], pts[:,2],
                   s=sizes[mask], marker=mk, label=sp, depthshade=True,
                   color=_color_for(sp), edgecolors="k", linewidths=0.2)

    # axes & legend
    ax.set_xlabel("x (Å)"); ax.set_ylabel("y (Å)"); ax.set_zlabel("z (Å)")
    # Set balanced limits to fit supercell content
    mins = cart.min(axis=0); maxs = cart.max(axis=0)
    ax.set_xlim(mins[0], maxs[0]); ax.set_ylim(mins[1], maxs[1]); ax.set_zlim(mins[2], maxs[2])
    ax.set_box_aspect((maxs - mins))
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(str(out), bbox_inches="tight")
    plt.close(fig)
    return str(out.resolve())

# Backwards-compatible simple wrapper
def save_png(task, path: str = "viz/structure.png") -> str:
    return render_crystal_png(task, path=path, style="polyhedra", supercell=(2,2,2))
