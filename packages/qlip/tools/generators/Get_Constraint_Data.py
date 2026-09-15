#!/usr/bin/env python3
"""
Get_Constraint_Data.py

Utilities to fetch and assemble the *actual data* required to build the MILP/IP
constraints and safety-oracle rules for crystal-structure allocation on a g×g×g
discrete lattice.

What this module provides (high-level):
- fetch_from_mp(): Pull lattice, space group, structure, oxidation states via the
  Materials Project API (v2), preferring MP data.
- make_discrete_grid(): Build a g×g×g fractional grid within the unit cell.
- symmetry_orbits(): Compute site orbits under the space-group operations.
- neighbor_list(): Build periodic neighbor lists and distances for grid sites.
- stoichiometry_targets(): Compute exact counts per species in a chosen supercell.
- role_map_from_oxi(): Derive cation/anion roles from oxidation states (fallbacks included).
- block_partition(): Deterministic block IDs for capacity constraints (e.g., 2×2×2).
- pair_index_table(): Precompute all unique unordered (i,j) pairs within a cutoff for
  objective/cut generation (used by Ewald/short-range tables outside this module).

This file is intentionally *data-only*: it computes the indexes, sets, maps, and numeric
arrays you need to *formulate* the constraints; it does NOT build the MILP itself.
Plug these outputs into your Pyomo/Gurobi layer.

Dependencies (install with pip as needed):
  pip install numpy scipy pymatgen mp-api
Optional:
  pip install spglib

Author: you+assistant
"""

from __future__ import annotations

import os
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable

import numpy as np

# Pymatgen ecosystem (robust to either direct mp_api or legacy MPRester via pymatgen)
# Pymatgen ecosystem (robust to either direct mp_api or legacy MPRester via pymatgen)
try:
    from mp_api.client import MPRester  # Materials Project API v2
except Exception:
    MPRester = None  # type: ignore


from pymatgen.core import Structure, Lattice, Element
from pymatgen.analysis.local_env import CrystalNN
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

# ---- Data containers ---------------------------------------------------------

@dataclass
class MPFetchResult:
    structure: Structure
    lattice: Lattice
    spacegroup_symbol: str
    spacegroup_number: int
    oxidation_states_present: bool


@dataclass
class DiscreteGrid:
    g: int
    frac: np.ndarray          # (N, 3) fractional coordinates in [0,1)
    cart: np.ndarray          # (N, 3) Cartesian coordinates
    lattice_matrix: np.ndarray  # (3,3)
    volume: float


@dataclass
class NeighborList:
    # pairs: list of (i, j, distance) with i < j (unique unordered pairs)
    pairs_ij: np.ndarray      # (M, 2) int indices
    distances: np.ndarray     # (M,) float distances (Angstrom)
    cutoff: float


@dataclass
class SymmetryOrbits:
    # orbit_id[k] gives the orbit index for site k in the grid
    orbit_id: np.ndarray      # (N,) int
    num_orbits: int


@dataclass
class StoichiometryTargets:
    # Exact counts per species *in the chosen supercell*
    counts: Dict[str, int]
    supercell_mult: int


@dataclass
class Roles:
    # 'cation' or 'anion' (or 'neutral') per species label (e.g., 'Sr', 'Ti', 'O')
    role_of_species: Dict[str, str]
    oxi_states: Dict[str, float]


