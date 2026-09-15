"""Frozen contracts for the non-scaffold 16-task final paper campaign."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from pymatgen.core import Composition

from sok_llm_orchestrator.workflow.cell_strategy import GLOBAL_VPA_A3_PER_ATOM
from sok_llm_orchestrator.workflow.runner import WorkflowConfig


SCHEMA_VERSION = "paper_final_v1.1"
STRUCTURED_TASK_SCHEMA_VERSION = "deterministic_crystallographic_task.v1"
PAPER_SPP_CONTRACT = "dmytro_gr_v1"
PAPER_RETRIEVAL_TOP_K = 50
PAPER_SPP_CORPUS_LIMIT = 30
PAPER_CUTOFF_A = 10.0
PAPER_GRID_DENSITY = 4
PAPER_SOLVER_TIME_LIMIT_S = 300
PAPER_SOLVER_GAP = 0.0
PAPER_SOLVER_THREADS = 1
PAPER_SOLVER_SEED = 0
PAPER_CHGNET_FMAX = 0.1
PAPER_CHGNET_STEPS = 80
PAPER_CHGNET_RELAX_CELL = True


@dataclass(frozen=True, slots=True)
class FinalTask:
    task_id: str
    formula: str
    original_request: str
    target_family: str
    target_space_group: str | None
    space_group_required: bool
    space_group_requirement_type: str
    intent_source: str
    canonical_run_id: str

    def structured_task(self) -> dict[str, Any]:
        return {
            "schema_version": STRUCTURED_TASK_SCHEMA_VERSION,
            "composition": self.formula,
            "family_intent": self.target_family,
            "space_group": self.target_space_group,
            "space_group_required": self.space_group_required,
            "space_group_requirement_type": self.space_group_requirement_type,
            "constraints": {"scaffold": "forbidden", "exact_composition": True},
            "retrieval_query": self.original_request,
            "solver_options": {"cell_mode": "composition_scaled", "native_grid_density": PAPER_GRID_DENSITY},
        }


_EXP1 = "local_runs/paper_experiment_1_common_v1/EXPERIMENT_MANIFEST.csv"
_EXP2 = "local_runs/paper_experiment_2_hard_v3/EXPERIMENT_MANIFEST.csv"
_LI2FEO3 = "artifacts/crystal_db/spp_only_oxide_benchmark_v4_taxonomy_fixed/results/paper_workflow_li2feo3/REQUEST.json"


FINAL_TASKS = (
    FinalTask("mgo", "MgO", "Generate a rocksalt magnesium oxide structure from retrieved oxide analogues.", "rocksalt", "Fm-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-mgo"),
    FinalTask("tin", "TiN", "Generate a rocksalt titanium nitride candidate using Crystal-DB nitride evidence.", "nitride", "Fm-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-tin"),
    FinalTask("zro2", "ZrO2", "Generate a fluorite zirconium dioxide candidate using retrieved oxide evidence.", "fluorite", "Fm-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-zro2"),
    FinalTask("batio3", "BaTiO3", "Generate a barium titanate perovskite candidate using retrieved titanate evidence.", "perovskite", "Pm-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-batio3"),
    FinalTask("catio3", "CaTiO3", "Generate a calcium titanate perovskite candidate with corner-sharing TiO6 octahedra using retrieved titanate evidence.", "perovskite", "Pm-3m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-catio3"),
    FinalTask("srtio3", "SrTiO3", "Generate a strontium titanate perovskite prototype using retrieved titanate evidence and explicit Sr-O Ti-O pair guidance.", "perovskite", "Pm-3m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-srtio3"),
    FinalTask("cspbbr3", "CsPbBr3", "Generate a cesium lead bromide halide perovskite prototype using Crystal-DB evidence and explicit SPP guidance.", "halide perovskite", "Pm-3m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-cspbbr3"),
    FinalTask("cspbcl3", "CsPbCl3", "Generate a cubic halide perovskite prototype candidate for CsPbCl3 using retrieved chloride perovskite evidence.", "halide perovskite", "Pm-3m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-cspbcl3"),
    FinalTask("cssni3", "CsSnI3", "Generate a cesium tin iodide halide perovskite prototype with formula CsSnI3 using retrieved iodide evidence.", "halide perovskite", "Pm-3m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-cssni3"),
    FinalTask("znfe2o4", "ZnFe2O4", "Generate a spinel zinc ferrite candidate with formula ZnFe2O4.", "spinel", "Fd-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-znfe2o4"),
    FinalTask("mgal2o4", "MgAl2O4", "Generate a spinel magnesium aluminate candidate using retrieved oxide evidence.", "spinel", "Fd-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-mgal2o4"),
    FinalTask("cofe2o4", "CoFe2O4", "Generate a spinel cobalt ferrite candidate using retrieved ferrite evidence.", "spinel", "Fd-3m", True, "POSTHOC_EXPECTATION", _EXP1, "paper-final-v1-cofe2o4"),
    FinalTask("li6ps5cl", "Li6PS5Cl", "Generate an argyrodite-like lithium thiophosphate chloride candidate with formula Li6PS5Cl using retrieved sulfide-halide evidence.", "argyrodite", "F-43m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-li6ps5cl"),
    FinalTask("licoo2", "LiCoO2", "Generate a layered lithium cobalt oxide candidate compatible with the requested R-3m prototype.", "layered oxide", "R-3m", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-licoo2"),
    FinalTask("lifepo4", "LiFePO4", "Generate an olivine phosphate candidate for LiFePO4 using retrieved lithium iron phosphate evidence.", "olivine phosphate", "Pnma", True, "POSTHOC_EXPECTATION", _EXP2, "paper-final-v1-lifepo4"),
    FinalTask("li2feo3", "Li2FeO3", "Generate a plausible layered battery oxide crystal structure for Li2FeO3.", "layered battery oxide", None, False, "NOT_REQUESTED", _LI2FEO3, "paper-final-v1-li2feo3"),
)


TICKET_IDS = tuple(
    f"T{epic}.{ticket}"
    for epic, count in ((1, 2), (2, 2), (3, 2), (4, 3), (5, 4), (6, 2), (7, 4), (8, 3), (9, 3), (10, 3), (11, 1), (12, 2), (13, 2), (14, 2), (15, 2))
    for ticket in range(1, count + 1)
)


def paper_workflow_config(output_root: Path, *, run_id: str | None = None) -> WorkflowConfig:
    config = WorkflowConfig(
        output_root=Path(output_root), retrieval_depth=PAPER_RETRIEVAL_TOP_K,
        retrieval_demo_export=True, cutoff=PAPER_CUTOFF_A,
        spp_artifact_contract=PAPER_SPP_CONTRACT,
        scaffold_mode="none", native_qlip=True, cell_mode="composition_scaled",
        native_grid_density=PAPER_GRID_DENSITY, run_id=run_id,
    )
    assert_paper_workflow_config(config)
    return config


def assert_paper_workflow_config(config: WorkflowConfig) -> None:
    errors = []
    if config.spp_artifact_contract != PAPER_SPP_CONTRACT:
        errors.append(f"spp_artifact_contract must explicitly be {PAPER_SPP_CONTRACT}")
    if not config.native_qlip or config.scaffold_mode != "none" or config.scaffold_dir is not None:
        errors.append("paper_final_v1 requires native non-scaffold QLIP")
    if config.cell_mode != "composition_scaled" or config.native_grid_density != PAPER_GRID_DENSITY:
        errors.append("paper_final_v1 requires the frozen composition-scaled 4x4x4 search grid")
    if config.cutoff != PAPER_CUTOFF_A or config.retrieval_depth != PAPER_RETRIEVAL_TOP_K:
        errors.append("paper_final_v1 retrieval/cutoff settings differ from the frozen policy")
    if errors:
        raise ValueError("; ".join(errors))


def validate_final_tasks(tasks: Iterable[FinalTask] = FINAL_TASKS, *, repo_root: Path | None = None) -> None:
    rows = tuple(tasks)
    if len(rows) != 16 or len({row.formula for row in rows}) != 16 or len({row.task_id for row in rows}) != 16:
        raise ValueError("paper_final_v1 must contain exactly 16 unique formulas and task IDs")
    forbidden = ("nasicon", "nzp", "scaffold")
    for row in rows:
        text = f"{row.formula} {row.target_family}".lower()
        if any(token in text for token in forbidden):
            raise ValueError(f"forbidden final-paper task: {row.task_id}")
        if row.space_group_requirement_type not in {"POSTHOC_EXPECTATION", "NOT_REQUESTED"}:
            raise ValueError(f"invalid non-scaffold SG semantics: {row.task_id}")
        if row.space_group_required != (row.space_group_requirement_type == "POSTHOC_EXPECTATION"):
            raise ValueError(f"inconsistent SG requirement: {row.task_id}")
        Composition(row.formula)
        if repo_root is not None and not (Path(repo_root) / row.intent_source).resolve().is_file():
            raise FileNotFoundError(f"intent source unavailable for {row.task_id}: {row.intent_source}")


def frozen_pipeline_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "campaign": "paper_final_v1",
        "task_formulation": {
            "mechanism": "deterministic_manual_mapping",
            "llm_used": False, "provider": None, "model": None, "temperature": None,
            "schema_version": STRUCTURED_TASK_SCHEMA_VERSION,
            "validation": "FinalTask validation plus ProductionWorkflowStages.normalise",
        },
        "retrieval": {
            "backend": "crystal_db.retrieval.text_search", "top_k": PAPER_RETRIEVAL_TOP_K,
            "embedding_engine": "lmstudio", "embedding_model": "text-embedding-bge-m3",
            "embedding_version": "lmstudio_v1", "text_engine": "robocrys",
            "text_view": "robocrys", "similarity_metric": "backend cosine similarity",
            "deduplication": "Crystal-DB backend record identity", "excluded_structure_ids": [],
            "designated_reference_record_excluded": False,
        },
        "spp": {
            "artifact_contract": PAPER_SPP_CONTRACT, "explicitly_pinned": True,
            "grid": {"bin_count": 200, "first_center_A": 0.025, "last_center_A": 9.975, "spacing_A": 0.05, "edges_A": [0.0, 10.0]},
            "gaussian_sigma_A": 0.1, "truncate_sigma": 3.0, "epsilon": 1e-12,
            "transform": "U(r)=-ln(g(r)+1e-12)", "minimum_shifted": False,
            "local_valid": "finite strictly increasing 200-point POT produced for the pair",
            "request_status_separate_from_selected_source": True,
            "prior_weight": "0.05 + 0.15*(1-confidence)",
            "confidence": "sqrt(min(n_structures/20,1)*min(log1p(n_observations)/log1p(20000),1))",
            "global_only": "local artifact absent or invalid and converted global RDF valid",
        },
        "search_cell": {
            "mode": "composition_scaled", "volume_per_atom_A3": GLOBAL_VPA_A3_PER_ATOM,
            "target_volume": "literal_formula_atom_count * volume_per_atom_A3",
            "shape": "cubic", "edge": "target_volume**(1/3)",
            "grid_dimensions": [PAPER_GRID_DENSITY] * 3,
            "candidate_positions": PAPER_GRID_DENSITY**3,
        },
        "qlip": {
            "solver": "Gurobi via Pyomo", "problem_class": "native nonconvex binary MIQP",
            "quadratic_handling": "native x[a,i]*x[b,j] products; Gurobi NonConvex=2; no auxiliary linearisation",
            "time_limit_s": PAPER_SOLVER_TIME_LIMIT_S, "mip_gap": PAPER_SOLVER_GAP,
            "threads": PAPER_SOLVER_THREADS,
            "seed_requested": PAPER_SOLVER_SEED,
            "seed_effective": "Gurobi default (QLIP 0.3.0 adapter does not forward integer zero)",
            "feasibility_tolerance": "Gurobi default", "optimality_tolerance": "Gurobi default",
            "periodic_interactions": "all lattice images within 10 A; zero-distance central self image excluded",
        },
        "sca": {"backend": "sca.pipelines.evaluate_one_cif", "symprec": 0.01, "angle_tolerance_deg": 5.0, "run_alignn": False},
        "chgnet": {"model": "CHGNet.load() pretrained checkpoint", "optimizer": "StructOptimizer default FIRE", "fmax_eV_per_A": PAPER_CHGNET_FMAX, "max_steps": PAPER_CHGNET_STEPS, "relax_cell": PAPER_CHGNET_RELAX_CELL, "device": "runtime auto-detection", "timeout_s": None, "timeout_policy": "no wrapper timeout; maximum optimizer steps is the terminal control"},
    }


def canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def task_row(task: FinalTask, output_root: Path) -> dict[str, Any]:
    structured = Path(output_root) / "runs" / task.task_id / "structured_task" / "structured_task.json"
    return asdict(task) | {"structured_task_path": str(structured.resolve())}


__all__ = [
    "FINAL_TASKS", "FinalTask", "PAPER_CHGNET_FMAX", "PAPER_CHGNET_RELAX_CELL",
    "PAPER_CHGNET_STEPS", "PAPER_SPP_CONTRACT", "SCHEMA_VERSION", "TICKET_IDS",
    "assert_paper_workflow_config", "canonical_json_hash", "frozen_pipeline_payload",
    "paper_workflow_config", "task_row", "validate_final_tasks",
]
