"""Thin canonical Crystal-DB -> SPP -> QLIP -> SCA workflow orchestration."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pymatgen.core import Composition, Structure

from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.structures.prototype_scaffold import ideal_prototype_structure
from sok_llm_orchestrator.structures.variable_perovskite import (
    VariablePerovskiteCase,
    structure_for_assignment,
)
from sok_llm_orchestrator.workflow.cell_strategy import (
    NATIVE_GRID_DENSITY,
    ResolvedCell,
    evidence_vpa_records,
    resolve_native_cell,
)
from sok_llm_orchestrator.workflow.evidence import (
    assemble_spp_evidence,
    canonical_pair,
    required_pairs_for_formula,
)
from sok_llm_orchestrator.workflow.dynamic_cell import (
    POLICY_VERSION as DYNAMIC_CELL_POLICY_VERSION,
    resolve_dynamic_cell,
    resolved_cell_from_dict,
)
from sok_llm_orchestrator.workflow.scaffold_ablation import load_selection
from sok_llm_orchestrator.workflow.spp import (
    REQUEST_DISABLED,
    REQUEST_INSUFFICIENT,
    REQUEST_MISSING,
    REQUEST_USABLE,
    classify_request_pair_quality,
    compile_spp_components,
    guidance_mode_for_pair,
    request_support_status,
    score_spp_components,
)


MAX_GENERIC_CANDIDATE_SITES = 64
MAX_ORDERED_SCAFFOLD_SITES = 128
MAX_EXPLICIT_SITE_BINARY_VARS = 500
MAX_EXPLICIT_SITE_CONSTRAINTS = 1000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.POT"), key=lambda value: value.as_posix().lower()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
        digest.update(b"\n")
    return digest.hexdigest()


def _pair_pot_path(root: Path, pair: str) -> Path | None:
    left, right = pair.split("-", 1)
    for name in (f"{left.upper()}-{right.upper()}", f"{right.upper()}-{left.upper()}"):
        for candidate in (root / name / f"{name}.POT", root / f"{name}.POT"):
            if candidate.is_file():
                return candidate
    return None


def _request_spp_run_id(bundle_hash: str, run_root: Path) -> str:
    return hashlib.sha256(f"{bundle_hash}|{run_root.resolve()}".encode("utf-8")).hexdigest()


def _scientific_config(config: "WorkflowConfig") -> dict[str, Any]:
    return {
        "retrieval_depth": config.retrieval_depth,
        "embedding_model": config.embedding_model,
        "embedding_version": config.embedding_version,
        "retrieval_demo_export": config.retrieval_demo_export,
        "cutoff": config.cutoff,
        "request_coefficient": config.request_coefficient,
        "regulator_coefficient": config.regulator_coefficient,
        "outer_objective_scale": config.outer_objective_scale,
        "request_spp_convention": config.request_spp_convention,
        "spp_artifact_contract": config.spp_artifact_contract,
        "regulator_id": config.regulator_id,
        "excluded_structure_ids": list(config.excluded_structure_ids),
        "scaffold_mode": config.scaffold_mode,
        "scaffold_dir": str(config.scaffold_dir.resolve()) if config.scaffold_dir else None,
        "native_qlip": config.native_qlip,
        "request_spp_mode": config.request_spp_mode,
        "cell_mode": config.cell_mode,
        "cell_volume_per_atom": config.cell_volume_per_atom,
        "native_grid_density": config.native_grid_density,
        "database_selector": config.database_selector,
        "solver_time_limit_s": config.solver_time_limit_s,
        "solver_threads": config.solver_threads,
        "solver_mip_gap": config.solver_mip_gap,
        "solver_seed": config.solver_seed,
        "proximity_scale": config.proximity_scale,
    }


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _workflow_run_id(request: str, config: "WorkflowConfig") -> str:
    return _canonical_hash({"schema": "canonical_workflow_run.v1", "request": request, "config": _scientific_config(config)})


def _new_attempt_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{stamp}-{uuid.uuid4().hex[:12]}"


_TERMINAL_ATTEMPT_STATUSES = {"COMPLETED", "FAILED_CONTROLLED", "FAILED_SOFTWARE", "INTERRUPTED_OR_INCOMPLETE"}


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    run_id: str
    attempt_id: str
    config_hash: str
    workspace: Path
    manifest_path: Path
    prior_incomplete_attempts: tuple[str, ...]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _prepare_execution_attempt(
    config: "WorkflowConfig",
    request: str,
    *,
    attempt_id: str | None = None,
) -> ExecutionAttempt:
    output_root = Path(config.output_root).resolve()
    attempts_root = output_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    run_id = _workflow_run_id(request, config)
    config_hash = _canonical_hash(_scientific_config(config))
    prior_incomplete: list[str] = []
    for manifest_path in sorted(attempts_root.glob("*/attempt_manifest.json")):
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("run_id") != run_id or payload.get("config_hash") != config_hash:
            continue
        if payload.get("status") in {"STARTED", "RUNNING"}:
            payload["status"] = "INTERRUPTED_OR_INCOMPLETE"
            payload["recognized_incomplete_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(manifest_path, payload)
            prior_incomplete.append(str(payload.get("attempt_id")))
    selected_id = attempt_id or _new_attempt_id()
    workspace = attempts_root / selected_id
    manifest_path = workspace / "attempt_manifest.json"
    if workspace.exists():
        if not manifest_path.is_file():
            raise FileExistsError(f"refusing to alter unknown pre-existing attempt workspace: {workspace}")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("run_id") != run_id or existing.get("config_hash") != config_hash:
            raise FileExistsError(f"refusing to alter attempt workspace owned by another run/config: {workspace}")
        if existing.get("status") in _TERMINAL_ATTEMPT_STATUSES:
            raise FileExistsError(f"refusing to overwrite terminal attempt workspace: {workspace}")
        raise FileExistsError(f"attempt id collision for incomplete workspace; request a fresh attempt id: {workspace}")
    workspace.mkdir(parents=False)
    payload = {
        "schema_version": "canonical_workflow_attempt.v1",
        "run_id": run_id,
        "attempt_id": selected_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "workflow_commit": _git_commit(Path(__file__).resolve().parents[3]),
        "config_hash": config_hash,
        "scientific_config": _scientific_config(config),
        "request": request,
        "status": "STARTED",
        "workspace": str(workspace),
        "prior_incomplete_attempts": prior_incomplete,
    }
    _write_json(manifest_path, payload)
    return ExecutionAttempt(run_id, selected_id, config_hash, workspace, manifest_path, tuple(prior_incomplete))


def _update_execution_attempt(attempt: ExecutionAttempt, status: str, **updates: Any) -> None:
    payload = json.loads(attempt.manifest_path.read_text(encoding="utf-8"))
    payload.update(updates)
    payload["status"] = status
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(attempt.manifest_path, payload)


def _qlip_repo_root() -> Path:
    import qlip

    package = Path(qlip.__file__).resolve()
    for parent in package.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src" / "qlip").is_dir():
            return parent
    raise RuntimeError(f"Unable to discover verified QLIP repository root from {package}")


def _qlip_runtime_root(config: "WorkflowConfig") -> Path:
    return Path(config.qlip_runtime_root or (_qlip_repo_root() / "gen_artifacts" / "skill_loop_csp")).resolve()


def _qlip_data_root(config: "WorkflowConfig") -> Path:
    return Path(config.qlip_data_root or (_qlip_repo_root() / "data" / "spp")).resolve()


def _request_spp_runtime_root(config: "WorkflowConfig", bundle_hash: str, run_root: Path) -> Path:
    request_run_id = config.run_id or _request_spp_run_id(bundle_hash, run_root)
    root = _qlip_runtime_root(config) / "runs" / request_run_id
    return root / "attempts" / config.attempt_id if config.attempt_id else root


@contextmanager
def _qlip_pot_authorization(config: "WorkflowConfig"):
    roots = (_qlip_runtime_root(config), _qlip_data_root(config))
    previous = os.environ.get("QLIP_ALLOWED_PATH_ROOTS")
    os.environ["QLIP_ALLOWED_PATH_ROOTS"] = os.pathsep.join(str(root) for root in roots)
    try:
        yield roots
    finally:
        if previous is None:
            os.environ.pop("QLIP_ALLOWED_PATH_ROOTS", None)
        else:
            os.environ["QLIP_ALLOWED_PATH_ROOTS"] = previous


_SUPPORTED_GUIDANCE_MODES = {
    "REQUEST_PLUS_REGULATOR",
    "PREBLENDED_COMPLETE",
    "REGULATOR_ONLY_LOCAL_INSUFFICIENT",
    "REGULATOR_ONLY_LOCAL_MISSING",
    "REGULATOR_ONLY_REQUEST_DISABLED",
}


def _solver_pair_guidance(required_pairs: list[str], pair_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate canonical pair decisions and derive QLIP's local/fallback sets."""
    by_pair = {str(row.get("species_pair")): row for row in pair_results}
    unsupported = [
        pair for pair in required_pairs
        if pair not in by_pair or str(by_pair[pair].get("guidance_mode")) not in _SUPPORTED_GUIDANCE_MODES
    ]
    if unsupported:
        raise WorkflowStageError(
            "guidance_pair_coverage",
            "GUIDANCE_PAIR_UNSUPPORTED",
            f"Required pairs lack a supported guidance mode: {', '.join(unsupported)}",
            details={"unsupported_pairs": unsupported, "required_pairs": required_pairs, "pair_results": pair_results},
        )
    request_supported = [pair for pair in required_pairs if by_pair[pair]["guidance_mode"] in {"REQUEST_PLUS_REGULATOR", "PREBLENDED_COMPLETE"}]
    regulator_fallback = [pair for pair in required_pairs if by_pair[pair]["guidance_mode"].startswith("REGULATOR_ONLY_")]
    return {
        "pair_results": [by_pair[pair] for pair in required_pairs],
        "solver_supported_pairs": list(required_pairs),
        "request_supported_pairs": request_supported,
        "regulator_fallback_pairs": regulator_fallback,
        "unsupported_pairs": [],
        "request_statuses": {pair: str(by_pair[pair]["request_pair_status"]) for pair in required_pairs},
    }