# ---- MP fetching -------------------------------------------------------------
def fetch_from_mp(
    formula_or_id: str,
    mp_api_key: Optional[str] = None,
    prefer_oxidation_states: bool = True,
) -> MPFetchResult:
    """
    Fetch structure + symmetry from Materials Project (v2). Tries to preserve oxidation
    states if present; if not, will attempt an oxidation-state *guess* so that role-mapping works.
    """
    key = mp_api_key or os.getenv("MP_API_KEY")
    if MPRester is None:
        raise RuntimeError("mp_api is not installed. `pip install mp-api`")

    def has_oxi(s: Structure) -> bool:
        # Safe check that doesn't touch Element.oxi_state
        for site in s.sites:
            sp = site.specie
            ox = getattr(sp, "oxi_state", None)
            if ox is None:
                return False
        return True

    with MPRester(api_key=key) as mpr:
        # Use the non-deprecated materials summary endpoint
        if formula_or_id.lower().startswith("mp-"):
            docs = mpr.materials.summary.search(
                material_ids=[formula_or_id],
                fields=["material_id", "structure", "symmetry", "composition", "volume", "energy_above_hull"],
            )
        else:
            docs = mpr.materials.summary.search(
                formula=formula_or_id,
                fields=["material_id", "structure", "symmetry", "composition", "volume", "energy_above_hull"],
            )
            docs = sorted(docs, key=lambda d: (d.energy_above_hull or 0.0, d.volume or 1e9))

        if not docs:
            raise ValueError(f"No MP summary found for '{formula_or_id}'.")

        d0 = docs[0]
        pmg_struct: Structure = d0.structure

        # Try to ensure oxidation states if desired
        oxi_present = has_oxi(pmg_struct)
        if prefer_oxidation_states and not oxi_present:
            # 1) try a local guess (fast, good enough for roles/cuts)
            try:
                s_guess = pmg_struct.copy()
                s_guess.add_oxidation_state_by_guess(max_sites=-1)
                if has_oxi(s_guess):
                    pmg_struct = s_guess
                    oxi_present = True
            except Exception:
                pass

            # 2) (optional) try structures endpoint for an oxi-decorated variant
            if not oxi_present:
                try:
                    sdocs = mpr.materials.structures.search(material_ids=[d0.material_id])
                    for sd in sdocs:
                        s2: Structure = sd.structure
                        if has_oxi(s2):
                            pmg_struct = s2
                            oxi_present = True
                            break
                except Exception:
                    pass

        # Symmetry from the (possibly oxi-decorated) structure
        sga = SpacegroupAnalyzer(pmg_struct, symprec=1e-3, angle_tolerance=5.0)
        spg = sga.get_space_group_symbol()
        spg_num = sga.get_space_group_number()

        return MPFetchResult(
            structure=pmg_struct,
            lattice=pmg_struct.lattice,
            spacegroup_symbol=spg,
            spacegroup_number=spg_num,
            oxidation_states_present=oxi_present,
        )



# ---- Grid, neighbors, symmetry ----------------------------------------------

def make_discrete_grid(lattice: Lattice, g: int) -> DiscreteGrid:
    """
    Build a regular g×g×g grid in fractional coordinates and map to Cartesian.

    Returns:
        DiscreteGrid
    """
    # Fractional nodes at centers of voxels to avoid exact boundaries (optional)
    coords_1d = (np.arange(g) + 0.5) / g
    fx, fy, fz = np.meshgrid(coords_1d, coords_1d, coords_1d, indexing="ij")
    frac = np.stack([fx, fy, fz], axis=-1).reshape(-1, 3)  # (N, 3)

    lat_mat = np.array(lattice.matrix)  # 3x3
    cart = frac @ lat_mat  # (N,3)
    return DiscreteGrid(g=g, frac=frac, cart=cart, lattice_matrix=lat_mat, volume=lattice.volume)


def _pbc_delta(frac_i: np.ndarray, frac_j: np.ndarray) -> np.ndarray:
    """Minimum-image difference in fractional space (component-wise wrapping to [-0.5,0.5))."""
    d = frac_j - frac_i
    d -= np.round(d)  # wrap
    return d


