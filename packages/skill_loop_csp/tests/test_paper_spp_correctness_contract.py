from __future__ import annotations

import math

from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.structures.prototype_scaffold import (
    _canonical_pair_key,
    _interpolate_curve,
    _score_structure_with_spp_curves,
)


def test_spp_negative_values_are_valid_lower_is_better_scores() -> None:
    curve = [(1.0, 2.0), (2.0, -1.5), (3.0, 0.0)]

    assert _interpolate_curve(curve, 2.0) == -1.5
    assert _interpolate_curve(curve, 1.5) == 0.25
    assert _interpolate_curve(curve, 2.0) < _interpolate_curve(curve, 1.0)


def test_spp_pair_canonicalisation_is_order_independent() -> None:
    assert _canonical_pair_key("Ti-N") == "N-Ti"
    assert _canonical_pair_key("N-Ti") == "N-Ti"
    assert _canonical_pair_key("pb-cs") == "Cs-Pb"


def test_spp_curve_values_can_be_checked_for_nan_inf() -> None:
    values = [0.0, -1.0, 2.0]

    assert not any(math.isnan(value) for value in values)
    assert not any(math.isinf(value) for value in values)


def test_periodic_scorer_counts_unique_off_diagonal_pairs_once() -> None:
    structure = Structure(
        Lattice.cubic(4.0),
        ["Ti", "N"],
        [[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]],
    )
    curves = {"N-Ti": [(0.0, 10.0), (2.0, -2.0), (11.0, 0.0)]}

    result = _score_structure_with_spp_curves(structure, curves)

    assert result["ok"] is True
    assert result["score"] == -2.0
    assert len(result["pair_score_breakdown"]) == 1
    assert result["pair_score_breakdown"][0]["pair"] == "N-Ti"
