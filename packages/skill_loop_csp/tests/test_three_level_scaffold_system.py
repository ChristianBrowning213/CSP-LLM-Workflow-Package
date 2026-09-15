from __future__ import annotations

import json
import csv
import tempfile
from pathlib import Path

import pytest

from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages
from sok_llm_orchestrator.workflow.scaffold_ablation import load_selection, native_selection
from scripts.finalize_three_level_scaffold_papers import figure4a_coordinate_source


ROOT = Path(__file__).resolve().parents[1]
LOOSE = ROOT / "experiments" / "scaffold_ablation" / "scaffolds" / "loose"
HARD = ROOT / "experiments" / "scaffold_ablation" / "scaffolds" / "hard"


def _task(formula: str) -> dict:
    return ProductionWorkflowStages().normalise(formula)


def test_absent_scaffold_registry_is_actual_native_qlip_uniform_grid(monkeypatch) -> None:
    import qlip.scaffolds

    monkeypatch.setattr(qlip.scaffolds, "get_scaffold", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("registry loaded")))
    selection = load_selection(_task("Na3Zr2Si2PO12"), None)
    assert selection.mode == "none"
    assert selection.structure is None
    assert selection.orbits == ()
    assert selection.native_sites == {"mode": "uniform_grid", "uniform_grid": {"density": 8}}
    assert selection.candidate_site_count == 512
    assert selection.symmetry_orbit_count == 0
    assert selection.species_fixed_orbit_count == 0
    assert selection.scaffold_id == "qlip_native_uniform_grid"