def neighbor_list(grid: DiscreteGrid, cutoff: float) -> NeighborList:
    """
    Build unique unordered neighbor list using a cutoff in Angstrom.

    Returns:
        NeighborList with ij pairs (i<j) and distances.
    """
    lat_mat = grid.lattice_matrix
    inv_lat = np.linalg.inv(lat_mat).T  # not actually needed here, but handy

    frac = grid.frac
    N = frac.shape[0]

    # Heuristic: use a voxel neighborhood window in fractional coords sufficient to cover cutoff.
    # Convert cutoff to an upper bound in fractional L2 by using the smallest lattice vector norm.
    # Safer (but more expensive) is full O(N^2); here we tile a small neighborhood.
    # We'll use a simple grid-based neighbor search: for each site, scan nearby fractional offsets.
    # Determine how many fractional steps ±k we might need (conservative bound).
    a_norm = np.linalg.norm(lat_mat[0])
    b_norm = np.linalg.norm(lat_mat[1])
    c_norm = np.linalg.norm(lat_mat[2])
    # minimal metric to get conservative k in each lattice direction
    ks = [max(1, math.ceil(cutoff / n)) for n in (a_norm, b_norm, c_norm)]

    pairs = []
    dists = []

    # Bucket sites by integer voxel (i,j,k) to reduce scans; since grid is regular we can index directly.
    g = grid.g
    # integer indices 0..g-1 corresponding to frac centers (k+0.5)/g
    # We'll use modular arithmetic for PBC
    def idx3(n: int) -> Tuple[int, int, int]:
        i = n // (g * g)
        rem = n % (g * g)
        j = rem // g
        k = rem % g
        return i, j, k

    for n in range(N):
        i0, j0, k0 = idx3(n)
        f0 = frac[n]
        for di in range(-ks[0], ks[0] + 1):
            for dj in range(-ks[1], ks[1] + 1):
                for dk in range(-ks[2], ks[2] + 1):
                    if di == dj == dk == 0:
                        # same voxel; we will handle same-cell neighbors by m>n condition below
                        pass
                    i1 = (i0 + di) % g
                    j1 = (j0 + dj) % g
                    k1 = (k0 + dk) % g
                    m = (i1 * g + j1) * g + k1
                    if m <= n:
                        continue  # unique unordered

                    # compute PBC distance via fractional delta then to Cartesian
                    df = _pbc_delta(f0, frac[m])
                    dc = df @ lat_mat
                    dist = float(np.linalg.norm(dc))
                    if dist <= cutoff + 1e-9:
                        pairs.append((n, m))
                        dists.append(dist)

    if not pairs:
        pairs_arr = np.empty((0, 2), dtype=int)
        dists_arr = np.empty((0,), dtype=float)
    else:
        pairs_arr = np.array(pairs, dtype=int)
        dists_arr = np.array(dists, dtype=float)

    return NeighborList(pairs_ij=pairs_arr, distances=dists_arr, cutoff=cutoff)


def symmetry_orbits(lattice: Lattice, grid: DiscreteGrid) -> SymmetryOrbits:
    """
    Compute orbit IDs of grid sites under the space group symmetries estimated from the lattice.
    We construct a fake Structure with a single dummy species at all grid sites to reuse
    pymatgen's SpacegroupAnalyzer mapping in fractional space.

    Note: We infer symmetry from the *metric* via a dummy structure; for exact MP symmetry,
    pass a real MP structure to SpacegroupAnalyzer and then apply those ops to the grid.
    """
    # Build dummy structure with one site to get symmetry operations.
    # Using a simple cubic species is fine; we only need operations.
    dummy = Structure(lattice, species=["X"], coords=[[0, 0, 0]], coords_are_cartesian=False)
    sga = SpacegroupAnalyzer(dummy, symprec=1e-3, angle_tolerance=5.0)
    symops = sga.get_symmetry_operations(cartesian=False)  # list of SymmOp acting on fractional

    frac = grid.frac
    N = frac.shape[0]
    orbit_id = -np.ones(N, dtype=int)
    current_orbit = 0

    # Hash for visited using rounded fractional coords
    def fhash(v: np.ndarray) -> Tuple[int, int, int]:
        # round to avoid floating noise; 1e-6 in fractional
        return tuple(np.round(v % 1.0, 6))

    # Build map from hash -> index for quick lookup
    hash_to_index = {fhash(frac[i]): i for i in range(N)}

    for i in range(N):
        if orbit_id[i] >= 0:
            continue
        # flood-fill orbit
        stack = [i]
        orbit_id[i] = current_orbit
        while stack:
            j = stack.pop()
            fj = frac[j]
            for op in symops:
                f2 = op.operate(fj) % 1.0
                key = fhash(f2)
                k = hash_to_index.get(key, None)
                if k is not None and orbit_id[k] < 0:
                    orbit_id[k] = current_orbit
                    stack.append(k)
        current_orbit += 1

    return SymmetryOrbits(orbit_id=orbit_id, num_orbits=current_orbit)


