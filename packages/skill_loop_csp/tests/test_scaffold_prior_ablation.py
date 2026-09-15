from __future__ import annotations

from collections import Counter
from pathlib import Path
import tempfile

import numpy as np
import pytest
from pymatgen.core import Composition, Lattice, Structure

from sok_llm_orchestrator.bench.prospective import FrozenReference, exclude_reference_equivalents
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    _qlip_spp_request_adapter,
)


INFORMATIVE_TARGETS = ("BaTiO3", "CaTiO3", "CsPbBr3", "CsPbCl3", "CsSnBr3")


@pytest.mark.parametrize("formula", INFORMATIVE_TARGETS)
def test_tight_loose_minimal_share_candidate_cell_and_positions(formula: str) -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise(formula)
    records = {
        mode: stages._scaffold(task, WorkflowConfig(output_root=Path("."), scaffold_mode=mode))
        for mode in ("tight", "loose", "minimal")
    }
    structures = [record[1] for record in records.values()]
    assert all(np.allclose(structure.lattice.matrix, structures[0].lattice.matrix) for structure in structures)
    assert all(np.allclose(structure.frac_coords, structures[0].frac_coords) for structure in structures)
    assert all(len(structure) == 5 for structure in structures)
    assert all(structure.composition.reduced_composition == Composition(formula).reduced_composition for structure in structures)


@pytest.mark.parametrize("formula", INFORMATIVE_TARGETS)
def test_actual_canonical_feasible_state_counts_are_informative(formula: str) -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise(formula)
    counts = {
        mode: len(stages.enumerate_feasible_assignments(
            task, WorkflowConfig(output_root=Path("."), scaffold_mode=mode),
        ))
        for mode in ("tight", "loose", "minimal")
    }
    assert counts["tight"] == 1
    assert counts["loose"] == 2
    assert counts["minimal"] > 2


@pytest.mark.parametrize("formula", INFORMATIVE_TARGETS)
def test_minimal_has_no_species_role_or_reference_occupation_prior(formula: str) -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise(formula)
    config = WorkflowConfig(output_root=Path("."), scaffold_mode="minimal")
    scaffold_id, structure, orbits = stages._scaffold(task, config)
    formula_counts = {key: int(value) for key, value in Composition(formula).get_el_amt_dict().items()}
    species = set(formula_counts)
    assert scaffold_id == "abx3_five_site_minimal_assignment_v1"
    assert len(orbits) == len(structure) == 5
    assert all(len(orbit["site_indices"]) == 1 for orbit in orbits)
    assert all(set(orbit["allowed_species"]) == species for orbit in orbits)
    assert all("fixed_species" not in orbit for orbit in orbits)
    assert all(orbit["required_occupancy"] is True for orbit in orbits)
    assignments = stages.enumerate_feasible_assignments(task, config)
    assert all(Counter(assignment) == Counter(formula_counts) for assignment in assignments)


def _touch_pot(root: Path, pair: str) -> None:
    path = root / pair.upper() / f"{pair.upper()}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")


def test_request_on_off_preserves_regulator_and_frozen_objective_weights() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        request_root, regulator_root = root / "request", root / "regulator"
        _touch_pot(request_root, "Ba-O")
        _touch_pot(regulator_root, "Ba-O")
        request_spp = {"pot_root": request_root, "regulator_root": regulator_root}
        enabled_guidance = {
            "pair_results": [{"species_pair": "Ba-O"}],
            "request_supported_pairs": ["Ba-O"], "regulator_fallback_pairs": [],
        }
        disabled_guidance = {
            "pair_results": [{"species_pair": "Ba-O"}],
            "request_supported_pairs": [], "regulator_fallback_pairs": ["Ba-O"],
        }
        config = WorkflowConfig(output_root=root, scaffold_mode="minimal")
        enabled = _qlip_spp_request_adapter(
            pair_guidance=enabled_guidance, request_spp=request_spp, config=config,
        )
        disabled = _qlip_spp_request_adapter(
            pair_guidance=disabled_guidance, request_spp=request_spp, config=config,
        )
        enabled_item = enabled["guidance"][0]
        disabled_item = disabled["guidance"][0]
        assert enabled["diagnostics"]["representation"] == "REQUEST_PLUS_REGULATOR_FALLBACK"
        assert enabled_item["weight"] == 10.0
        assert enabled_item["params"]["regularisation_spp_dir"] == str(regulator_root.resolve())
        assert enabled_item["params"]["regularisation_weight"] == 2.0
        assert disabled["diagnostics"]["representation"] == "REGULATOR_AS_PRIMARY_WEIGHTED"
        assert disabled_item["params"]["pot_root"] == str(regulator_root.resolve())
        assert disabled_item["weight"] == 20.0
        assert config.outer_objective_scale == 10.0 and config.regulator_coefficient == 2.0


def test_reference_exclusion_still_covers_primary_and_pair_expansion() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        reference_path = root / "reference.cif"
        duplicate_path = root / "duplicate.cif"
        structure = Structure(
            Lattice.cubic(4.0), ["Ba", "Ti", "O", "O", "O"],
            [(0, 0, 0), (0.5, 0.5, 0.5), (0.5, 0.5, 0), (0.5, 0, 0.5), (0, 0.5, 0.5)],
        )
        structure.to(filename=reference_path)
        duplicate_path.write_bytes(reference_path.read_bytes())
        reference = FrozenReference.from_cif(
            case_id="RDX-BATIO3", formula="BaTiO3", reference_id="reference-id",
            source_structure_id="source-id", cif_path=reference_path,
        )
        item = lambda structure_id: {
            "structure_id": structure_id, "rank": 1,
            "cif_export": {"status": "exported", "path": str(duplicate_path)},
        }
        result = exclude_reference_equivalents({
            "selected": [item("reference-id")],
            "pair_coverage_expansion": {"selected": [item("expansion-duplicate")]},
        }, reference)
        assert result.retrieval["selected"] == []
        assert result.retrieval["pair_coverage_expansion"]["selected"] == []
        assert {row.retrieval_source for row in result.audit} == {"primary", "pair_coverage_expansion"}
        assert all(not row.included_in_request_spp for row in result.audit)
        assert result.reference_equivalent_evidence_count == 0