def test_native_required_pairs_never_calls_prototype_or_scaffold_path(monkeypatch) -> None:
    from sok_llm_orchestrator.workflow.runner import WorkflowConfig

    stages = ProductionWorkflowStages()
    monkeypatch.setattr(stages, "_scaffold", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scaffold path used")))
    pairs = stages.required_pairs(_task("Na3Zr2Si2PO12"), WorkflowConfig(output_root=Path("."), scaffold_mode="none", native_qlip=True))
    assert "Na-Zr" in pairs
    assert "O-O" in pairs


def test_requested_directories_load_only_their_declared_registry() -> None:
    task = _task("Na3Zr2Si2PO12")
    assert load_selection(task, LOOSE).mode == "loose"
    assert load_selection(task, HARD).mode == "hard"
    with tempfile.TemporaryDirectory() as temporary:
        bad = Path(temporary)
        (bad / "registry.json").write_text(json.dumps({"schema_version": "nasicon_scaffold_ablation_registry.v1", "mode": "hard", "targets": {}}), encoding="utf-8")
        try:
            load_selection(task, bad)
        except KeyError as exc:
            assert "not registered" in str(exc)
        else:
            raise AssertionError("missing target silently fell back to a scaffold")


def test_loose_transformation_is_deterministic_and_geometry_identical() -> None:
    for formula in ("Na3Zr2Si2PO12", "Na3Ti2(PO4)3", "LiZr2(PO4)3"):
        task = _task(formula)
        first, second, hard = load_selection(task, LOOSE), load_selection(task, LOOSE), load_selection(task, HARD)
        assert first.scaffold_hash == second.scaffold_hash
        assert first.structure is not None and hard.structure is not None
        assert first.structure.lattice == hard.structure.lattice
        assert (first.structure.frac_coords == hard.structure.frac_coords).all()
        assert [orbit["site_indices"] for orbit in first.orbits] == [orbit["site_indices"] for orbit in hard.orbits]
        assert first.species_fixed_orbit_count == 0
        assert first.variable_orbit_count == first.symmetry_orbit_count


def test_hard_registry_matches_current_production_semantics() -> None:
    from qlip.paper_diversity.smoke_preparation import task_orbits
    from qlip.scaffolds import get_scaffold

    expected = {
        "Na3Zr2Si2PO12": (22, 18, 4, 3),
        "Na3Ti2(PO4)3": (8, 8, 0, 1),
        "LiZr2(PO4)3": (5, 5, 0, 1),
    }
    for formula, counts in expected.items():
        selection = load_selection(_task(formula), HARD)
        assert (selection.symmetry_orbit_count, selection.species_fixed_orbit_count, selection.variable_orbit_count, selection.feasible_state_count) == counts
        registered = get_scaffold(selection.scaffold_id)
        assert list(selection.orbits) == task_orbits({"target_formula": formula}, registered)


def test_native_selection_does_not_depend_on_registered_nasicon_coordinates() -> None:
    one = native_selection("Na3Zr2Si2PO12")
    two = native_selection("Na3Ti2(PO4)3")
    assert one.native_template == two.native_template
    assert one.native_sites == two.native_sites
    assert one.structure is two.structure is None
    assert one.orbits == two.orbits == ()


def test_native_selection_default_cell_is_byte_identical_to_frozen_production_defaults() -> None:
    """resolved_cell=None must reproduce the exact original hardcoded behavior."""
    selection = native_selection("Na3Zr2Si2PO12")
    assert selection.native_template == {
        "name": "cubic",
        "lattice": {"a": 3.9, "b": 3.9, "c": 3.9, "alpha": 90.0, "beta": 90.0, "gamma": 90.0, "units": "angstrom"},
    }
    assert selection.native_sites == {"mode": "uniform_grid", "uniform_grid": {"density": 8}}
    assert selection.native_constraints == ({"id": "proximity.atomic_radii", "params": {"scale": 1.0}},)
    assert selection.candidate_site_count == 512
    assert selection.scaffold_id == "qlip_native_uniform_grid"
    assert selection.cell_provenance is None
    assert selection.provenance().get("cell_provenance") is None


def test_native_selection_resolved_cell_changes_only_physical_edge_length() -> None:
    from sok_llm_orchestrator.workflow.cell_strategy import resolve_native_cell

    resolved = resolve_native_cell("Na3Zr2Si2PO12", cell_mode="composition_scaled")
    selection = native_selection("Na3Zr2Si2PO12", resolved_cell=resolved)
    assert selection.native_template["lattice"]["a"] == pytest.approx(resolved.a)
    assert selection.native_template["lattice"]["a"] != 3.9
    assert selection.native_template["lattice"]["alpha"] == 90.0
    # Grid density and the atomic-radii proximity constraint stay frozen.
    assert selection.native_sites == {"mode": "uniform_grid", "uniform_grid": {"density": 8}}
    assert selection.candidate_site_count == 512
    assert selection.native_constraints == ({"id": "proximity.atomic_radii", "params": {"scale": 1.0}},)
    assert selection.scaffold_id == "qlip_native_uniform_grid_composition_scaled"
    assert selection.cell_provenance is not None
    assert selection.cell_provenance["cell_mode"] == "composition_scaled"
    assert selection.provenance()["cell_provenance"]["cell_mode"] == "composition_scaled"


def test_load_selection_threads_resolved_cell_through_native_path() -> None:
    from sok_llm_orchestrator.workflow.cell_strategy import resolve_native_cell

    task = _task("LiZr2(PO4)3")
    resolved = resolve_native_cell("LiZr2(PO4)3", cell_mode="composition_scaled")
    selection = load_selection(task, None, resolved_cell=resolved)
    assert selection.native_template["lattice"]["a"] == pytest.approx(resolved.a)


def test_frozen_rows_change_only_search_space_prior_within_each_target() -> None:
    table = ROOT / "experiments" / "scaffold_ablation" / "NASICON_SCAFFOLD_ABLATION.csv"
    with table.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for formula in {row["formula"] for row in rows}:
        group = [row for row in rows if row["formula"] == formula]
        assert {row["scaffold_mode"] for row in group} == {"none", "loose", "hard"}
        for field in ("request", "request_spp_mode", "corpus", "retrieval_depth", "run_sca", "run_chgnet"):
            assert len({row[field] for row in group}) == 1


def test_figure4a_source_manifest_uses_actual_native_and_scaffold_coordinates() -> None:
    rows = figure4a_coordinate_source()
    by_mode = {mode: [row for row in rows if row["mode"] == mode] for mode in ("none", "loose", "hard")}
    assert len(by_mode["none"]) == 512
    assert len(by_mode["loose"]) == len(by_mode["hard"]) == 40
    assert {row["occupation_class"] for row in by_mode["none"]} == {"native-unconstrained"}
    hard = load_selection(_task("Na3Zr2Si2PO12"), HARD)
    assert hard.structure is not None
    for source, fractional, cartesian in zip(by_mode["hard"], hard.structure.frac_coords, hard.structure.cart_coords):
        assert [source["frac_x"], source["frac_y"], source["frac_z"]] == list(fractional)
        assert [source["cart_x_A"], source["cart_y_A"], source["cart_z_A"]] == list(cartesian)
        assert source["orbit_id"]
        assert source["scaffold_hash"] == hard.scaffold_hash