def _qlip_spp_request_adapter(
    *,
    pair_guidance: dict[str, Any],
    request_spp: dict[str, Any],
    config: "WorkflowConfig",
) -> dict[str, Any]:
    """Translate canonical pair guidance into QLIP's strict SPP contract."""
    required_pairs = [str(row["species_pair"]) for row in pair_guidance["pair_results"]]
    request_supported = list(pair_guidance["request_supported_pairs"])
    fallback_pairs = list(pair_guidance["regulator_fallback_pairs"])
    request_root = Path(request_spp["pot_root"]).resolve()
    regulator_root = Path(request_spp.get("regulator_root") or "").resolve()
    request_pots = sorted(request_root.rglob("*.POT")) if request_root.is_dir() else []
    regulator_pots = sorted(regulator_root.rglob("*.POT")) if regulator_root.is_dir() else []
    if request_spp.get("blend_mode") == "preblended_pair_level":
        if len(request_pots) < len(required_pairs):
            raise WorkflowStageError(
                "qlip_request_adapter", "PREBLENDED_POT_ROOT_INCOMPLETE",
                "The pair-level blended root does not contain every required POT.",
                details={"required_pairs": required_pairs, "request_pot_root": str(request_root)},
            )
        params = {"pot_root": str(request_root), "mode": "complete", "cutoff": config.cutoff}
        return {
            "context": {"run_id": config.run_id, "pot_root": str(request_root)},
            "guidance": [{"id": "objective.energy_spp", "weight": config.outer_objective_scale * config.request_coefficient, "params": params}],
            "diagnostics": {
                "representation": "PREBLENDED_PAIR_LEVEL_COMPLETE",
                "artifact_contract": request_spp.get("artifact_contract"),
                "request_pot_root": str(request_root), "request_pot_count": len(request_pots),
                "regulator_root": str(regulator_root), "regulator_pot_count": len(regulator_pots),
                "primary_pot_root": str(request_root),
                "guidance_weight": config.outer_objective_scale * config.request_coefficient,
                "required_pairs": required_pairs, "request_supported_pairs": required_pairs,
                "fallback_pairs": [],
            },
        }
    if request_supported and not request_pots:
        raise WorkflowStageError(
            "qlip_request_adapter",
            "REQUEST_POT_ROOT_EMPTY",
            "Request-supported pairs were declared but the request POT root contains no POT files.",
            details={"request_supported_pairs": request_supported, "request_pot_root": str(request_root)},
        )
    if fallback_pairs and not regulator_pots:
        raise WorkflowStageError(
            "guidance_pair_coverage",
            "GUIDANCE_PAIR_UNSUPPORTED",
            "Regulator fallback pairs were declared but the regulator POT root contains no POT files.",
            details={"fallback_pairs": fallback_pairs, "regulator_root": str(regulator_root)},
        )
    if request_supported:
        params = {
            "pot_root": str(request_root),
            "mode": "partial",
            "supported_pairs": request_supported,
            "missing_pairs": fallback_pairs,
            "strict_pair_coverage": False,
            "missing_pair_policy": "fallback",
            "regularisation_spp_dir": str(regulator_root),
            "regularisation_weight": config.regulator_coefficient,
            "cutoff": config.cutoff,
        }
        primary_root = request_root
        guidance_weight = config.outer_objective_scale
        representation = "REQUEST_PLUS_REGULATOR_FALLBACK"
    else:
        if set(fallback_pairs) != set(required_pairs):
            raise WorkflowStageError(
                "guidance_pair_coverage",
                "GUIDANCE_PAIR_UNSUPPORTED",
                "A regulator-only QLIP request must cover every required pair.",
                details={"required_pairs": required_pairs, "fallback_pairs": fallback_pairs},
            )
        params = {"pot_root": str(regulator_root), "mode": "complete", "cutoff": config.cutoff}
        primary_root = regulator_root
        guidance_weight = config.outer_objective_scale * config.regulator_coefficient
        representation = "REGULATOR_AS_PRIMARY_WEIGHTED"
    return {
        "context": {"run_id": config.run_id, "pot_root": str(primary_root)},
        "guidance": [{"id": "objective.energy_spp", "weight": guidance_weight, "params": params}],
        "diagnostics": {
            "representation": representation,
            "request_pot_root": str(request_root),
            "request_pot_count": len(request_pots),
            "regulator_root": str(regulator_root),
            "regulator_pot_count": len(regulator_pots),
            "primary_pot_root": str(primary_root),
            "guidance_weight": guidance_weight,
            "required_pairs": required_pairs,
            "request_supported_pairs": request_supported,
            "fallback_pairs": fallback_pairs,
        },
    }


