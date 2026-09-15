"""Frozen contracts for the dynamic-cell paper_final_v2 campaign."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from sok_llm_orchestrator.workflow.dynamic_cell import (
    BINARY_SEARCH_TOLERANCE_A,
    EDGE_SAFETY_MARGIN,
    EXPANSION_FACTOR,
    FEASIBILITY_TIME_LIMIT_S,
    MAX_EDGE_EXPANSION,
    MIN_EDGE_BOUND_A,
    MIN_VOLUME_OBSERVATIONS,
    POLICY_VERSION,
)
from sok_llm_orchestrator.workflow.paper_final_v1 import (
    FINAL_TASKS as V1_FINAL_TASKS,
    PAPER_CHGNET_FMAX,
    PAPER_CHGNET_RELAX_CELL,
    PAPER_CHGNET_STEPS,
    PAPER_CUTOFF_A,
    PAPER_GRID_DENSITY,
    PAPER_RETRIEVAL_TOP_K,
    PAPER_SOLVER_GAP,
    PAPER_SOLVER_SEED,
    PAPER_SOLVER_THREADS,
    PAPER_SOLVER_TIME_LIMIT_S,
    PAPER_SPP_CONTRACT,
    TICKET_IDS,
    FinalTask,
    canonical_json_hash,
    frozen_pipeline_payload as v1_frozen_pipeline_payload,
    task_row,
    validate_final_tasks,
)
from sok_llm_orchestrator.workflow.runner import WorkflowConfig


SCHEMA_VERSION = "paper_final_v2.0"
FINAL_TASKS = tuple(
    replace(task, canonical_run_id=task.canonical_run_id.replace("paper-final-v1-", "paper-final-v2-"))
    for task in V1_FINAL_TASKS
)


def paper_workflow_config(output_root: Path, *, run_id: str | None = None) -> WorkflowConfig:
    config = WorkflowConfig(
        output_root=Path(output_root),
        retrieval_depth=PAPER_RETRIEVAL_TOP_K,
        retrieval_demo_export=True,
        cutoff=PAPER_CUTOFF_A,
        spp_artifact_contract=PAPER_SPP_CONTRACT,
        scaffold_mode="none",
        native_qlip=True,
        cell_mode=POLICY_VERSION,
        native_grid_density=PAPER_GRID_DENSITY,
        run_id=run_id,
    )
    assert_paper_workflow_config(config)
    return config


def assert_paper_workflow_config(config: WorkflowConfig) -> None:
    errors = []
    if config.spp_artifact_contract != PAPER_SPP_CONTRACT:
        errors.append(f"spp_artifact_contract must explicitly be {PAPER_SPP_CONTRACT}")
    if not config.native_qlip or config.scaffold_mode != "none" or config.scaffold_dir is not None:
        errors.append("paper_final_v2 requires native non-scaffold QLIP")
    if config.cell_mode != POLICY_VERSION or config.native_grid_density != PAPER_GRID_DENSITY:
        errors.append(f"paper_final_v2 requires {POLICY_VERSION} on the frozen 4x4x4 grid")
    if config.cutoff != PAPER_CUTOFF_A or config.retrieval_depth != PAPER_RETRIEVAL_TOP_K:
        errors.append("paper_final_v2 retrieval/cutoff settings differ from v1")
    if (
        config.solver_time_limit_s != PAPER_SOLVER_TIME_LIMIT_S
        or config.solver_threads != PAPER_SOLVER_THREADS
        or config.solver_mip_gap != PAPER_SOLVER_GAP
        or config.solver_seed != PAPER_SOLVER_SEED
    ):
        errors.append("paper_final_v2 QLIP solver defaults differ from the frozen policy")
    if config.proximity_scale != 1.0:
        errors.append("paper_final_v2 requires proximity.atomic_radii(scale=1.0)")
    if errors:
        raise ValueError("; ".join(errors))


def frozen_pipeline_payload() -> dict[str, object]:
    payload = copy.deepcopy(v1_frozen_pipeline_payload())
    payload["schema_version"] = SCHEMA_VERSION
    payload["campaign"] = "paper_final_v2"
    payload["supersedes"] = "paper_final_v1"
    payload["only_intended_scientific_change"] = "search-cell construction"
    payload["search_cell"] = {
        "policy_version": POLICY_VERSION,
        "shape": "cubic",
        "grid_dimensions": [PAPER_GRID_DENSITY] * 3,
        "candidate_positions": PAPER_GRID_DENSITY**3,
        "retrieval_statistic": "median leakage-filtered evidence CIF volume per atom",
        "minimum_valid_volume_observations": MIN_VOLUME_OBSERVATIONS,
        "fallback": "frozen global mp_stable_10k_v1 median VPA",
        "hard_feasibility": "QLIP Allocation.encode + proximity.atomic_radii(scale=1.0), zero objective",
        "expansion_factor": EXPANSION_FACTOR,
        "maximum_edge_expansion": MAX_EDGE_EXPANSION,
        "minimum_edge_bound_A": MIN_EDGE_BOUND_A,
        "binary_search_tolerance_A": BINARY_SEARCH_TOLERANCE_A,
        "edge_safety_margin": EDGE_SAFETY_MARGIN,
        "feasibility_time_limit_s_per_check": FEASIBILITY_TIME_LIMIT_S,
        "final_rule": "a_search=max(a_prior,a_geom_upper_bound)*edge_safety_margin; V_search=a_search^3",
        "spp_used_by_feasibility": False,
    }
    return payload


def structured_task(task: FinalTask) -> dict[str, object]:
    payload = task.structured_task()
    payload["solver_options"] = {
        "cell_mode": POLICY_VERSION,
        "native_grid_density": PAPER_GRID_DENSITY,
    }
    return payload


def validate_v2_tasks(
    tasks: Iterable[FinalTask] = FINAL_TASKS, *, repo_root: Path | None = None
) -> None:
    validate_final_tasks(tasks, repo_root=repo_root)


__all__ = [
    "FINAL_TASKS",
    "PAPER_CHGNET_FMAX",
    "PAPER_CHGNET_RELAX_CELL",
    "PAPER_CHGNET_STEPS",
    "PAPER_SOLVER_GAP",
    "PAPER_SOLVER_SEED",
    "PAPER_SOLVER_THREADS",
    "PAPER_SOLVER_TIME_LIMIT_S",
    "PAPER_SPP_CONTRACT",
    "SCHEMA_VERSION",
    "TICKET_IDS",
    "assert_paper_workflow_config",
    "canonical_json_hash",
    "frozen_pipeline_payload",
    "paper_workflow_config",
    "structured_task",
    "task_row",
    "validate_v2_tasks",
]
