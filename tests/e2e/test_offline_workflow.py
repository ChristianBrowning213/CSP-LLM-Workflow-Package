from __future__ import annotations

import pytest
import pyomo.environ as pyo
from ase import Atoms
from ase.io import write

from llm_csp.retrieval import EvidenceRecord, RetrievalStageResult
from llm_csp.schemas import (
    CSPWorkflowRequest,
    GenerationConfig,
    SPPConfig,
    WorkflowConfig,
)
from llm_csp.workflow import run_csp_workflow
from qlip.resources import bundled_spp_root


EXPECTED_PAIRS = ["O-O", "O-Sr", "O-Ti", "Sr-Sr", "Sr-Ti", "Ti-Ti"]


def _request() -> CSPWorkflowRequest:
    return CSPWorkflowRequest(
        query="cubic strontium titanate perovskite",
        formula="SrTiO3",
        target_space_group="Pm-3m",
        topology_family="PEROVSKITE_3D",
        scaffold_id=None,
        design_space={
            "template": {
                "name": "cubic",
                "lattice": {
                    "a": 3.9, "b": 3.9, "c": 3.9,
                    "alpha": 90.0, "beta": 90.0, "gamma": 90.0,
                    "units": "angstrom",
                },
            },
            "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 2}},
        },
    )


def _provider(cif_path, events=None):
    def retrieve(**kwargs):
        if events is not None:
            events.append("retrieval")
        return RetrievalStageResult(
            "retrieval_success",
            "offline_deterministic_fixture",
            (
                EvidenceRecord(
                    "synthetic-srtio3-evidence",
                    1.0,
                    str(cif_path),
                    {"source": "synthetic", "allow_export": True},
                    {"formula": "SrTiO3"},
                ),
            ),
            {"network": False},
        )
    return retrieve


def _evidence_cif(path):
    atoms = Atoms(
        ["Sr", "Ti", "O", "O", "O"],
        scaled_positions=[[0, 0, 0], [.5, .5, .5], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]],
        cell=[3.9, 3.9, 3.9],
        pbc=True,
    )
    write(path, atoms, format="cif")


def test_complete_offline_packaged_workflow(tmp_path) -> None:
    solver = pyo.SolverFactory("gurobi")
    if solver is None or not solver.available(exception_flag=False):
        pytest.skip("Gurobi not available")
    evidence = tmp_path / "synthetic_evidence.cif"
    _evidence_cif(evidence)
    config = WorkflowConfig(
        output_root=tmp_path / "runs",
        spp=SPPConfig(
            request_mode="disabled",
            regulator_root=bundled_spp_root(),
            request_coefficient=1.0,
            regulator_coefficient=1.0,
            outer_objective_scale=1.0,
        ),
        generation=GenerationConfig(time_limit_s=30),
        retrieval_provider=_provider(evidence),
        run_id="offline-srtio3",
    )

    result = run_csp_workflow(_request(), config)

    assert result.status == "completed"
    assert result.stages["retrieval"]["status"] == "retrieval_success"
    assert result.stages["spp"]["ready"] is True
    assert result.stages["spp"]["required_pairs"] == EXPECTED_PAIRS
    assert result.stages["spp"]["regulator_fallback_pairs"] == EXPECTED_PAIRS
    assert result.stages["qlip"]["status"] == "OPTIMAL"
    assert result.stages["candidate"]["solver_objective"] == pytest.approx(4.883033620558714, abs=1e-9)
    assert result.stages["candidate"]["independent_objective"] == pytest.approx(4.883033620558713, abs=1e-9)
    general = result.stages["validation"]["general"]
    assert general["status"] == "evaluated"
    assert general["parseable"] is True
    assert general["composition"]["formula"] == "Sr1 Ti1 O3"
    assert general["composition"]["target_formula_match"] is True
    assert result.stages["validation"]["topology"]["status"] == "evaluated"
    assert (tmp_path / "runs" / "offline-srtio3" / "run.json").is_file()
    assert (tmp_path / "runs" / "offline-srtio3" / "final" / "candidate.cif").is_file()