def _qlip_ordered_orbits_adapter(orbits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project internal ordered-orbit records onto QLIP solve-request v1.0."""
    serialized: list[dict[str, Any]] = []
    optional_fields = ("fixed_species", "required_state", "vacancy_allowed", "allow_partial_occupation")
    for index, orbit in enumerate(orbits):
        orbit_id = str(orbit.get("orbit_id") or "")
        if not orbit_id:
            raise WorkflowStageError(
                "qlip_request_adapter", "ORDERED_ORBIT_ID_MISSING",
                f"Canonical ordered orbit {index} has no non-empty orbit ID.",
            )
        if "site_indices" not in orbit or "allowed_species" not in orbit:
            raise WorkflowStageError(
                "qlip_request_adapter", "ORDERED_ORBIT_CONTRACT_INCOMPLETE",
                f"Canonical ordered orbit {orbit_id} lacks site membership or allowed species.",
            )
        required_occupancy = orbit.get("required_occupancy")
        if required_occupancy is None:
            occupation_mode = str(orbit.get("occupation_mode") or "")
            if occupation_mode.endswith("_FULL_ORBIT"):
                required_occupancy = True
            elif "vacancy_allowed" in orbit:
                required_occupancy = not bool(orbit["vacancy_allowed"])
            else:
                raise WorkflowStageError(
                    "qlip_request_adapter", "ORDERED_ORBIT_OCCUPANCY_UNDEFINED",
                    f"Required occupancy cannot be derived from canonical orbit {orbit_id}.",
                )
        record: dict[str, Any] = {
            "orbit_id": orbit_id,
            "site_indices": [int(value) for value in orbit["site_indices"]],
            "allowed_species": [str(value) for value in orbit["allowed_species"]],
            "required_occupancy": bool(required_occupancy),
        }
        for field_name in optional_fields:
            value = orbit.get(field_name)
            if value is not None:
                record[field_name] = value
        serialized.append(record)
    return serialized


def _qlip_target_formula(task: dict[str, Any], site_count: int) -> str:
    """Serialize the target composition at the explicit candidate-cell scale."""
    target = Composition(str(task["formula"]))
    formula_atom_count = float(target.num_atoms)
    scale = float(site_count) / formula_atom_count if formula_atom_count else 0.0
    integer_scale = round(scale)
    if integer_scale <= 0 or abs(scale - integer_scale) > 1e-9:
        raise WorkflowStageError(
            "qlip_request_adapter", "TARGET_FORMULA_SITE_SCALE_INVALID",
            f"Target formula {task['formula']} cannot be scaled exactly onto {site_count} candidate sites.",
            details={"target_formula": task["formula"], "site_count": site_count, "scale": scale},
        )
    return (target * integer_scale).formula.replace(" ", "")


def _validate_qlip_species_contract(
    *, formula: str, ordered_orbits: list[dict[str, Any]], required_pairs: list[str], guidance: list[dict[str, Any]],
) -> None:
    """Fail before QLIP when target chemistry and active wire species disagree."""
    formula_species = set(Composition(formula).get_el_amt_dict())
    vacancy_state = "VACANCY"
    fixed_species = {
        str(orbit["fixed_species"])
        for orbit in ordered_orbits if orbit.get("fixed_species") and orbit.get("fixed_species") != vacancy_state
    }
    allowed_occupied_species = {
        str(species)
        for orbit in ordered_orbits
        if str(orbit.get("required_state", "AUTO")).upper() != "EMPTY"
        for species in orbit.get("allowed_species", [])
        if str(species) != vacancy_state
    }
    required_pair_species = {species for pair in required_pairs for species in str(pair).split("-", 1)}
    guidance_species: set[str] = set()
    for item in guidance:
        params = item.get("params", {}) if isinstance(item, dict) else {}
        for field_name in ("supported_pairs", "missing_pairs", "required_pairs"):
            for pair in params.get(field_name, []):
                guidance_species.update(str(pair).split("-", 1))
    sources = {
        "fixed_species": fixed_species,
        "allowed_occupied_species": allowed_occupied_species,
        "required_pair_species": required_pair_species,
        "active_guidance_species": guidance_species,
    }
    missing = {name: sorted(values - formula_species) for name, values in sources.items() if values - formula_species}
    if missing:
        raise WorkflowStageError(
            "qlip_request_adapter", "QLIP_SPECIES_CONTRACT_MISMATCH",
            f"QLIP target formula species {sorted(formula_species)} do not cover active wire species: {missing}",
            details={"formula": formula, "formula_species": sorted(formula_species), "missing_by_source": missing},
        )


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    output_root: Path
    retrieval_depth: int = 40
    embedding_model: str = "text-embedding-bge-m3"
    embedding_version: str = "lmstudio_v1"
    retrieval_demo_export: bool = True
    cutoff: float = 11.0
    request_coefficient: float = 1.0
    regulator_coefficient: float = 2.0
    outer_objective_scale: float = 10.0
    request_spp_convention: str = "reward"
    # Keep the generic workflow's established evidence-quality/fallback path
    # as the implicit contract. Scientific campaigns that use the repaired
    # common contract must opt in explicitly in their frozen policy.
    spp_artifact_contract: str = "legacy_histogram_v4"
    regulator_root: Path | None = None
    qlip_runtime_root: Path | None = None
    qlip_data_root: Path | None = None
    regulator_id: str = "icsd_broad_regulator_v1"
    registry_path: Path | None = None
    trace_path: Path | None = None
    excluded_structure_ids: tuple[str, ...] = ()
    scaffold_mode: str = "loose"
    scaffold_dir: Path | None = None
    native_qlip: bool = False
    request_spp_mode: str = "enabled"
    cell_mode: str = "native"
    cell_volume_per_atom: float | None = None
    native_grid_density: int | None = None
    database_selector: str = "auto"
    crystal_db_root: Path | None = None
    solver_time_limit_s: int = 300
    solver_threads: int = 1
    solver_mip_gap: float = 0.0
    solver_seed: int = 0
    proximity_scale: float = 1.0
    run_id: str | None = field(default=None, repr=False, compare=False)
    attempt_id: str | None = field(default=None, repr=False, compare=False)
    stages: "WorkflowStages | None" = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.scaffold_mode not in {"none", "hard", "tight", "loose", "minimal"}:
            raise ValueError("scaffold_mode must be none, hard, tight, loose, or minimal")
        if self.native_qlip and self.scaffold_dir is not None:
            raise ValueError("native QLIP and an explicit scaffold directory are mutually exclusive")
        if self.request_spp_mode not in {"enabled", "disabled"}:
            raise ValueError("request_spp_mode must be 'enabled' or 'disabled'")
        if self.spp_artifact_contract not in {"dmytro_gr_v1", "legacy_histogram_v4"}:
            raise ValueError("spp_artifact_contract must be dmytro_gr_v1 or legacy_histogram_v4")
        if self.cell_mode not in {
            "native", "composition_scaled", "retrieval_derived", DYNAMIC_CELL_POLICY_VERSION,
        }:
            raise ValueError(
                "cell_mode must be native, composition_scaled, retrieval_derived, "
                f"or {DYNAMIC_CELL_POLICY_VERSION}"
            )
        if self.cell_mode != "native" and not self.native_qlip:
            raise ValueError("cell_mode other than 'native' requires native_qlip=True (no explicit scaffold)")
        if self.cell_mode == "native" and self.cell_volume_per_atom is not None:
            raise ValueError("cell_volume_per_atom is not applicable when cell_mode='native'")
        if self.native_grid_density is not None and self.native_grid_density < 1:
            raise ValueError("native_grid_density must be positive")
        if self.native_grid_density is not None and not self.native_qlip:
            raise ValueError("native_grid_density requires native_qlip=True")
        if self.database_selector not in {
            "auto", "general", "spinel", "layered",
            "rocksalt", "olivine", "ruddlesden_popper", "garnet", "nasicon", "argyrodite",
        }:
            raise ValueError(
                "database_selector must be auto, general, spinel, layered, rocksalt, "
                "olivine, ruddlesden_popper, garnet, nasicon, or argyrodite"
            )
        if self.solver_time_limit_s <= 0 or self.solver_threads <= 0:
            raise ValueError("solver_time_limit_s and solver_threads must be positive")
        if self.solver_mip_gap < 0.0:
            raise ValueError("solver_mip_gap must be non-negative")
        if self.proximity_scale <= 0.0:
            raise ValueError("proximity_scale must be positive")


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    run_id: str
    attempt_id: str
    attempt_workspace: str
    prior_incomplete_attempts: tuple[str, ...]
    request: str
    normalised_task: dict[str, Any]
    corpus_id: str
    corpus_path: str
    corpus_hash: str
    retrieval_config: dict[str, Any]
    retrieved_ids: tuple[str, ...]
    retrieval_scores: tuple[float, ...]
    spp_evidence_ids: tuple[str, ...]
    spp_evidence_count: int
    request_spp_artifact: str
    request_spp_quality: dict[str, Any]
    request_spp_run_id: str
    request_support_status: str
    regulator_spp_artifact: str
    regulator_spp_hash: str
    request_component: float
    regulator_component: float
    combined_objective: float
    scaffold_id: str
    scaffold_mode: str
    feasible_state_count: int | None
    search_space_provenance: dict[str, Any]
    solver_status: str
    solver_objective: float
    independent_objective: float
    objective_difference: float
    generated_cif_path: str
    generated_cif_hash: str
    sca_result: dict[str, Any]
    pair_components: tuple[dict[str, Any], ...]
    request_supported_pair_count: int
    regulator_fallback_pair_count: int
    unsupported_pair_count: int
    provenance_manifest: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkflowStages(Protocol):
    def normalise(self, request: str) -> dict[str, Any]: ...
    def retrieve(self, request: str, task: dict[str, Any], config: WorkflowConfig, run_root: Path) -> dict[str, Any]: ...
    def fit_request_spp(self, evidence: Any, task: dict[str, Any], config: WorkflowConfig, run_root: Path) -> dict[str, Any]: ...
    def solve(self, task: dict[str, Any], request_spp: dict[str, Any], config: WorkflowConfig, run_root: Path) -> dict[str, Any]: ...
    def evaluate(self, cif_path: Path, task: dict[str, Any]) -> dict[str, Any]: ...


class WorkflowStageError(RuntimeError):
    def __init__(self, stage: str, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.stage = stage
        self.code = code
        self.details = details or {}
        super().__init__(message)


def _explicit_site_runtime_limits(design_space: dict[str, Any]) -> dict[str, int]:
    """Return the production safety policy for explicit-site requests.

    Ordered scaffolds use a larger conservative engineering ceiling because
    their symmetry-closed sites represent a topology rather than an
    unrestricted candidate grid. Native ``mode == none`` requests do not call
    this helper and retain their existing runtime behavior.
    """

    sites = design_space.get("sites") if isinstance(design_space, dict) else None
    if not isinstance(sites, dict) or sites.get("mode") != "explicit_fractional_sites":
        raise WorkflowStageError(
            "qlip_request_validation",
            "EXPLICIT_SITE_POLICY_MODE_REQUIRED",
            "Explicit-site runtime policy requires sites.mode=explicit_fractional_sites.",
        )
    coordinates = sites.get("explicit_fractional_sites")
    if not isinstance(coordinates, list):
        raise WorkflowStageError(
            "qlip_request_validation",
            "EXPLICIT_SITE_COORDINATES_REQUIRED",
            "Explicit-site runtime policy requires an explicit_fractional_sites list.",
        )
    site_count = len(coordinates)
    ordered = bool(sites.get("ordered_orbits"))
    limit = MAX_ORDERED_SCAFFOLD_SITES if ordered else MAX_GENERIC_CANDIDATE_SITES
    representation = "ordered scaffold" if ordered else "generic explicit candidate grid"
    if site_count > limit:
        code = (
            "ORDERED_SCAFFOLD_SITE_LIMIT_EXCEEDED"
            if ordered
            else "GENERIC_CANDIDATE_SITE_LIMIT_EXCEEDED"
        )
        raise WorkflowStageError(
            "qlip_request_validation",
            code,
            f"{representation} received {site_count} candidate sites; allowed limit is {limit}.",
            details={
                "representation": representation,
                "received_site_count": site_count,
                "allowed_site_limit": limit,
            },
        )
    return {
        "max_sites": limit,
        "max_binary_vars": MAX_EXPLICIT_SITE_BINARY_VARS,
        "max_constraints": MAX_EXPLICIT_SITE_CONSTRAINTS,
    }


class ProductionWorkflowStages:
    """Adapters over supported production APIs; contains no scoring implementation."""

    _TASKS = {
        "MgO": {"formula": "MgO", "family": "rocksalt", "prototype": "rocksalt", "space_group": "Fm-3m"},
        "TiN": {"formula": "TiN", "family": "nitride", "prototype": "rocksalt", "space_group": "Fm-3m"},
        "ZrO2": {"formula": "ZrO2", "family": "fluorite", "prototype": "fluorite", "space_group": "Fm-3m"},
        "BaTiO3": {"formula": "BaTiO3", "family": "perovskite", "prototype": "perovskite", "space_group": "Pm-3m", "roles": {"A": "Ba", "B": "Ti", "X": "O"}},
        "CaTiO3": {"formula": "CaTiO3", "family": "perovskite", "prototype": "perovskite", "space_group": "Pm-3m", "roles": {"A": "Ca", "B": "Ti", "X": "O"}},
        "SrTiO3": {"formula": "SrTiO3", "family": "perovskite", "prototype": "perovskite", "space_group": "Pm-3m", "roles": {"A": "Sr", "B": "Ti", "X": "O"}},
        "CsPbBr3": {"formula": "CsPbBr3", "family": "halide perovskite", "prototype": "halide_perovskite", "space_group": "Pm-3m", "roles": {"A": "Cs", "B": "Pb", "X": "Br"}},
        "CsPbCl3": {"formula": "CsPbCl3", "family": "halide perovskite", "prototype": "halide_perovskite_cspbcl3", "space_group": "Pm-3m", "roles": {"A": "Cs", "B": "Pb", "X": "Cl"}},
        "CsPbI3": {"formula": "CsPbI3", "family": "halide perovskite", "prototype": "halide_perovskite_cspbi3", "space_group": "Pm-3m", "roles": {"A": "Cs", "B": "Pb", "X": "I"}},
        "CsSnBr3": {"formula": "CsSnBr3", "family": "halide perovskite", "prototype": "halide_perovskite_cssnbr3", "space_group": "Pm-3m", "roles": {"A": "Cs", "B": "Sn", "X": "Br"}},
        "CsSnI3": {"formula": "CsSnI3", "family": "halide perovskite", "prototype": "halide_perovskite_cssni3", "space_group": "Pm-3m", "roles": {"A": "Cs", "B": "Sn", "X": "I"}},
        "ZnFe2O4": {"formula": "ZnFe2O4", "family": "spinel", "prototype": "spinel", "space_group": "Fd-3m"},
        "MgAl2O4": {"formula": "MgAl2O4", "family": "spinel", "prototype": "spinel", "space_group": "Fd-3m"},
        "CoFe2O4": {"formula": "CoFe2O4", "family": "spinel", "prototype": "spinel", "space_group": "Fd-3m"},
        "Li6PS5Cl": {"formula": "Li6PS5Cl", "family": "argyrodite", "prototype": "argyrodite", "space_group": "F-43m"},
        "LiCoO2": {"formula": "LiCoO2", "family": "layered oxide", "prototype": "layered_oxide", "space_group": "R-3m"},
        "LiFePO4": {"formula": "LiFePO4", "family": "olivine phosphate", "prototype": "olivine_phosphate", "space_group": "Pnma"},
        "Li2FeO3": {"formula": "Li2FeO3", "family": "layered battery oxide", "prototype": "layered_oxide", "space_group": None},
        "Na3Zr2Si2PO12": {"formula": "Na3Zr2Si2PO12", "family": "NASICON/NZP", "prototype": "nasicon_na3zr2si2po12_c2_ordered", "space_group": "C2"},
        "Na3Ti2(PO4)3": {"formula": "Na3Ti2(PO4)3", "family": "NASICON/NZP", "prototype": "nasicon_na3ti2po43_r3", "space_group": "R-3"},
        "LiZr2(PO4)3": {"formula": "LiZr2(PO4)3", "family": "NASICON/NZP", "prototype": "nzp_nazr2po43_r3c", "space_group": "R-3c"},
        "Na3Ti2Si2PO12": {"formula": "Na3Ti2Si2PO12", "family": "NASICON/NZP", "prototype": "nasicon_na3ti2si2po12_cc", "space_group": "R-3", "expected_abstention": "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"},
        "Na3Hf2Si2PO12": {"formula": "Na3Hf2Si2PO12", "family": "NASICON/NZP", "prototype": "nasicon_na3hftisi2po12_p1", "space_group": "R-3", "expected_abstention": "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"},
    }

    _TASK_ALIASES = {
        "magnesium oxide": "MgO", "titanium nitride": "TiN",
        "zirconium dioxide": "ZrO2", "barium titanate": "BaTiO3",
        "calcium titanate": "CaTiO3", "strontium titanate": "SrTiO3",
        "cesium lead bromide": "CsPbBr3", "cesium lead chloride": "CsPbCl3",
        "cesium tin iodide": "CsSnI3", "zinc ferrite": "ZnFe2O4",
        "magnesium aluminate": "MgAl2O4", "cobalt ferrite": "CoFe2O4",
        "lithium thiophosphate chloride": "Li6PS5Cl",
        "lithium cobalt oxide": "LiCoO2", "lithium iron phosphate": "LiFePO4",
    }

    def normalise(self, request: str) -> dict[str, Any]:
        compact = str(request).replace(" ", "")
        if "RDX-NEG-E4-A1" in request or ("Na3Zr2Si2PO12" in compact and "R-3c" in request):
            return {"formula": "Na3Zr2Si2PO12", "family": "NASICON/NZP", "prototype": "nasicon_na3sc2po43_r3c", "space_group": "R-3c", "expected_abstention": "ORBIT_MULTIPLICITY_NOT_REPRESENTABLE"}
        for formula, task in self._TASKS.items():
            if formula in compact:
                return dict(task)
        lowered = str(request).lower()
        for alias, formula in self._TASK_ALIASES.items():
            if alias in lowered:
                return dict(self._TASKS[formula])
        raise ValueError(f"canonical smoke workflow has no structured task mapping for: {request!r}")

    def retrieve(self, request: str, task: dict[str, Any], config: WorkflowConfig, run_root: Path) -> dict[str, Any]:
        from crystal_db.retrieval import text_search

        if config.database_selector == "auto" and config.crystal_db_root is None:
            # Preserve the established adapter call shape for non-CSV callers.
            route = route_corpus(
                request,
                formula=task["formula"],
                registry_path=config.registry_path,
            )
        else:
            route = route_corpus(
                request,
                formula=task["formula"],
                registry_path=config.registry_path,
                logical_selector=config.database_selector,
                crystal_db_root=config.crystal_db_root,
            )
        export_dir = run_root / "retrieved_cifs"
        export_dir.mkdir(parents=True, exist_ok=True)
        result = text_search(
            query_text=request,
            db_path=str(route.database),
            k=config.retrieval_depth,
            embed_engine="lmstudio",
            model_name=config.embedding_model,
            model_version=config.embedding_version,
            text_engine="robocrys",
            text_view="robocrys",
            show_text_top=config.retrieval_depth,
            export_dir=str(export_dir),
            export_top=config.retrieval_depth,
            redacted=False,
            demo_export=config.retrieval_demo_export,
        )
        if result.get("status") != "ok":
            raise RuntimeError(f"Crystal-DB text_search failed: {result.get('errors')}")
        selected = []
        for rank, neighbor in enumerate(result.get("neighbors", []), start=1):
            selected.append({**neighbor, "rank": rank, "retrieval_score": float(neighbor.get("score", 0.0))})
        return {
            "corpus": {"corpus_id": route.corpus_id, "database": str(route.database), "hash": _sha256(route.database)},
            "backend": "crystal_db.retrieval.text_search",
            "config": dict(result.get("query", {})) | {"demo_export": config.retrieval_demo_export},
            "selected": selected,
        }

    def fit_request_spp(self, evidence: Any, task: dict[str, Any], config: WorkflowConfig, run_root: Path) -> dict[str, Any]:
        from spp_maker.calibration import collect_scores_for_corpus, recommend_lambda_quantile, scale_spp_root
        from spp_maker_qlip.pot_quality import audit_pot_file
        from spp_maker_qlip.required_pair_extraction import export_required_pair_spp_root

        if config.request_spp_mode == "disabled":
            from spp_maker_qlip.pot_quality import audit_pot_file
            request_run_id = config.run_id or _request_spp_run_id(evidence.bundle_hash, run_root)
            qlip_run_root = _request_spp_runtime_root(config, evidence.bundle_hash, run_root)
            root = qlip_run_root / "request_spp" / "supported_pairs"
            root.mkdir(parents=True, exist_ok=True)
            regulator = self._regulator_root(config)
            pair_results = []
            unsupported = []
            for pair in evidence.required_pairs:
                regulator_path = _pair_pot_path(regulator, pair)
                quality = audit_pot_file(regulator_path, max_cap_fraction_threshold=0.5) if regulator_path else None
                available = bool(regulator_path and quality and quality.get("pot_quality") == "usable")
                if not available:
                    unsupported.append(pair)
                pair_results.append({
                    "species_pair": pair, "request_pair_status": REQUEST_DISABLED,
                    "structures_contributing": 0, "observations": 0, "cap_fraction": None,
                    "request_quality": "disabled", "candidate_distance_support": {"minimum_A": None, "maximum_A": None},
                    "request_pot_path": None, "request_pot_hash": None, "regulator_available": available,
                    "regulator_pot_path": str(regulator_path) if regulator_path else None,
                    "regulator_pot_hash": _sha256(regulator_path) if regulator_path else None,
                    "regulator_quality": quality.get("pot_quality") if quality else "missing",
                    "guidance_mode": "REGULATOR_ONLY_REQUEST_DISABLED" if available else "UNSUPPORTED_REQUIRED_PAIR",
                })
            if unsupported:
                raise WorkflowStageError("guidance_pair_coverage", "GUIDANCE_PAIR_UNSUPPORTED", f"Required pairs lack a usable frozen regulator POT: {', '.join(unsupported)}", details={"unsupported_pairs": unsupported, "pair_results": pair_results})
            return {
                "pot_root": root, "artifact": str(root.parent), "request_spp_run_id": request_run_id,
                "request_spp_logical_id": f"request_spp_disabled:{request_run_id}:{evidence.bundle_hash}", "request_spp_hashes": {},
                "attempt_id": config.attempt_id, "evidence_hash": evidence.bundle_hash,
                "regulator_root": regulator, "regulator_id": config.regulator_id, "regulator_hash": _tree_hash(regulator),
                "quality": {"status": "REQUEST_DISABLED_REGULATOR_ONLY", "convention": config.request_spp_convention,
                            "lambda_used": None, "generation": {"request_spp_mode": "disabled", "required_pairs": list(evidence.required_pairs)},
                            "request_pair_results": pair_results, "request_supported_pair_count": 0,
                            "regulator_fallback_pair_count": len(pair_results), "unsupported_pair_count": 0,
                            "fresh_request_spp_run_id": request_run_id},
            }

        request_run_id = config.run_id or _request_spp_run_id(evidence.bundle_hash, run_root)
        qlip_run_root = _request_spp_runtime_root(config, evidence.bundle_hash, run_root)
        cif_dir = qlip_run_root / "spp_evidence"
        cif_dir.mkdir(parents=True, exist_ok=True)
        from sok_llm_orchestrator.workflow.spp_package_audit import audit_cif_hash_chain

        expected_names = {f"{item.structure_id}.cif" for item in evidence.selected}
        existing_names = {path.name for path in cif_dir.glob("*.cif")}
        unexpected = sorted(existing_names - expected_names)
        if unexpected:
            raise WorkflowStageError(
                "request_spp_input", "STALE_SPP_INPUT_CIFS",
                "SPP input directory contains CIFs not selected for this request.",
                details={"input_directory": str(cif_dir), "unexpected_cifs": unexpected},
            )
        for item in evidence.selected:
            source = Path(item.cif_path)
            (cif_dir / f"{item.structure_id}.cif").write_bytes(source.read_bytes())
        cif_chain = audit_cif_hash_chain(
            evidence=evidence, input_dir=cif_dir,
            excluded_structure_ids=config.excluded_structure_ids,
        )
        if not cif_chain["SELECTED_CORPUS_HASHES_EQUAL_SPP_INPUT_HASHES"]:
            raise WorkflowStageError(
                "request_spp_input", "SPP_INPUT_HASH_MISMATCH",
                "Selected evidence CIF hashes do not equal the files enumerated by SPP-Maker.",
                details=cif_chain,
            )
        if not cif_chain["NO_TARGET_LEAKAGE"]:
            raise WorkflowStageError(
                "request_spp_input", "TARGET_LEAKAGE_IN_SPP_INPUT",
                "A held-out target/equivalent entered the SPP input corpus.", details=cif_chain,
            )
        _write_json(Path(run_root) / "selected_spp_corpus.json", {"selected": cif_chain["selected"]})
        _write_json(Path(run_root) / "exported_cif_manifest.json", {"exported": cif_chain["selected"]})
        _write_json(Path(run_root) / "spp_input_manifest.json", cif_chain)
        _write_json(cif_dir / "spp_input_manifest.json", cif_chain)
        if config.request_spp_convention not in {"reward", "penalty"}:
            raise ValueError(f"unsupported SPP-Maker convention: {config.request_spp_convention}")
        formula = str(task["formula"])
        if config.spp_artifact_contract == "dmytro_gr_v1":
            from spp_maker.common_contract import (
                CONTRACT_ID, blend_contract_roots, build_local_supercell_artifact,
            )

            regulator = self._regulator_root(config)
            local_root = qlip_run_root / "request_spp" / "local_common_contract"
            local_metadata = build_local_supercell_artifact(
                cif_dir=cif_dir, out_root=local_root, name=f"{run_root.name}_{CONTRACT_ID}",
            )
            observations = dict(local_metadata.get("pair_observations") or {})
            required_pairs = [str(pair) for pair in evidence.required_pairs]
            pair_evidence = {
                pair: {
                    "structures_contributing": int(evidence.pair_structure_counts.get(pair, 0)),
                    "observations": int(observations.get(pair, 0)),
                }
                for pair in required_pairs
            }
            root = qlip_run_root / "request_spp" / "blended_complete_root"
            try:
                blend_manifest = blend_contract_roots(
                    local_root=local_root, regulator_root=regulator, out_root=root,
                    required_pairs=required_pairs, pair_evidence=pair_evidence,
                    name=f"{run_root.name}_pair_level_blend",
                )
            except ValueError as exc:
                marker = "neither local nor global contract artifact is valid for "
                if marker not in str(exc):
                    raise
                unsupported_pair = str(exc).split(marker, 1)[1]
                raise WorkflowStageError(
                    "guidance_pair_coverage", "GUIDANCE_PAIR_UNSUPPORTED",
                    f"Required pair lacks both a valid local common-contract POT and global fallback: {unsupported_pair}",
                    details={"unsupported_pairs": [unsupported_pair], "artifact_contract": CONTRACT_ID},
                ) from exc
            blend_by_pair = {str(row["pair"]): row for row in blend_manifest["pairs"]}
            pair_results = []
            for pair in required_pairs:
                decision = blend_by_pair[pair]
                selected_path = _pair_pot_path(root, pair)
                request_path = _pair_pot_path(local_root, pair) if decision["local_valid"] else None
                global_root = root.parent / "global_common_contract"
                regulator_path = _pair_pot_path(global_root, pair) if decision["global_valid"] else None
                evidence_present = pair_evidence[pair]["structures_contributing"] > 0
                if decision["local_valid"]:
                    request_status = REQUEST_USABLE
                    mode = "PREBLENDED_COMPLETE"
                elif evidence_present:
                    request_status = REQUEST_INSUFFICIENT
                    mode = "REGULATOR_ONLY_LOCAL_INSUFFICIENT"
                else:
                    request_status = REQUEST_MISSING
                    mode = "REGULATOR_ONLY_LOCAL_MISSING"
                pair_results.append({
                    "species_pair": pair, "request_pair_status": request_status,
                    "structures_contributing": pair_evidence[pair]["structures_contributing"],
                    "observations": pair_evidence[pair]["observations"], "cap_fraction": None,
                    "request_quality": "usable_common_contract" if decision["local_valid"] else "invalid_or_absent_common_contract",
                    "candidate_distance_support": {"minimum_A": None, "maximum_A": config.cutoff},
                    "request_pot_path": str(request_path) if request_path else None,
                    "request_pot_hash": _sha256(request_path) if request_path else None,
                    "regulator_available": bool(decision["global_valid"]),
                    "regulator_pot_path": str(regulator_path) if regulator_path else None,
                    "regulator_pot_hash": _sha256(regulator_path) if regulator_path else None,
                    "regulator_quality": "converted_to_common_contract" if decision["global_valid"] else "missing",
                    "guidance_mode": mode, "blend_decision": decision,
                    "selected_pot_path": str(selected_path) if selected_path else None,
                    "selected_pot_source": str(decision["mode"]),
                })
            request_statuses = [str(row["request_pair_status"]) for row in pair_results]
            supported_count = sum(status == REQUEST_USABLE for status in request_statuses)
            request_pot_hashes = {
                path.relative_to(root).as_posix(): _sha256(path)
                for path in sorted(root.rglob("*.POT"), key=lambda item: item.as_posix().lower())
            }
            return {
                "pot_root": root, "artifact": str(root.parent),
                "request_spp_run_id": request_run_id,
                "request_spp_logical_id": f"request_spp:{CONTRACT_ID}:{request_run_id}:{evidence.bundle_hash}",
                "request_spp_hashes": request_pot_hashes, "attempt_id": config.attempt_id,
                "evidence_hash": evidence.bundle_hash, "regulator_root": regulator,
                "regulator_id": config.regulator_id, "regulator_hash": _tree_hash(regulator),
                "blend_mode": "preblended_pair_level", "artifact_contract": CONTRACT_ID,
                "quality": {
                    "status": "PASS_COMMON_CONTRACT", "convention": "dimensionless_negative_log_gr",
                    "request_support_status": request_support_status(request_statuses),
                    "lambda_used": None, "generation": local_metadata,
                    "blend_manifest": blend_manifest, "request_pair_results": pair_results,
                    "request_supported_pair_count": supported_count,
                    "regulator_fallback_pair_count": len(pair_results) - supported_count,
                    "unsupported_pair_count": 0,
                    "fresh_request_spp_run_id": request_run_id, "spp_input_manifest": cif_chain,
                },
            }
        raw_root = qlip_run_root / "request_spp" / "unscaled_spp_root"
        generation = export_required_pair_spp_root(
            cif_dir=cif_dir, formula=formula, out_root=raw_root, name=run_root.name,
            cutoff=config.cutoff, max_cap_fraction_threshold=0.5,
        )
        quality = dict(generation.get("spp_pot_quality") or {})
        quality_by_pair = {str(item["pair"]): dict(item) for item in quality.get("pairs", [])}
        required_pairs = [str(pair) for pair in generation["required_pairs"]]
        missing_pairs = set(str(pair) for pair in generation.get("missing_pairs", []))
        missing_pairs.update(pair for pair in evidence.required_pairs if evidence.pair_structure_counts.get(pair, 0) == 0)
        request_statuses = classify_request_pair_quality(required_pairs, quality, missing_pairs)
        usable_pairs = [pair for pair in required_pairs if request_statuses[pair] == "REQUEST_USABLE"]
        scaled_all_root = qlip_run_root / "request_spp" / "scaled_all_pairs"
        recommendation = None
        if list(raw_root.rglob("*.POT")):
            stats = collect_scores_for_corpus(
                spp_root=raw_root, cif_dir=cif_dir, score_method="neighbors", r_cut=config.cutoff,
                use_bandpass=False, missing_pair_policy="max_global",
            )
            recommendation = recommend_lambda_quantile(
                stats, q=0.5, target=1.0, convention=config.request_spp_convention,
                min_lambda=0.0, max_lambda=1e9,
            )
            scale_spp_root(
                raw_root, scaled_all_root, recommendation.lambda_used, convention=config.request_spp_convention,
                source_calibration_json=None, min_lambda=0.0, max_lambda=1e9,
            )
        root = qlip_run_root / "request_spp" / "supported_pairs"
        root.mkdir(parents=True, exist_ok=True)
        for pair in usable_pairs:
            source = _pair_pot_path(scaled_all_root, pair)
            if source is None:
                raise WorkflowStageError("request_spp_quality", "REQUEST_USABLE_POT_MISSING", f"Usable request POT artifact missing for {pair}")
            destination = root / source.parent.name / source.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        regulator = self._regulator_root(config)
        pair_results: list[dict[str, Any]] = []
        unsupported: list[str] = []
        pair_stats = generation.get("pair_stats", {})
        for pair in required_pairs:
            request_quality = quality_by_pair.get(pair, {})
            request_status = request_statuses[pair]
            regulator_path = _pair_pot_path(regulator, pair)
            regulator_quality = audit_pot_file(regulator_path, max_cap_fraction_threshold=0.5) if regulator_path else None
            regulator_available = bool(regulator_path and regulator_quality and regulator_quality.get("pot_quality") == "usable")
            if not regulator_available:
                unsupported.append(pair)
            mode = guidance_mode_for_pair(request_status, regulator_available) if regulator_available else "UNSUPPORTED_REQUIRED_PAIR"
            stat = pair_stats.get(pair, {})
            pair_results.append({
                "species_pair": pair,
                "request_pair_status": request_status,
                "structures_contributing": int(evidence.pair_structure_counts.get(pair, 0)),
                "observations": int(stat.get("count", 0)),
                "cap_fraction": request_quality.get("max_cap_fraction"),
                "request_quality": request_quality.get("pot_quality", "missing"),
                "candidate_distance_support": {"minimum_A": stat.get("min_distance"), "maximum_A": stat.get("max_distance")},
                "request_pot_path": str(_pair_pot_path(root, pair)) if _pair_pot_path(root, pair) else None,
                "request_pot_hash": _sha256(_pair_pot_path(root, pair)) if _pair_pot_path(root, pair) else None,
                "regulator_available": regulator_available,
                "regulator_pot_path": str(regulator_path) if regulator_path else None,
                "regulator_pot_hash": _sha256(regulator_path) if regulator_path else None,
                "regulator_quality": regulator_quality.get("pot_quality") if regulator_quality else "missing",
                "guidance_mode": mode,
            })
        if unsupported:
            raise WorkflowStageError(
                "guidance_pair_coverage", "GUIDANCE_PAIR_UNSUPPORTED",
                f"Required pairs lack a usable frozen regulator POT: {', '.join(unsupported)}",
                details={"unsupported_pairs": unsupported, "pair_results": pair_results},
            )
        supported_count = len(usable_pairs)
        overall = request_support_status(request_statuses.values())
        request_pot_hashes = {
            path.relative_to(root).as_posix(): _sha256(path)
            for path in sorted(root.rglob("*.POT"), key=lambda item: item.as_posix().lower())
        }
        request_spp = {
            "pot_root": root,
            "artifact": str(root.parent),
            "request_spp_run_id": request_run_id,
            "request_spp_logical_id": f"request_spp:{request_run_id}:{evidence.bundle_hash}",
            "request_spp_hashes": request_pot_hashes,
            "attempt_id": config.attempt_id,
            "evidence_hash": evidence.bundle_hash,
            "regulator_root": regulator,
            "regulator_id": config.regulator_id,
            "regulator_hash": _tree_hash(regulator),
            "quality": {
                "status": overall,
                "convention": config.request_spp_convention,
                "lambda_used": recommendation.lambda_used if recommendation else None,
                "generation": generation,
                "request_pair_results": pair_results,
                "request_supported_pair_count": supported_count,
                "regulator_fallback_pair_count": len(required_pairs) - supported_count,
                "unsupported_pair_count": 0,
                "fresh_request_spp_run_id": request_run_id,
                "spp_input_manifest": cif_chain,
            },
        }
        return request_spp

    @staticmethod
    def _regulator_root(config: WorkflowConfig) -> Path:
        value = config.regulator_root or (Path(os.environ["SKILL_LOOP_REGULATOR_SPP_ROOT"]) if os.getenv("SKILL_LOOP_REGULATOR_SPP_ROOT") else _qlip_data_root(config) / "regulators" / config.regulator_id)
        root = value.resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"regulator SPP root unavailable: {root}")
        return root

    @staticmethod
    def _scaffold(task: dict[str, Any], config: WorkflowConfig | None = None) -> tuple[str, Structure, list[dict[str, Any]]]:
        if config is not None and config.scaffold_dir is not None:
            selection = load_selection(task, config.scaffold_dir)
            if selection.structure is None:
                raise RuntimeError("explicit scaffold registry returned no structure")
            return selection.scaffold_id, selection.structure, [dict(orbit) for orbit in selection.orbits]
        mode = config.scaffold_mode if config is not None else "loose"
        if task.get("family") == "NASICON/NZP":
            from qlip.scaffolds import get_scaffold, validate_scaffold
            from qlip.paper_diversity.smoke_preparation import task_orbits
            from qlip.scaffolds.occupation import preflight_ordered_occupation
            record = get_scaffold(task["prototype"])
            validation = validate_scaffold(record)
            if not validation.valid:
                raise RuntimeError(f"registered scaffold failed validation: {validation.errors}")
            structure = Structure.from_file(record.source_cif_path)
            orbits = task_orbits({"target_formula": task["formula"]}, record)
            occupation = preflight_ordered_occupation(task["formula"], len(structure), orbits)
            if task.get("expected_abstention") or not occupation.stoichiometry_representable or record.source_space_group != task["space_group"]:
                reason = task.get("expected_abstention") or occupation.rejection_reason or "TARGET_SPACE_GROUP_SCAFFOLD_MISMATCH"
                raise WorkflowStageError("representability", str(reason), f"Canonical NASICON task is not representable: {reason}", details={"task": task, "occupation": occupation.to_dict(), "scaffold_space_group": record.source_space_group})
            return record.scaffold_id, structure, orbits
        # Paper_scaffolds_september reusable family scaffold library (Dataset C):
        # spinel / layered oxide / olivine / rocksalt topology priors with
        # composition-variable cation orbits. Only engaged when a scaffold mode
        # is explicitly requested for a supported family.
        from sok_llm_orchestrator.workflow.paper_scaffolds_library import (
            build_family_scaffold,
            resolve_policy,
        )

        if str(mode) not in {"", "none"} and resolve_policy(str(task.get("family") or "")) is not None:
            library_mode = "fixed" if str(mode) in {"tight", "hard"} else "variable"
            scaffold_id, structure, orbits, _prov = build_family_scaffold(task, library_mode)
            return scaffold_id, structure, orbits
        prototype_structure = ideal_prototype_structure(task["prototype"], task["formula"])
        if prototype_structure is None:
            raise RuntimeError(f"canonical prototype scaffold unavailable for {task['formula']}")
        roles = task.get("roles") or {}
        if set(roles) != {"A", "B", "X"}:
            raise RuntimeError(f"canonical ABX3 role mapping unavailable for {task['formula']}")
        a_species, b_species, x_species = (str(roles[key]) for key in ("A", "B", "X"))
        case = VariablePerovskiteCase(
            case_id=str(task["formula"]),
            composition=str(task["formula"]),
            cation_species=(a_species, b_species),
            anion_species=x_species,
            lattice_a=float(prototype_structure.lattice.a),
        )
        structure = structure_for_assignment(case, a_species, b_species)
        orbits = []
        minimal_species = sorted(Composition(str(task["formula"])).get_el_amt_dict(), key=str.lower)
        for index, site in enumerate(structure):
            species = str(site.specie)
            if mode == "minimal":
                # Each candidate position is an independent singleton domain.
                # Exact composition and full occupancy remain enforced by QLIP;
                # no A/B/X role or multi-site orbit closure reaches the wire.
                allowed = minimal_species
            elif species == x_species:
                allowed = [x_species]
            elif species in {a_species, b_species}:
                allowed = [species] if mode == "tight" else [a_species, b_species]
            else:
                raise RuntimeError(f"scaffold species {species} is absent from explicit ABX3 roles for {task['formula']}")
            orbits.append({"orbit_id": f"site_{index:03d}", "site_indices": [index], "allowed_species": allowed, "required_occupancy": True})
        if mode == "tight":
            scaffold_id = f"canonical_{task['prototype']}_tight"
        elif mode == "loose":
            scaffold_id = "cubic_perovskite_variable_cation_v1"
        else:
            scaffold_id = "abx3_five_site_minimal_assignment_v1"
        return scaffold_id, structure, orbits

    def enumerate_feasible_assignments(
        self, task: dict[str, Any], config: WorkflowConfig,
    ) -> tuple[tuple[str, ...], ...]:
        """Exhaustively enumerate assignments admitted by the QLIP wire constraints.

        This mirrors the allocation contract before any objective is attached:
        ordered-orbit allowlists and closure, fixed/full-site requirements, and
        exact cell-scaled stoichiometry.  It is intentionally limited to fully
        occupied ABX3 scaffolds used by the scaffold-prior ablation.
        """
        if task.get("family") == "NASICON/NZP":
            raise ValueError("ABX3 scaffold assignment enumeration does not apply to NASICON")
        _, structure, orbits = self._scaffold(task, config)
        site_count = len(structure)
        if sorted(int(site) for orbit in orbits for site in orbit["site_indices"]) != list(range(site_count)):
            raise RuntimeError("ordered orbits do not exactly partition the candidate sites")
        target = Composition(_qlip_target_formula(task, site_count)).get_el_amt_dict()
        target_counts: dict[str, int] = {}
        for species, value in target.items():
            rounded = round(float(value))
            if abs(float(value) - rounded) > 1e-9:
                raise RuntimeError(f"non-integral target count for {species}: {value}")
            target_counts[str(species)] = int(rounded)
        domains: list[tuple[str, ...] | None] = [None] * site_count
        for orbit in orbits:
            if orbit.get("vacancy_allowed") or "VACANCY" in orbit.get("allowed_species", []):
                raise RuntimeError("scaffold ablation enumeration requires full occupancy")
            if not bool(orbit.get("required_occupancy", True)):
                raise RuntimeError("scaffold ablation enumeration requires every site occupied")
            fixed = orbit.get("fixed_species")
            allowed = (str(fixed),) if fixed else tuple(str(value) for value in orbit["allowed_species"])
            for index in orbit["site_indices"]:
                domains[int(index)] = allowed
        if any(domain is None for domain in domains):
            raise RuntimeError("candidate site lacks an ordered-orbit domain")
        assignments: list[tuple[str, ...]] = []
        for assignment in itertools.product(*(domain for domain in domains if domain is not None)):
            counts = {species: assignment.count(species) for species in target_counts}
            if counts != target_counts or set(assignment) - set(target_counts):
                continue
            closed = True
            for orbit in orbits:
                indices = [int(value) for value in orbit["site_indices"]]
                if not orbit.get("allow_partial_occupation", False) and len({assignment[index] for index in indices}) != 1:
                    closed = False
                    break
            if closed:
                assignments.append(tuple(assignment))
        return tuple(assignments)

    def reported_feasible_state_count(
        self, task: dict[str, Any], config: WorkflowConfig,
    ) -> int | None:
        """Return an exact cheap count where implemented, otherwise explicit unknown.

        The exhaustive counter is an ABX3 diagnostic and must not be invoked for
        registered NASICON/NZP scaffolds after a successful QLIP solve.
        """
        if config.scaffold_dir is not None:
            return load_selection(task, config.scaffold_dir).feasible_state_count
        if config.native_qlip or task.get("family") == "NASICON/NZP":
            return None
        return len(self.enumerate_feasible_assignments(task, config))

    def required_pairs(self, task: dict[str, Any], config: WorkflowConfig) -> list[str]:
        """Return the species-pair domain that the compiled periodic scaffold can score."""
        if config.native_qlip:
            return required_pairs_for_formula(str(task["formula"]))
        _, structure, orbits = self._scaffold(task, config)
        allowed_by_site = [{str(site.specie)} for site in structure]
        for orbit in orbits:
            allowed = {str(species) for species in orbit["allowed_species"]}
            for index in orbit["site_indices"]:
                allowed_by_site[int(index)] = allowed
        center_indices, point_indices, _, _ = structure.get_neighbor_list(
            r=float(config.cutoff), numerical_tol=1e-8, exclude_self=True
        )
        pairs: set[str] = set()
        for center, point in zip(center_indices, point_indices, strict=True):
            for left in allowed_by_site[int(center)]:
                for right in allowed_by_site[int(point)]:
                    pairs.add(canonical_pair(left, right))
        if not pairs:
            raise RuntimeError("compiled scaffold has no periodic pair interactions inside the SPP cutoff")
        return sorted(pairs, key=str.lower)

    def solve(self, task: dict[str, Any], request_spp: dict[str, Any], config: WorkflowConfig, run_root: Path) -> dict[str, Any]:
        from qlip.core.solve import solve

        run_root = Path(run_root)
        run_root.mkdir(parents=True, exist_ok=True)
        resolved_cell = None
        if config.native_qlip and config.cell_mode == DYNAMIC_CELL_POLICY_VERSION:
            persisted = request_spp.get("dynamic_cell")
            if isinstance(persisted, ResolvedCell):
                resolved_cell = persisted
            elif isinstance(persisted, dict):
                resolved_cell = resolved_cell_from_dict(persisted)
            else:
                raise ValueError(
                    f"{DYNAMIC_CELL_POLICY_VERSION} requires a persisted dynamic_cell payload"
                )
        elif config.native_qlip and (config.cell_mode != "native" or config.native_grid_density is not None):
            resolved_cell = resolve_native_cell(
                str(task["formula"]),
                cell_mode=config.cell_mode,
                grid_density=config.native_grid_density or NATIVE_GRID_DENSITY,
                cell_volume_per_atom=config.cell_volume_per_atom,
                evidence_vpa_records=tuple(request_spp.get("evidence_vpa_records") or ()),
            )
        selection = (
            load_selection(task, None if config.native_qlip else config.scaffold_dir, resolved_cell=resolved_cell)
            if (config.native_qlip or config.scaffold_dir is not None)
            else None
        )
        if selection is not None and selection.mode == "none":
            scaffold_id, structure, orbits = selection.scaffold_id, None, []
        else:
            scaffold_id, structure, orbits = self._scaffold(task, config)
        required_pairs = self.required_pairs(task, config)
        pair_guidance = _solver_pair_guidance(
            required_pairs,
            list(request_spp["quality"].get("request_pair_results", [])),
        )
        regulator = Path(request_spp.get("regulator_root") or self._regulator_root(config)).resolve()
        qlip_adapter = _qlip_spp_request_adapter(
            pair_guidance=pair_guidance,
            request_spp=request_spp,
            config=config,
        )
        wire_orbits = _qlip_ordered_orbits_adapter(orbits) if orbits else []
        qlip_formula = str(task["formula"]) if structure is None else _qlip_target_formula(task, len(structure))
        _validate_qlip_species_contract(
            formula=qlip_formula,
            ordered_orbits=wire_orbits,
            required_pairs=required_pairs,
            guidance=qlip_adapter["guidance"],
        )
        if selection is not None and selection.mode == "none":
            design_space = {"template": selection.native_template, "sites": selection.native_sites}
            constraints = list(selection.native_constraints)
            for constraint in constraints:
                if constraint.get("id") == "proximity.atomic_radii":
                    constraint["params"] = dict(constraint.get("params") or {}) | {
                        "scale": float(config.proximity_scale)
                    }
        else:
            assert structure is not None
            cell = structure.lattice
            design_space = {"template": {"name": scaffold_id, "lattice": {"a": cell.a, "b": cell.b, "c": cell.c, "alpha": cell.alpha, "beta": cell.beta, "gamma": cell.gamma, "units": "angstrom"}}, "sites": {"mode": "explicit_fractional_sites", "explicit_fractional_sites": structure.frac_coords.tolist(), "ordered_orbits": wire_orbits}}
            constraints = []
        request = {
            "version": "1.0",
            "problem": {"chemistry": {"formula": qlip_formula}, "design_space": design_space, "objective": {"type": "spp_energy"}},
            "constraints": constraints,
            "guidance": qlip_adapter["guidance"],
            "guidance_mode": "weighted_sum",
            "solver": {
                "name": "gurobi",
                "time_limit_s": int(config.solver_time_limit_s),
                "mip_gap": float(config.solver_mip_gap),
                "threads": int(config.solver_threads),
                "seed": int(config.solver_seed),
                "parameters": {"NonConvex": 2},
            },
            "artifacts": {"return_cif": True},
            "context": qlip_adapter["context"],
        }
        if selection is None or selection.mode != "none":
            request["runtime"] = _explicit_site_runtime_limits(design_space)
        with _qlip_pot_authorization(config) as allowed_roots:
            result = solve(request)
        # FEASIBLE_TIME_LIMIT means QLIP's Gurobi solve hit its time budget but
        # still decoded a real, feasible incumbent (SolCount>=1) into a CIF --
        # it is never treated as equivalent to OPTIMAL/FEASIBLE (both of which
        # carry a solver-proved status); result.status/solved["status"] keeps
        # propagating the true, distinguishable label downstream unchanged.
        if result.status not in {"OPTIMAL", "FEASIBLE", "FEASIBLE_TIME_LIMIT"} or not result.outputs.cif:
            raise WorkflowStageError(
                "solve", f"QLIP_{result.status}",
                f"QLIP/IP-CSP did not emit a candidate: {result.status}: {[error.message for error in result.errors]}",
                details={
                    "qlip_status": result.status,
                    "qlip_errors": [error.message for error in result.errors],
                    "search_space": (selection.provenance() if selection is not None else {}),
                    "qlip_diagnostics": result.certificates.get("diagnostics") if result.certificates else None,
                },
            )
        cif_path = run_root / "generated.cif"
        cif_path.write_text(result.outputs.cif, encoding="latin-1")
        generated = Structure.from_file(cif_path)
        pairs = [tuple(pair.split("-", 1)) for pair in required_pairs]
        if request_spp.get("blend_mode") == "preblended_pair_level":
            from qlip.interactions.spp import SPPCollection

            request_collection = SPPCollection(Path(request_spp["pot_root"]), cutoff=config.cutoff, missing_pair_policy="block")
            request_collection.load(pairs)
            regulator_collection = None
            diagnostic_regulator_weight = 0.0
        else:
            request_collection, regulator_collection, _ = compile_spp_components(request_pot_root=Path(request_spp["pot_root"]), regulator_pot_root=regulator, pairs=pairs, cutoff=config.cutoff, regulator_weight=config.regulator_coefficient, allow_request_fallback=True)
            diagnostic_regulator_weight = config.regulator_coefficient
        atoms = generated.to_ase_atoms()
        statuses = pair_guidance["request_statuses"]
        components = score_spp_components(symbols=atoms.get_chemical_symbols(), positions=atoms.positions, cell=atoms.cell.array, request=request_collection, regulator=regulator_collection, regulator_weight=diagnostic_regulator_weight, request_guidance_weight=config.outer_objective_scale * config.request_coefficient, pairs=pairs, request_pair_statuses=statuses)
        solver_objective = float(result.summary.objective_value)
        feasible_state_count = selection.feasible_state_count if selection is not None else self.reported_feasible_state_count(task, config)
        search_space = selection.provenance() if selection is not None else {
            "scaffold_mode": config.scaffold_mode, "scaffold_dir": "", "scaffold_id": scaffold_id,
            "scaffold_hash": "", "candidate_site_count": len(structure),
            "symmetry_orbit_count": len(orbits),
            "species_fixed_orbit_count": sum(bool(orbit.get("fixed_species")) for orbit in orbits),
            "variable_orbit_count": sum(not bool(orbit.get("fixed_species")) for orbit in orbits),
            "feasible_state_count": feasible_state_count,
        }
        return {
            "scaffold_id": scaffold_id, "scaffold_mode": search_space["scaffold_mode"],
            "feasible_state_count": feasible_state_count, "search_space": search_space,
            "status": result.status, "solver_objective": solver_objective,
            "solver_summary": result.summary.to_dict(),
            "solver_diagnostics": result.certificates.get("diagnostics", {}) if result.certificates else {},
            "components": components, "cif_path": cif_path, "regulator_root": regulator,
            "regulator_hash": request_spp.get("regulator_hash") or _tree_hash(regulator),
            "qlip_allowed_roots": [str(root) for root in allowed_roots],
            "pot_authorization_status": "PASS", "qlip_adapter": qlip_adapter["diagnostics"],
            "difference": abs(solver_objective - components.solver_objective),
        }

    def evaluate(self, cif_path: Path, task: dict[str, Any]) -> dict[str, Any]:
        from sca.pipelines import evaluate_one_cif
        from sca.evaluators.topology import family_topology_metrics

        record, structure = evaluate_one_cif(cif_path, target_formula=task["formula"], target_space_group=task["space_group"], method="canonical_workflow", run_alignn=False)
        result = record.model_dump(mode="json")
        policies = {
            "rocksalt": "ROCKSALT",
            "nitride": "ROCKSALT",
            "fluorite": "FLUORITE",
            "fluorite or anti-fluorite": "GENERIC_SCAFFOLD_ONLY",
            "cscl": "GENERIC_SCAFFOLD_ONLY",
            "zinc blende": "GENERIC_SCAFFOLD_ONLY",
            "NASICON/NZP": "NASICON_ORDERED",
            "perovskite": "PEROVSKITE_3D",
            "halide perovskite": "HALIDE_PEROVSKITE_3D",
            "layered": "LAYERED_OXIDE",
            "layered battery oxide": "LAYERED_OXIDE",
            "spinel": "SPINEL",
            "spinel oxide": "SPINEL",
            "argyrodite": "ARGYRODITE_ORDERED",
            "olivine phosphate": "OLIVINE",
        }
        policy = policies.get(str(task.get("family")), "GENERIC_SCAFFOLD_ONLY")
        if structure is not None:
            topology, details = family_topology_metrics(structure, policy)
            result.update({
                "topology_status": topology["topology_status"],
                "topology_policy": policy,
                "topology_checks": topology.get("topology_checks", {}),
                "topology_warnings": topology.get("topology_warnings", []),
                "topology_backend": "sca.evaluators.topology.family_topology_metrics (pymatgen CrystalNN)",
                "topology_details": details,
            })
        return result


def _git_commit(path: Path) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


def _containing_repo_root(path: Path) -> Path:
    candidate = Path(path).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for current in (candidate, *candidate.parents):
        if (current / ".git").exists():
            return current
    return candidate


def _imported_component_root(module_name: str) -> Path | None:
    try:
        module = __import__(module_name)
        module_file = getattr(module, "__file__", None)
        return _containing_repo_root(Path(module_file)) if module_file else None
    except Exception:
        return None


def _write_trace(config: WorkflowConfig, payload: dict[str, Any], attempt_workspace: Path | None = None) -> None:
    paths: list[Path] = []
    if attempt_workspace is not None:
        paths.append(attempt_workspace / "workflow_trace.json")
    if config.trace_path is not None:
        configured = Path(config.trace_path).resolve()
        if configured not in paths:
            paths.append(configured)
    for path in paths:
        _write_json(path, payload)


def run_csp_workflow(request: str, config: WorkflowConfig) -> WorkflowResult:
    """Run all canonical stages once; persist completed upstream state on failure."""
    attempt = _prepare_execution_attempt(config, request)
    config = replace(config, run_id=attempt.run_id, attempt_id=attempt.attempt_id)
    stages = config.stages or ProductionWorkflowStages()
    trace: dict[str, Any] = {
        "schema_version": "canonical_csp_workflow_trace.v1", "workflow_status": "RUNNING",
        "run_id": attempt.run_id, "attempt_id": attempt.attempt_id,
        "attempt_workspace": str(attempt.workspace),
        "prior_incomplete_attempts": list(attempt.prior_incomplete_attempts),
        "request": request, "failure_stage": None, "failure_code": None, "failure_message": None,
        "regulator_status": "NOT_REACHED", "solver_status": "NOT_REACHED",
        "CIF_generated": False, "SCA_status": "NOT_REACHED",
    }
    _update_execution_attempt(attempt, "RUNNING")
    _write_trace(config, trace, attempt.workspace)
    stage = "normalise"
    try:
        task = stages.normalise(request)
        trace["normalised_task"] = task
        run_root = attempt.workspace
        stage = "retrieval"
        retrieval = stages.retrieve(request, task, config, run_root)
        trace.update({
            "corpus_id": retrieval["corpus"]["corpus_id"], "corpus_path": retrieval["corpus"]["database"],
            "corpus_hash": retrieval["corpus"]["hash"], "retrieval_backend": retrieval["backend"],
            "retrieval_config": retrieval["config"], "retrieval_count": len(retrieval["selected"]),
            "retrieved_ids": [str(item["structure_id"]) for item in retrieval["selected"]],
        })
        if hasattr(stages, "required_pairs"):
            required_pairs = stages.required_pairs(task, config)
            required_pair_source = "native_formula_pair_domain" if config.native_qlip else "compiled_periodic_scaffold_domain"
        else:
            required_pairs = required_pairs_for_formula(str(task["formula"]))
            required_pair_source = "stage_adapter_formula_fallback"
        trace["required_pairs"] = required_pairs
        trace["required_pair_source"] = required_pair_source
        stage = "evidence_assembly"
        evidence = assemble_spp_evidence(
            retrieval=retrieval,
            required_pairs=required_pairs,
            excluded_structure_ids=config.excluded_structure_ids,
            max_ranked_structures=config.retrieval_depth,
            allow_partial_pair_coverage=True,
        )
        trace.update({"SPP_evidence_count": len(evidence.selected), "SPP_evidence_ids": [item.structure_id for item in evidence.selected], "evidence_bundle": evidence.to_dict()})
        _update_execution_attempt(
            attempt,
            "RUNNING",
            evidence_ids=[item.structure_id for item in evidence.selected],
            evidence_hash=evidence.bundle_hash,
        )
        stage = "request_spp_fit"
        request_spp = stages.fit_request_spp(evidence, task, config, run_root)
        trace.update({"request_spp_status": request_spp["quality"].get("status", "PASS"), "request_spp_artifact": str(request_spp["artifact"]), "fresh_request_spp_run_id": request_spp.get("request_spp_run_id"), "request_spp_logical_id": request_spp.get("request_spp_logical_id"), "request_spp_path": str(request_spp["artifact"]), "request_spp_root": str(request_spp["pot_root"]), "request_spp_hashes": request_spp.get("request_spp_hashes", {}), "regulator_id": request_spp.get("regulator_id"), "regulator_path": str(request_spp.get("regulator_root")), "regulator_root": str(request_spp.get("regulator_root")), "regulator_hash": request_spp.get("regulator_hash"), "request_spp_quality": request_spp["quality"], "request_pair_results": request_spp["quality"].get("request_pair_results", []), "guidance_modes": {row["species_pair"]: row["guidance_mode"] for row in request_spp["quality"].get("request_pair_results", [])}, "request_supported_pair_count": request_spp["quality"].get("request_supported_pair_count", 0), "regulator_fallback_pair_count": request_spp["quality"].get("regulator_fallback_pair_count", 0), "unsupported_pair_count": request_spp["quality"].get("unsupported_pair_count", 0), "request_spp_convention": config.request_spp_convention})
        if config.native_qlip and config.cell_mode == "retrieval_derived":
            # Reuse the SAME leakage-safe evidence cohort already assembled for
            # request-SPP fitting -- no second, hidden retrieval for cell sizing.
            request_spp["evidence_vpa_records"] = evidence_vpa_records(evidence.selected)
            trace["cell_evidence_vpa_records"] = request_spp["evidence_vpa_records"]
        elif config.native_qlip and config.cell_mode == DYNAMIC_CELL_POLICY_VERSION:
            dynamic_cell, dynamic_provenance = resolve_dynamic_cell(
                str(task["formula"]),
                evidence.selected,
                grid_density=config.native_grid_density or NATIVE_GRID_DENSITY,
                proximity_scale=config.proximity_scale,
            )
            request_spp["dynamic_cell"] = dynamic_cell.to_dict()
            trace["dynamic_cell_provenance"] = dynamic_provenance
        stage = "solve"
        solved = stages.solve(task, request_spp, config, run_root)
        trace.update({"regulator_status": "LOADED_CACHED", "regulator_artifact": str(solved["regulator_root"]), "regulator_hash": solved["regulator_hash"], "qlip_allowed_roots": solved["qlip_allowed_roots"], "pot_authorization_status": solved["pot_authorization_status"], "qlip_adapter": solved.get("qlip_adapter", {}), "search_space_provenance": solved.get("search_space", {}), "solver_status": solved["status"]})
        cif_path = Path(solved["cif_path"]).resolve()
        if not cif_path.is_file():
            raise WorkflowStageError("cif_export", "CIF_MISSING", "solver reported success without a generated CIF")
        components = solved["components"]
        objective_difference = float(solved["difference"])
        trace.update({
            "solver_objective": float(solved["solver_objective"]),
            "independent_objective": float(components.solver_objective),
            "objective_difference": objective_difference,
            "objective_parity": "PASS" if objective_difference < 1e-6 else "FAIL",
            "request_component": float(components.request_spp_score),
            "regulator_component": float(components.regulator_spp_score),
            "combined_objective": float(components.solver_objective),
            "pair_components": list(getattr(components, "pair_components", ())),
            "objective_parity_difference": objective_difference,
            "CIF_generated": True,
            "CIF_path": str(cif_path),
            "CIF_hash": _sha256(cif_path),
        })
        _write_trace(config, trace, attempt.workspace)
        stage = "sca"
        sca = stages.evaluate(cif_path, task)
        trace["SCA_status"] = "PASS" if sca.get("parse_ok") else "FAIL"
    except Exception as exc:
        failure_stage = exc.stage if isinstance(exc, WorkflowStageError) else stage
        failure_code = exc.code if isinstance(exc, WorkflowStageError) else type(exc).__name__
        attempt_status = "FAILED_CONTROLLED" if isinstance(exc, WorkflowStageError) else "FAILED_SOFTWARE"
        trace.update({
            "workflow_status": "FAILED_CONTROLLED",
            "execution_attempt_status": attempt_status,
            "failure_stage": failure_stage,
            "failure_code": failure_code,
            "failure_message": str(exc),
        })
        if isinstance(exc, WorkflowStageError):
            trace["failure_details"] = exc.details
            generation = exc.details.get("generation", {})
            trace.update({"request_spp_status": "FAILED_QUALITY", "request_spp_artifact": exc.details.get("artifact"), "request_spp_quality": generation.get("spp_pot_quality", {}), "request_spp_convention": exc.details.get("convention")})
        _write_trace(config, trace, attempt.workspace)
        _update_execution_attempt(
            attempt,
            attempt_status,
            failure_stage=failure_stage,
            failure_code=failure_code,
            failure_message=str(exc),
            evidence_hash=trace.get("evidence_bundle", {}).get("bundle_hash"),
        )
        raise
    selected = retrieval["selected"]
    provenance = {
        "schema_version": "canonical_csp_workflow_provenance.v1",
        "api": "sok_llm_orchestrator.workflow.runner.run_csp_workflow",
        "stage_order": ["normalise", "route_and_retrieve", "assemble_evidence", "fit_request_spp", "load_regulator_and_solve", "independent_objective", "export_cif", "sca"],
        "sca_post_generation": True,
        "retrieval_backend": retrieval["backend"],
        "formula": "10.0 * (request_spp_score + 2.0 * regulator_spp_score)",
        "repositories": {
            "Skill-Loop-CSP": _git_commit(Path(__file__).resolve().parents[3]),
            "Crystal-DB": _git_commit(
                config.crystal_db_root
                or _containing_repo_root(Path(retrieval["corpus"]["database"]))
            ),
            "SPP-Maker-QLIP": _git_commit(
                _imported_component_root("spp_maker") or Path(request_spp["artifact"])
            ),
            "qlip": _git_commit(_qlip_repo_root()),
            "Structured_Crystal_Analyser": _git_commit(
                _imported_component_root("sca") or Path.cwd()
            ),
        },
    }
    result = WorkflowResult(
        run_id=attempt.run_id, attempt_id=attempt.attempt_id,
        attempt_workspace=str(attempt.workspace), prior_incomplete_attempts=attempt.prior_incomplete_attempts,
        request=request, normalised_task=task, corpus_id=retrieval["corpus"]["corpus_id"], corpus_path=retrieval["corpus"]["database"], corpus_hash=retrieval["corpus"]["hash"], retrieval_config=retrieval["config"],
        retrieved_ids=tuple(str(item["structure_id"]) for item in selected), retrieval_scores=tuple(float(item.get("score", item.get("retrieval_score", 0.0))) for item in selected),
        spp_evidence_ids=tuple(item.structure_id for item in evidence.selected), spp_evidence_count=len(evidence.selected), request_spp_artifact=str(request_spp["artifact"]), request_spp_quality=dict(request_spp["quality"]), request_spp_run_id=str(request_spp.get("request_spp_run_id", "stage-adapter-unspecified")), request_support_status=str(request_spp["quality"].get("status", "PASS")),
        regulator_spp_artifact=str(solved["regulator_root"]), regulator_spp_hash=str(solved["regulator_hash"]), request_component=float(components.request_spp_score), regulator_component=float(components.regulator_spp_score), combined_objective=float(components.solver_objective),
        scaffold_id=str(solved["scaffold_id"]), scaffold_mode=str(solved.get("scaffold_mode", config.scaffold_mode)), feasible_state_count=(None if solved.get("feasible_state_count") is None else int(solved["feasible_state_count"])), search_space_provenance=dict(solved.get("search_space", {})), solver_status=str(solved["status"]), solver_objective=float(solved["solver_objective"]), independent_objective=float(components.solver_objective), objective_difference=float(solved["difference"]),
        generated_cif_path=str(cif_path), generated_cif_hash=_sha256(cif_path), sca_result=sca, pair_components=tuple(getattr(components, "pair_components", ())), request_supported_pair_count=int(request_spp["quality"].get("request_supported_pair_count", 0)), regulator_fallback_pair_count=int(request_spp["quality"].get("regulator_fallback_pair_count", 0)), unsupported_pair_count=int(request_spp["quality"].get("unsupported_pair_count", 0)), provenance_manifest=provenance,
    )
    _write_trace(config, {**trace, **result.to_dict(), "workflow_status": "PASS"}, attempt.workspace)
    _update_execution_attempt(
        attempt,
        "COMPLETED",
        completed_at=datetime.now(timezone.utc).isoformat(),
        evidence_ids=list(result.spp_evidence_ids),
        evidence_hash=evidence.bundle_hash,
        request_spp_hash=_tree_hash(Path(request_spp["pot_root"])),
        request_spp_pot_hashes=request_spp.get("request_spp_hashes", {}),
        generated_cif_hash=result.generated_cif_hash,
    )
    return result


__all__ = ["ProductionWorkflowStages", "WorkflowConfig", "WorkflowResult", "WorkflowStageError", "WorkflowStages", "run_csp_workflow"]