# ---- Stoichiometry and roles -------------------------------------------------

def stoichiometry_targets(
    composition: Dict[str, float],
    supercell_mult: int = 1
) -> StoichiometryTargets:
    """
    Compute integer counts per species in the chosen supercell.
    `composition` is a plain element->amount dict (e.g., {"Sr":1,"Ti":1,"O":3}).

    Args:
        composition: fractional amounts per formula unit.
        supercell_mult: how many formula units you intend to place overall.

    Returns:
        StoichiometryTargets with exact integer counts per species.
    """
    counts = {el: int(round(q * supercell_mult)) for el, q in composition.items()}
    # Sanity: ensure no zeros that should be positive
    for el, q in composition.items():
        if q > 0 and counts[el] == 0:
            counts[el] = 1  # minimal presence if rounding would drop (rare; adjust policy as needed)
    return StoichiometryTargets(counts=counts, supercell_mult=supercell_mult)


def role_map_from_oxi(
    structure: Structure,
    default_neutral: bool = False
) -> Roles:
    """
    Derive cation/anion roles from oxidation states if present; otherwise apply a heuristic:
    - positive -> 'cation'
    - negative -> 'anion'
    - zero/unknown -> 'neutral' (or force cation for metals & anion for typical anions via periodic table)

    Returns:
        Roles(role_of_species, oxi_states)
    """
    per_el_vals: Dict[str, List[float]] = {}
    for site in structure.sites:
        sp = site.specie
        el = sp.symbol
        ox = getattr(sp, "oxi_state", None)
        if ox is None:
            continue
        per_el_vals.setdefault(el, []).append(float(ox))

    oxi_states: Dict[str, float] = {}
    for el, vals in per_el_vals.items():
        oxi_states[el] = float(np.median(vals))  # robust

    role_of_species: Dict[str, str] = {}
    all_elements = {sp.specie.symbol for sp in structure.sites}

    # Assign by sign when available
    for el in all_elements:
        ox = oxi_states.get(el, None)
        if ox is None:
            if default_neutral:
                role_of_species[el] = "neutral"
            else:
                # Crude heuristic: oxygen, halogens -> anion; alkali/alkaline/metal -> cation
                try:
                    e = Element(el)
                    if e.is_halogen or el in {"O", "S", "Se", "Te"}:
                        role_of_species[el] = "anion"
                    elif e.is_alkali or e.is_alkaline or e.is_transition_metal or e.is_post_transition_metal:
                        role_of_species[el] = "cation"
                    else:
                        role_of_species[el] = "neutral"
                except Exception:
                    role_of_species[el] = "neutral"
        else:
            role_of_species[el] = "cation" if ox > 0 else ("anion" if ox < 0 else "neutral")

    return Roles(role_of_species=role_of_species, oxi_states=oxi_states)


# ---- Blocks & pairs ----------------------------------------------------------

