from __future__ import annotations

import importlib.util
import math
import sys
import tempfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_li2feo3_cell_representability.py"
SPEC = importlib.util.spec_from_file_location("li2feo3_cell_diagnostic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def test_normalized_lattice_ratios_are_sorted_and_unit_product() -> None:
    ratios = diagnostic.normalized_lattice_ratios((12.0, 3.0, 6.0))
    assert ratios == tuple(sorted(ratios))
    assert math.prod(ratios) == pytest.approx(1.0)


def test_median_shape_is_unit_product_with_longest_assigned_to_c() -> None:
    shape = diagnostic.aggregate_median_shape(
        [(0.5, 1.0, 2.0), (0.6, 1.0, 1.8), (0.4, 1.1, 2.1)]
    )
    assert shape == tuple(sorted(shape))
    assert math.prod(shape) == pytest.approx(1.0)
    assert shape[2] == max(shape)


def test_constant_volume_scaling_is_exact() -> None:
    lengths = diagnostic.scale_shape_to_volume((0.5, 1.0, 2.0), 125.0)
    assert math.prod(lengths) == pytest.approx(125.0)
    assert lengths[2] / lengths[0] == pytest.approx(4.0)


def test_uniform_feasibility_expansion_preserves_ratios() -> None:
    initial = (2.0, 3.0, 5.0)

    def checker(lengths):
        feasible = lengths[0] >= 2.5
        return {"status": "FEASIBLE" if feasible else "INFEASIBLE", "feasible": feasible}

    final, trace = diagnostic.expand_anisotropic_to_feasible(initial, checker)
    assert trace["expansion_required"] is True
    assert final[1] / final[0] == pytest.approx(initial[1] / initial[0])
    assert final[2] / final[0] == pytest.approx(initial[2] / initial[0])
    assert final[0] >= 2.5


def test_invariant_audit_detects_accidental_scientific_change() -> None:
    common = {
        "request": diagnostic.REQUEST, "formula": diagnostic.FORMULA,
        "retrieval_bundle_hashes": {"x": "1"}, "spp_pot_hashes": {"p": "2"},
        "pair_manifest": ["Li-O"], "solver": {"threads": 1},
        "proximity": {"scale": 1.0}, "grid": {"dimensions": [4, 4, 4]},
    }
    variants = {
        "A": {"invariants": common, "lattice_geometry": {"a": 3.9}},
        "B": {"invariants": common | {"solver": {"threads": 2}}, "lattice_geometry": {"a": 4.7}},
    }
    with pytest.raises(RuntimeError, match="scientific invariant audit failed"):
        diagnostic.audit_variant_invariants(variants)


def test_diagnostic_refuses_output_inside_or_over_source_row() -> None:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "frozen" / "layered_007"
        source.mkdir(parents=True)
        with pytest.raises(ValueError, match="must not be inside"):
            diagnostic.assert_fresh_output_root(source / "diagnostic", source)
        with pytest.raises(ValueError, match="must not be inside"):
            diagnostic.assert_fresh_output_root(source.parent, source)


def test_diagnostic_refuses_to_overwrite_existing_output() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        output = root / "output"
        source.mkdir()
        output.mkdir()
        with pytest.raises(FileExistsError, match="refusing to overwrite"):
            diagnostic.assert_fresh_output_root(output, source)
