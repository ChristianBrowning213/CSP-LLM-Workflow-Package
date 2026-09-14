"""Structure scoring against an in-memory SPP model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ase import Atoms

from spp_maker.fit_hist import PairKey, canonical_pair
from spp_maker.neighbors import build_neighbor_edges
from spp_maker.spp_model import SPPModel
from spp_maker.weights import BandpassParams, bandpass_weight


@dataclass(frozen=True)
class ScoreReport:
    """Aggregate scoring diagnostics for one structure."""

    total: float
    by_pair: Dict[PairKey, float]
    num_edges: int
    num_scored_edges: int
    skipped_out_of_range: int
    skipped_missing_pair: int


def score_atoms(
    atoms: Atoms,
    model: SPPModel,
    *,
    r_cut: Optional[float] = 4.0,
    k: Optional[int] = None,
    min_d: Optional[float] = None,
    bandpass: Optional[BandpassParams] = None,
    use_bandpass: bool = True,
) -> ScoreReport:
    """
    Score one structure by summing weighted SPP penalties over neighbor edges.

    Edge contribution:
      w(d) * phi_ab(d)
    where `w(d)` is optional band-pass weighting and `phi_ab` is looked up from model.
    """
    if use_bandpass:
        active_bandpass = bandpass if bandpass is not None else BandpassParams.defaults()
    else:
        active_bandpass = None

    edges = build_neighbor_edges(atoms, r_cut=r_cut, k=k, min_d=min_d)
    symbols = atoms.get_chemical_symbols()

    by_pair: Dict[PairKey, float] = {}
    total = 0.0
    num_scored_edges = 0
    skipped_out_of_range = 0
    skipped_missing_pair = 0

    for edge in edges:
        a = symbols[edge.i]
        b = symbols[edge.j]
        key = canonical_pair(a, b)

        if key not in model.phi:
            skipped_missing_pair += 1
        else:
            if model.binning is not None:
                if model.binning.bin_index(float(edge.d)) < 0:
                    skipped_out_of_range += 1
            else:
                r_vals = model.r[key]
                d_float = float(edge.d)
                if d_float < float(r_vals[0]) or d_float > float(r_vals[-1]):
                    skipped_out_of_range += 1

        penalty = model.penalty(a, b, float(edge.d))

        weight = (
            float(bandpass_weight(float(edge.d), active_bandpass))
            if active_bandpass is not None
            else 1.0
        )
        contribution = weight * penalty

        by_pair[key] = by_pair.get(key, 0.0) + contribution
        total += contribution
        num_scored_edges += 1

    return ScoreReport(
        total=total,
        by_pair=by_pair,
        num_edges=len(edges),
        num_scored_edges=num_scored_edges,
        skipped_out_of_range=skipped_out_of_range,
        skipped_missing_pair=skipped_missing_pair,
    )