def block_partition(grid: DiscreteGrid, block_size: int) -> np.ndarray:
    """
    Assign each grid site to an integer block ID for capacity constraints.
    Blocks are (block_size)^3 cubes in index space.

    Returns:
        block_id: (N,) int array of block identifiers in [0, num_blocks).
    """
    g = grid.g
    N = g * g * g

    # index to (i,j,k)
    def idx3(n: int) -> Tuple[int, int, int]:
        i = n // (g * g)
        rem = n % (g * g)
        j = rem // g
        k = rem % g
        return i, j, k

    bi = []
    for n in range(N):
        i,j,k = idx3(n)
        bi.append((i // block_size, j // block_size, k // block_size))
    bi = np.array(bi, dtype=int)

    # convert triplets to unique IDs
    # number of blocks per axis
    B = math.ceil(g / block_size)
    block_id = (bi[:,0] * B + bi[:,1]) * B + bi[:,2]
    return block_id


def pair_index_table(neigh: NeighborList) -> np.ndarray:
    """
    Return the (i,j) integer pairs for all neighbors within cutoff (i<j), to be used by
    objective table assembly (Ewald/short-range) or distance-based forbids.
    """
    return neigh.pairs_ij.copy()


# ---- Orchestration helper ----------------------------------------------------

@dataclass
class ConstraintData:
    mp: MPFetchResult
    grid: DiscreteGrid
    orbits: SymmetryOrbits
    neighbors: NeighborList
    roles: Roles
    stoich: StoichiometryTargets
    block_id: np.ndarray  # (N,)


def build_constraint_data(
    formula_or_id: str,
    g: int,
    neighbor_cutoff: float,
    supercell_mult: int = 1,
    block_size: int = 2,
    mp_api_key: Optional[str] = None,
) -> ConstraintData:
    """
    One-shot convenience to fetch MP, build grid + orbits + neighbors + roles + stoich + blocks.

    Args:
        formula_or_id: "SrTiO3" or "mp-XXXX".
        g: grid resolution per axis.
        neighbor_cutoff: Angstrom cutoff for neighbor graph.
        supercell_mult: formula-unit multiplier for stoichiometry.
        block_size: block edge length in grid cells.
        mp_api_key: MP API key (falls back to env).

    Returns:
        ConstraintData
    """
    mp = fetch_from_mp(formula_or_id, mp_api_key=mp_api_key)
    grid = make_discrete_grid(mp.lattice, g=g)
    orbits = symmetry_orbits(mp.lattice, grid)
    neighbors = neighbor_list(grid, cutoff=neighbor_cutoff)

    # Composition as dict from the fetched structure's composition
    comp = {el: float(amt) for el, amt in mp.structure.composition.get_el_amt_dict().items()}

    # Renormalize to per-formula-unit (divide by smallest positive amount)
    min_pos = min([v for v in comp.values() if v > 0])
    comp_norm = {k: v / min_pos for k, v in comp.items()}
    stoich = stoichiometry_targets(comp_norm, supercell_mult=supercell_mult)

    roles = role_map_from_oxi(mp.structure, default_neutral=False)
    block_id = block_partition(grid, block_size=block_size)

    return ConstraintData(
        mp=mp,
        grid=grid,
        orbits=orbits,
        neighbors=neighbors,
        roles=roles,
        stoich=stoich,
        block_id=block_id,
    )


# ---- CLI for quick testing ---------------------------------------------------

def _print_summary(cd: ConstraintData) -> None:
    print("── ConstraintData summary ──")
    print(f"MP Space group: {cd.mp.spacegroup_symbol} (#{cd.mp.spacegroup_number})")
    print(f"Lattice (Å):\n{np.array(cd.mp.lattice.matrix)}")
    print(f"Grid g: {cd.grid.g}, N sites: {cd.grid.frac.shape[0]}")
    print(f"Volume: {cd.grid.volume:.3f} Å^3")
    print(f"Neighbor cutoff: {cd.neighbors.cutoff} Å, pairs: {cd.neighbors.pairs_ij.shape[0]}")
    print(f"Symmetry orbits: {cd.orbits.num_orbits}")
    print(f"Stoichiometry (supercell_mult={cd.stoich.supercell_mult}): {cd.stoich.counts}")
    print(f"Roles: {cd.roles.role_of_species}")
    print(f"Blocks: unique={len(np.unique(cd.block_id))}, example IDs: {np.unique(cd.block_id)[:8]}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Assemble constraint data from MP for MILP CSP.")
    p.add_argument("--chem", required=True, help="Formula or MP material id, e.g., 'SrTiO3' or 'mp-390'")
    p.add_argument("--g", type=int, default=6, help="Grid resolution per axis (default: 6)")
    p.add_argument("--cutoff", type=float, default=3.0, help="Neighbor cutoff in Å (default: 3.0)")
    p.add_argument("--supercell", type=int, default=1, help="Formula-unit multiplier (default: 1)")
    p.add_argument("--block", type=int, default=2, help="Block size in grid cells (default: 2)")
    p.add_argument("--mp-key", default=None, help="Materials Project API key (else read MP_API_KEY env var)")
    args = p.parse_args()

    cd = build_constraint_data(
        formula_or_id=args.chem,
        g=args.g,
        neighbor_cutoff=args.cutoff,
        supercell_mult=args.supercell,
        block_size=args.block,
        mp_api_key=args.mp_key,
    )
    _print_summary(cd)
