from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.workflow.dynamic_cell import (
    EDGE_SAFETY_MARGIN,
    MAX_EDGE_EXPANSION,
    POLICY_VERSION,
    qlip_hard_geometry_feasibility,
    resolve_dynamic_cell,
    resolved_cell_from_dict,
    retrieval_volume_prior,
)


FORMULAS = (
    "CaTiO3",
    "BaTiO3",
    "SrTiO3",
    "CsPbBr3",
    "CsPbCl3",
    "CsSnI3",
    "MgO",
    "MgAl2O4",
    "LiCoO2",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(root: Path) -> list[dict[str, object]]:
    records = []
    for index, edge in enumerate((3.0, 3.2, 3.4, 3.6, 3.8), start=1):
        path = root / f"analogue_{index}.cif"
        Structure(
            Lattice.cubic(edge),
            ["Na", "Cl"],
            [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        ).to(filename=path)
        records.append({
            "retrieval_rank": index,
            "structure_id": f"analogue-{index}",
            "cif_path": str(path),
            "cif_sha256": _sha256(path),
        })
    return records


def _threshold_checker(_formula: str, edge: float) -> dict[str, object]:
    feasible = edge >= 5.0
    return {
        "status": "FEASIBLE" if feasible else "INFEASIBLE",
        "feasible": feasible,
        "termination_condition": "synthetic_test_witness",
        "edge_A": edge,
    }


@pytest.mark.parametrize("formula", FORMULAS)
def test_dynamic_cell_is_deterministic_for_required_chemistry_classes(formula: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        evidence = _evidence(Path(directory))
        first, first_provenance = resolve_dynamic_cell(
            formula, evidence, grid_density=4, feasibility_checker=_threshold_checker
        )
        second, second_provenance = resolve_dynamic_cell(
            formula, evidence, grid_density=4, feasibility_checker=_threshold_checker
        )
    assert first.to_dict() == second.to_dict()
    assert first_provenance == second_provenance
    assert first.cell_mode == POLICY_VERSION
    assert first.a >= 5.0 * EDGE_SAFETY_MARGIN
    assert first.grid_density == 4


def test_retrieval_prior_excludes_target_reference_and_duplicate_without_leakage() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        evidence = _evidence(root)
        target = root / "target.cif"
        Structure(
            Lattice.cubic(4.0),
            ["Ba", "Ti", "O", "O", "O"],
            [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
        ).to(filename=target)
        evidence.append({"structure_id": "target", "cif_path": str(target), "cif_sha256": _sha256(target)})
        evidence.append(dict(evidence[0]) | {"structure_id": "duplicate"})
        prior = retrieval_volume_prior("BaTiO3", evidence)
    reasons = {row["retrieved_record_id"]: row["exclusion_reason"] for row in prior["records"]}
    assert prior["status"] == "RETRIEVAL_VOLUME_USABLE"
    assert prior["valid_observation_count"] == 5
    assert reasons["target"] == "TARGET_REDUCED_COMPOSITION"
    assert reasons["duplicate"] == "DUPLICATE_CIF_HASH"


def test_retrieval_prior_has_explicit_global_fallback() -> None:
    with tempfile.TemporaryDirectory() as directory:
        prior = retrieval_volume_prior("MgO", _evidence(Path(directory))[:2])
    assert prior["retrieval_volume_status"] == "RETRIEVAL_VOLUME_INSUFFICIENT"
    assert prior["status"] == "GLOBAL_VOLUME_FALLBACK"
    assert prior["vpa_source"] == "frozen_global_corpus_median_fallback"


def test_dynamic_cell_expansion_is_bounded_and_failure_is_explicit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        evidence = _evidence(Path(directory))

        def never_feasible(_formula: str, edge: float) -> dict[str, object]:
            return {"status": "INFEASIBLE", "feasible": False, "edge_A": edge}

        with pytest.raises(RuntimeError, match="GEOMETRY_NOT_FEASIBLE_WITHIN_BOUND"):
            resolve_dynamic_cell(
                "BaTiO3", evidence, grid_density=4, feasibility_checker=never_feasible
            )
        prior = retrieval_volume_prior("BaTiO3", evidence)
        assert prior["a_prior_A"] * MAX_EDGE_EXPANSION > prior["a_prior_A"]


def test_persisted_dynamic_cell_round_trip() -> None:
    with tempfile.TemporaryDirectory() as directory:
        cell, _ = resolve_dynamic_cell(
            "BaTiO3",
            _evidence(Path(directory)),
            grid_density=4,
            feasibility_checker=_threshold_checker,
        )
    assert resolved_cell_from_dict(cell.to_dict()) == cell


def test_real_qlip_hard_model_separates_old_ca_and_ba_cells() -> None:
    ca = qlip_hard_geometry_feasibility("CaTiO3", 4.480317269262231, grid_density=4)
    ba = qlip_hard_geometry_feasibility("BaTiO3", 4.480317269262231, grid_density=4)
    assert ca["status"] == "FEASIBLE"
    assert ba["status"] == "INFEASIBLE"
    assert ca["spp_objective_used"] is False
    assert ba["spp_objective_used"] is False
