from __future__ import annotations

from pathlib import Path

import pytest

from sok_llm_orchestrator.workflow.cell_strategy import resolve_native_cell
from sok_llm_orchestrator.workflow.paper_final_v1 import (
    FINAL_TASKS,
    PAPER_SPP_CONTRACT,
    assert_paper_workflow_config,
    frozen_pipeline_payload,
    paper_workflow_config,
    validate_final_tasks,
)
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages, WorkflowConfig


REPO = Path(__file__).resolve().parents[1]


def test_final_16_is_exact_and_excludes_scaffolds_and_nasicon() -> None:
    validate_final_tasks(repo_root=REPO)
    assert [task.formula for task in FINAL_TASKS] == [
        "MgO", "TiN", "ZrO2", "BaTiO3", "CaTiO3", "SrTiO3",
        "CsPbBr3", "CsPbCl3", "CsSnI3", "ZnFe2O4", "MgAl2O4",
        "CoFe2O4", "Li6PS5Cl", "LiCoO2", "LiFePO4", "Li2FeO3",
    ]


def test_paper_config_explicitly_pins_dmytro_and_non_scaffold_mode() -> None:
    config = paper_workflow_config(REPO / "unused")
    assert config.spp_artifact_contract == PAPER_SPP_CONTRACT
    assert config.native_qlip is True
    assert config.scaffold_mode == "none"
    assert config.scaffold_dir is None


def test_paper_preflight_rejects_generic_legacy_default() -> None:
    with pytest.raises(ValueError, match="dmytro_gr_v1"):
        assert_paper_workflow_config(WorkflowConfig(output_root=REPO / "unused"))


@pytest.mark.parametrize("task", FINAL_TASKS, ids=lambda task: task.formula)
def test_all_final_requests_normalise_to_the_frozen_task(task) -> None:
    normalized = ProductionWorkflowStages().normalise(task.original_request)
    assert normalized["formula"] == task.formula
    assert normalized["family"] == task.target_family
    assert normalized["space_group"] == task.target_space_group


@pytest.mark.parametrize("formula", ["MgO", "BaTiO3", "Li6PS5Cl", "Li2FeO3"])
def test_search_cell_reconstructs_deterministically(formula: str) -> None:
    first = resolve_native_cell(formula=formula, cell_mode="composition_scaled", grid_density=4)
    second = resolve_native_cell(formula=formula, cell_mode="composition_scaled", grid_density=4)
    assert first.to_dict() == second.to_dict()
    assert first.grid_density == 4
    assert first.grid_density**3 == 64


def test_frozen_payload_separates_request_status_and_selected_source() -> None:
    payload = frozen_pipeline_payload()
    assert payload["spp"]["artifact_contract"] == "dmytro_gr_v1"
    assert payload["qlip"]["seed_requested"] == 0
    assert "Gurobi default" in payload["qlip"]["seed_effective"]
    assert payload["spp"]["request_status_separate_from_selected_source"] is True
    assert payload["spp"]["grid"] == {
        "bin_count": 200,
        "first_center_A": 0.025,
        "last_center_A": 9.975,
        "spacing_A": 0.05,
        "edges_A": [0.0, 10.0],
    }
