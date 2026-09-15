from __future__ import annotations

import pytest

from sok_llm_orchestrator.workflow.cell_strategy import (
    GLOBAL_VPA_A3_PER_ATOM,
    NATIVE_CELL_A,
    NATIVE_GRID_DENSITY,
    n_target_atoms,
    resolve_native_cell,
)


def test_native_mode_matches_frozen_production_defaults() -> None:
    cell = resolve_native_cell("Na3Zr2Si2PO12", cell_mode="native")
    assert cell.a == cell.b == cell.c == NATIVE_CELL_A == 3.9
    assert (cell.alpha, cell.beta, cell.gamma) == (90.0, 90.0, 90.0)
    assert cell.grid_density == NATIVE_GRID_DENSITY == 8
    assert cell.vpa_value is None
    assert cell.cell_volume_A3 == pytest.approx(3.9 ** 3)


def test_native_mode_rejects_explicit_vpa_override() -> None:
    with pytest.raises(ValueError, match="native"):
        resolve_native_cell("Na3Zr2Si2PO12", cell_mode="native", cell_volume_per_atom=20.0)


def test_composition_scaled_uses_frozen_global_vpa_constant() -> None:
    cell = resolve_native_cell("Na3Zr2Si2PO12", cell_mode="composition_scaled")
    atoms = n_target_atoms("Na3Zr2Si2PO12")
    assert atoms == 20
    expected_volume = atoms * GLOBAL_VPA_A3_PER_ATOM
    assert cell.cell_volume_A3 == pytest.approx(expected_volume)
    assert cell.a == cell.b == cell.c == pytest.approx(expected_volume ** (1.0 / 3.0))
    assert cell.vpa_source == "global_vpa_frozen_constant"
    assert cell.vpa_value == pytest.approx(GLOBAL_VPA_A3_PER_ATOM)
    assert cell.grid_density == NATIVE_GRID_DENSITY
    assert cell.grid_spacing_A == pytest.approx(cell.a / NATIVE_GRID_DENSITY)


def test_composition_scaled_atom_count_uses_unscaled_target_formula() -> None:
    # LiZr2(PO4)3 has 18 atoms in its literal (unscaled) formula; the
    # native/no-scaffold QLIP request always sends this literal formula,
    # never a site-count-scaled one (see cell_strategy module docstring).
    cell = resolve_native_cell("LiZr2(PO4)3", cell_mode="composition_scaled")
    assert cell.n_target_atoms == 18
    assert cell.cell_volume_A3 == pytest.approx(18 * GLOBAL_VPA_A3_PER_ATOM)


def test_composition_scaled_explicit_override_replaces_global_constant() -> None:
    cell = resolve_native_cell("Na3Zr2Si2PO12", cell_mode="composition_scaled", cell_volume_per_atom=10.0)
    assert cell.vpa_source == "explicit_override"
    assert cell.vpa_value == pytest.approx(10.0)
    assert cell.cell_volume_A3 == pytest.approx(20 * 10.0)


def test_retrieval_derived_uses_median_of_evidence_vpa_records() -> None:
    records = (
        {"structure_id": "a", "vpa_A3_per_atom": 10.0},
        {"structure_id": "b", "vpa_A3_per_atom": 20.0},
        {"structure_id": "c", "vpa_A3_per_atom": 30.0},
    )
    cell = resolve_native_cell("Na3Zr2Si2PO12", cell_mode="retrieval_derived", evidence_vpa_records=records)
    assert cell.vpa_source == "retrieval_evidence_median"
    assert cell.vpa_value == pytest.approx(20.0)
    assert cell.cell_volume_A3 == pytest.approx(20 * 20.0)
    assert cell.provenance["evidence_structure_count"] == 3


def test_retrieval_derived_requires_at_least_one_evidence_record() -> None:
    with pytest.raises(ValueError, match="evidence"):
        resolve_native_cell("Na3Zr2Si2PO12", cell_mode="retrieval_derived", evidence_vpa_records=())


def test_retrieval_derived_rejects_explicit_vpa_override() -> None:
    with pytest.raises(ValueError, match="retrieval_derived"):
        resolve_native_cell(
            "Na3Zr2Si2PO12", cell_mode="retrieval_derived",
            cell_volume_per_atom=10.0, evidence_vpa_records=({"vpa_A3_per_atom": 5.0},),
        )


def test_unknown_cell_mode_rejected() -> None:
    with pytest.raises(ValueError, match="cell_mode"):
        resolve_native_cell("Na3Zr2Si2PO12", cell_mode="reference_derived")


def test_all_three_modes_stay_cubic_with_frozen_grid_density() -> None:
    records = ({"vpa_A3_per_atom": 18.0},)
    for mode, kwargs in (
        ("native", {}),
        ("composition_scaled", {}),
        ("retrieval_derived", {"evidence_vpa_records": records}),
    ):
        cell = resolve_native_cell("LiZr2(PO4)3", cell_mode=mode, **kwargs)
        assert cell.a == cell.b == cell.c
        assert (cell.alpha, cell.beta, cell.gamma) == (90.0, 90.0, 90.0)
        assert cell.grid_density == 8
