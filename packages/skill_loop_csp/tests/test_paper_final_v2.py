from __future__ import annotations

from pathlib import Path

import pytest

from sok_llm_orchestrator.workflow.dynamic_cell import POLICY_VERSION
from sok_llm_orchestrator.workflow.paper_final_v1 import frozen_pipeline_payload as v1_payload
from sok_llm_orchestrator.workflow.paper_final_v2 import (
    FINAL_TASKS,
    assert_paper_workflow_config,
    frozen_pipeline_payload,
    paper_workflow_config,
    structured_task,
    validate_v2_tasks,
)
from sok_llm_orchestrator.workflow.runner import WorkflowConfig


REPO = Path(__file__).resolve().parents[1]


def test_v2_retains_exact_v1_task_set_with_new_run_ids() -> None:
    validate_v2_tasks(repo_root=REPO)
    assert len(FINAL_TASKS) == 16
    assert all(task.canonical_run_id.startswith("paper-final-v2-") for task in FINAL_TASKS)
    assert all(structured_task(task)["solver_options"]["cell_mode"] == POLICY_VERSION for task in FINAL_TASKS)


def test_v2_config_changes_only_the_search_cell_mode() -> None:
    config = paper_workflow_config(REPO / "unused")
    assert config.cell_mode == POLICY_VERSION
    assert config.native_grid_density == 4
    assert config.spp_artifact_contract == "dmytro_gr_v1"
    assert config.native_qlip is True
    assert config.scaffold_mode == "none"


def test_v2_payload_preserves_frozen_non_cell_protocols() -> None:
    old = v1_payload()
    new = frozen_pipeline_payload()
    for section in ("task_formulation", "retrieval", "spp", "qlip", "sca", "chgnet"):
        assert new[section] == old[section]
    assert new["search_cell"]["policy_version"] == POLICY_VERSION
    assert new["campaign"] == "paper_final_v2"
    assert new["supersedes"] == "paper_final_v1"


def test_v2_rejects_old_composition_scaled_cell() -> None:
    old = WorkflowConfig(
        output_root=REPO / "unused",
        retrieval_depth=50,
        cutoff=10.0,
        spp_artifact_contract="dmytro_gr_v1",
        scaffold_mode="none",
        native_qlip=True,
        cell_mode="composition_scaled",
        native_grid_density=4,
    )
    with pytest.raises(ValueError, match=POLICY_VERSION):
        assert_paper_workflow_config(old)
