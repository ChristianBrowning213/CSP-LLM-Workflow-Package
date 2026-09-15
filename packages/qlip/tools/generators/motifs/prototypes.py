# prototypes.py
from pymatgen.core import Lattice, Structure

def proto_perovskite_ABO3(a: float, A="A", B="B", X="X"):
    lat = Lattice.cubic(a)
    species = [A, B, X, X, X]
    frac = [
        (0,0,0),           # A @ 1a
        (0.5,0.5,0.5),     # B @ 1b
        (0.5,0.5,0.0),     # X @ 3d reps
        (0.5,0.0,0.5),
        (0.0,0.5,0.5),
    ]
    return Structure(lat, species, frac, to_unit_cell=True)

def proto_spinel_AB2X4(a: float, A="A", B="B", X="X"):
    # Very small toy: just a few reps for Fd-3m (not a full expansion).
    # In practice: pull a canonical CIF or use pymatgen’s built-ins for full Wyckoff sets.
    lat = Lattice.cubic(a)
    species = [A, B, B, X, X, X, X]
    frac = [
        (0.125,0.125,0.125),       # A (8a)
        (0.5,0.5,0.5),             # B (16d) rep
        (0.0,0.5,0.5),
        (0.255,0.255,0.255),       # X (32e) reps
        (0.745,0.255,0.255),
        (0.255,0.745,0.255),
        (0.255,0.255,0.745),
    ]
    return Structure(lat, species, frac, to_unit_cell=True)
