"""Strict held-out SPP-only benchmark orchestration for oxide families.

This module blocks QLIP unless every required pair resolves to a finite usable
request POT and/or an exact finite usable POT in the frozen global regulator.
Local-only coverage is retained as a diagnostic and never replaced by a fake
neutral/zero missing-pair fallback.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import shutil
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.orchestrator.logging import sha256_text
from sok_llm_orchestrator.workflow.evidence import SPPEvidenceBundle, assemble_spp_evidence
from sok_llm_orchestrator.workflow.pair_aware_retrieval import (
    actual_pair_structure_counts,
    append_augmentation_to_retrieval,
    build_family_pair_inventory,
    select_pair_augmentation,
)
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
)
from sok_llm_orchestrator.workflow.spp_package_audit import (
    assert_family_database_provenance,
    audit_spp_package,
)


RESULT_COLUMNS = (
    "experiment_id", "family", "target_mpid", "formula", "target_spacegroup",
    "target_atom_count", "retrieval_k", "retrieval_top1_similarity", "retrieval_mean_topk",
    "spp_corpus_count", "pair_coverage", "qlip_status", "qlip_runtime", "qlip_objective",
    "candidate_generated", "candidate_valid", "sca_status", "minimum_distance", "density",
    "spp_score", "spp_percentile", "structure_match", "structure_match_rms",
    "local_environment_score", "primary_mlip_energy", "relaxed", "final_classification",
    "NO_TARGET_LEAKAGE", "PAIR_COVERAGE_COMPLETE", "SPP_ARTIFACT_VALID", "SCAFFOLD_USED",
    "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION", "failure_message", "run_directory",
)


_QLIP_CANDIDATE_STATUSES = frozenset({"OPTIMAL", "FEASIBLE", "FEASIBLE_TIME_LIMIT"})
_QLIP_TERMINAL_CLASSIFICATIONS = {
    "INFEASIBLE": "FAILED_QLIP_INFEASIBLE",
    "TIME_LIMIT_NO_SOLUTION": "FAILED_QLIP_TIMEOUT",
}


def _qlip_terminal_classification(status: str, *, candidate_present: bool) -> str | None:
    """Map QLIP's structured status without conflating it with benchmark success."""
    normalized = str(status).strip().upper()
    if candidate_present and normalized in _QLIP_CANDIDATE_STATUSES:
        return None
    return _QLIP_TERMINAL_CLASSIFICATIONS.get(normalized, "FAILED_OTHER")


def _classify_target_exception(row: dict[str, Any], exc: Exception) -> None:
    """Apply deterministic target taxonomy while preserving structured QLIP status."""
    if isinstance(exc, WorkflowStageError) and exc.stage == "solve":
        qlip_status = str(exc.details.get("qlip_status") or "").strip().upper()
        if qlip_status:
            row["qlip_status"] = qlip_status
            row["final_classification"] = _qlip_terminal_classification(
                qlip_status, candidate_present=False,
            ) or "FAILED_OTHER"
            return
    if row["final_classification"] == "FAILED_OTHER" and row["retrieval_k"] == 0:
        row["final_classification"] = "FAILED_RETRIEVAL"
    elif row["final_classification"] == "FAILED_OTHER" and not row["SPP_ARTIFACT_VALID"]:
        row["final_classification"] = "FAILED_SPP_BUILD"


@dataclass(frozen=True, slots=True)
class SPPOnlyBenchmarkPolicy:
    candidate_retrieval_depth: int = 50
    spp_corpus_size: int = 30
    maximum_corpus_size: int = 60
    quality_augmentation_batch_size: int = 5
    native_grid_density: int = 4
    cutoff: float = 11.0
    embedding_model: str = "text-embedding-bge-m3"
    embedding_version: str = "lmstudio_v1"
    cell_mode: str = "composition_scaled"
    spp_artifact_contract: str = "dmytro_gr_v1"

    def __post_init__(self) -> None:
        if self.candidate_retrieval_depth < self.spp_corpus_size:
            raise ValueError("candidate retrieval depth must be at least the SPP corpus size")
        if self.spp_corpus_size < 1:
            raise ValueError("SPP corpus size must be positive")
        if self.maximum_corpus_size < self.spp_corpus_size:
            raise ValueError("maximum corpus size must be at least the semantic SPP corpus size")
        if self.quality_augmentation_batch_size < 1:
            raise ValueError("quality augmentation batch size must be positive")
        if self.native_grid_density < 1:
            raise ValueError("native grid density must be positive")
        if self.spp_artifact_contract != "dmytro_gr_v1":
            raise ValueError("the frozen SPP-only benchmark requires dmytro_gr_v1")


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    names = list(fieldnames)
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name) for name in names})
    temporary.replace(path)


def _sha256_normalized_text(path: Path) -> str:
    """Hash decoded text using the frozen dataset's newline-normalized contract."""
    return sha256_text(path.read_text(encoding="utf-8"))


def leakage_safe_neighbourhood(
    retrieval: dict[str, Any], *, excluded_structure_ids: Iterable[str], limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Suppress held-out IDs before selecting the fixed SPP neighbourhood."""
    excluded = {str(value) for value in excluded_structure_ids}
    audit: list[dict[str, Any]] = []
    eligible: list[dict[str, Any]] = []
    for item in retrieval.get("selected", []):
        structure_id = str(item.get("structure_id", ""))
        if structure_id in excluded:
            audit.append({"structure_id": structure_id, "decision": "excluded", "reason": "frozen_target_or_equivalent"})
            continue
        if len(eligible) >= int(limit):
            audit.append({"structure_id": structure_id, "decision": "not_selected", "reason": "fixed_spp_corpus_limit"})
            continue
        eligible.append(dict(item))
        audit.append({"structure_id": structure_id, "decision": "selected", "reason": "ranked_non_target_analogue"})
    filtered = dict(retrieval)
    filtered["selected"] = eligible
    return filtered, audit


def strict_pair_preflight(evidence: SPPEvidenceBundle, excluded_structure_ids: Iterable[str]) -> dict[str, Any]:
    excluded = {str(value) for value in excluded_structure_ids}
    selected = {item.structure_id for item in evidence.selected}
    missing = [pair for pair, count in evidence.pair_structure_counts.items() if int(count) < 1]
    return {
        "SPP_CORPUS_VALID": bool(evidence.selected),
        "PAIR_COVERAGE_COMPLETE": not missing,
        "NO_TARGET_LEAKAGE": not bool(excluded & selected),
        "missing_pairs": missing,
        "selected_excluded_ids": sorted(excluded & selected),
    }


def normalize_pair_for_match(pair: str) -> tuple[str, str]:
    """Return a case/order-insensitive key without rewriting element symbols."""
    parts = [part.strip() for part in str(pair).split("-")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid species-pair identifier: {pair!r}")
    return tuple(sorted((parts[0].casefold(), parts[1].casefold())))


def strict_spp_artifact_preflight(request_spp: dict[str, Any], required_pairs: Iterable[str]) -> dict[str, Any]:
    from spp_maker_qlip.pot_quality import audit_pot_root

    required = [str(pair) for pair in required_pairs]
    required_by_key = {normalize_pair_for_match(pair): pair for pair in required}
    result_by_key = {
        normalize_pair_for_match(str(row.get("species_pair"))): row
        for row in request_spp.get("quality", {}).get("request_pair_results", [])
    }
    missing_result_rows = [pair for key, pair in required_by_key.items() if key not in result_by_key]
    nonempty = not missing_result_rows and all(
        int(result_by_key[key].get("observations", 0)) > 0 for key in required_by_key
    )
    all_request_usable = not missing_result_rows and all(
        result_by_key[key].get("request_pair_status") == "REQUEST_USABLE" for key in required_by_key
    )
    raw_audit = audit_pot_root(
        Path(request_spp["pot_root"]), required_pairs=None, max_cap_fraction_threshold=0.5,
    )
    audited_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw_audit.get("pairs", []):
        audited_by_key.setdefault(normalize_pair_for_match(str(row["pair"])), []).append(row)
    matched_rows = [rows[0] for key in required_by_key if (rows := audited_by_key.get(key))]
    missing_artifact_pairs = [pair for key, pair in required_by_key.items() if key not in audited_by_key]
    ambiguous_artifact_pairs = [
        required_by_key[key] for key in required_by_key if len(audited_by_key.get(key, [])) > 1
    ]
    unusable_artifact_pairs = [
        required_by_key[key]
        for key in required_by_key
        if key in audited_by_key and audited_by_key[key][0].get("pot_quality") != "usable"
    ]
    finite = not missing_artifact_pairs and not ambiguous_artifact_pairs and all(
        row.get("raw_point_count", 0) > 0
        and all(math.isfinite(float(row[key])) for key in ("x_min", "x_max", "y_min", "y_max"))
        for row in matched_rows
    )
    artifact_usable = not missing_artifact_pairs and not ambiguous_artifact_pairs and not unusable_artifact_pairs
    audit = {
        **raw_audit,
        "required_pairs": required,
        "matched_artifact_pairs": [str(row["pair"]) for row in matched_rows],
        "missing_pairs": missing_artifact_pairs,
        "ambiguous_pairs": ambiguous_artifact_pairs,
        "unusable_pairs": unusable_artifact_pairs,
        "spp_pot_quality_status": "usable" if artifact_usable else "missing_or_unusable",
    }
    valid = bool(all_request_usable and nonempty and finite and artifact_usable)
    return {
        "FINITE_SPP_VALUES": finite,
        "NONEMPTY_DISTANCE_COUNTS": nonempty,
        "SPP_ARTIFACT_VALID": valid,
        "ALL_REQUEST_PAIRS_USABLE": all_request_usable,
        "missing_request_result_rows": missing_result_rows,
        "pot_audit": audit,
    }


def _prompt(target: dict[str, Any]) -> str:
    label = "layered battery oxide" if target["family"] == "layered" else "spinel oxide"
    return f"Generate a plausible {label} crystal structure for {target['formula']}."


def _task(target: dict[str, Any]) -> dict[str, Any]:
    family = "layered battery oxide" if target["family"] == "layered" else "spinel oxide"
    return {"formula": str(target["formula"]), "family": family, "prototype": family, "space_group": None}


def _dataset_directory(crystal_root: Path, family: str) -> Path:
    dataset = "MP_LAYERED_BATTERY_OXIDES_V1" if family == "layered" else "MP_SPINEL_OXIDES_V1"
    return crystal_root / "artifacts" / "mp_oxide_families_v1" / dataset


def _structure_ids_by_candidate_key(dataset_dir: Path) -> dict[str, str]:
    payload = json.loads((dataset_dir / "accepted.json").read_text(encoding="utf-8"))
    rows = payload.get("rows", payload) if isinstance(payload, dict) else payload
    return {str(row["candidate_key"]): str(row["structure_id"]) for row in rows}


def _retrieval_artifacts(run_dir: Path, request: str, raw: dict[str, Any], filtered: dict[str, Any], audit: list[dict[str, Any]]) -> None:
    root = run_dir / "retrieval"
    _write_json(root / "query.json", {"query_text": request, "candidate_k": len(raw.get("selected", []))})
    _write_json(root / "results.json", _jsonable(filtered))
    _write_json(root / "exclusions.json", audit)
    rows = [
        {
            "rank": item.get("rank"), "structure_id": item.get("structure_id"),
            "score": item.get("score", item.get("retrieval_score")), "formula": item.get("formula", ""),
            "cif_path": (item.get("cif_export") or {}).get("path", ""),
        }
        for item in filtered.get("selected", [])
    ]
    _write_csv(root / "results.csv", ("rank", "structure_id", "score", "formula", "cif_path"), rows)


def _mechanical_checks(path: Path, formula: str) -> tuple[dict[str, Any], Structure | None]:
    checks: dict[str, Any] = {"CIF_created": path.is_file()}
    if not path.is_file():
        return checks | {"CIF_parses": False}, None
    try:
        structure = Structure.from_file(path)
    except Exception as exc:  # noqa: BLE001 - persisted benchmark failure evidence
        return checks | {"CIF_parses": False, "parse_error": str(exc)}, None
    distances = np.asarray(structure.distance_matrix, dtype=float)
    positive = distances[distances > 1e-8]
    minimum = float(np.min(positive)) if positive.size else 0.0
    exact = structure.composition.reduced_composition == Composition(formula).reduced_composition
    checks.update({
        "CIF_parses": True,
        "exact_requested_composition": bool(exact),
        "finite_coordinates": bool(np.isfinite(structure.cart_coords).all()),
        "finite_lattice": bool(np.isfinite(structure.lattice.matrix).all() and structure.volume > 0),
        "unique_occupied_sites": bool(minimum > 1e-6),
        "minimum_distance": minimum,
        "density": float(structure.density),
    })
    checks["candidate_valid"] = all(bool(checks[key]) for key in ("CIF_parses", "exact_requested_composition", "finite_coordinates", "finite_lattice", "unique_occupied_sites"))
    return checks, structure


def _post_generation_reference(
    *, crystal_root: Path, target: dict[str, Any], generated: Structure | None, run_dir: Path,
) -> dict[str, Any]:
    target_path = crystal_root / str(target["target_cif_path"])
    if not target_path.is_file():
        return {"reference_available": False, "reference_error": f"missing target CIF: {target_path}"}
    reference = Structure.from_file(target_path)
    reference_symmetry = SpacegroupAnalyzer(reference, symprec=0.01, angle_tolerance=5.0)
    target_spacegroup = reference_symmetry.get_space_group_symbol()
    target_crystal_system = reference_symmetry.get_crystal_system()
    heldout = run_dir / "heldout_reference" / "target.cif"
    heldout.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target_path, heldout)
    result: dict[str, Any] = {
        "reference_available": True,
        "hash_contract": "sha256_text(path.read_text(encoding='utf-8'))",
        "target_spacegroup": target_spacegroup,
        "target_crystal_system": target_crystal_system,
        "target_atom_count": len(reference),
        "target_cif_sha256_verified": (
            _sha256_normalized_text(target_path) == str(target["target_cif_sha256"])
        ),
        "structure_match": False,
        "structure_match_rms": None,
        "target_lattice": {
            "a": float(reference.lattice.a), "b": float(reference.lattice.b),
            "c": float(reference.lattice.c), "alpha": float(reference.lattice.alpha),
            "beta": float(reference.lattice.beta), "gamma": float(reference.lattice.gamma),
        },
        "target_volume": float(reference.volume),
        "target_volume_per_atom": float(reference.volume / len(reference)),
    }
    if generated is None:
        return result
    generated_symmetry = SpacegroupAnalyzer(generated, symprec=0.01, angle_tolerance=5.0)
    generated_spacegroup = generated_symmetry.get_space_group_symbol()
    generated_crystal_system = generated_symmetry.get_crystal_system()
    target_volume_per_atom = float(reference.volume / len(reference))
    generated_volume_per_atom = float(generated.volume / len(generated))
    result.update({
        "generated_spacegroup": generated_spacegroup,
        "generated_crystal_system": generated_crystal_system,
        "spacegroup_match": generated_spacegroup == target_spacegroup,
        "crystal_system_match": generated_crystal_system == target_crystal_system,
        "generated_lattice": {
            "a": float(generated.lattice.a), "b": float(generated.lattice.b),
            "c": float(generated.lattice.c), "alpha": float(generated.lattice.alpha),
            "beta": float(generated.lattice.beta), "gamma": float(generated.lattice.gamma),
        },
        "generated_volume": float(generated.volume),
        "generated_volume_per_atom": generated_volume_per_atom,
        "volume_per_atom_difference": generated_volume_per_atom - target_volume_per_atom,
        "volume_per_atom_percent_difference": (
            100.0 * (generated_volume_per_atom - target_volume_per_atom) / target_volume_per_atom
        ),
    })
    matcher = StructureMatcher(primitive_cell=True, scale=True, attempt_supercell=True)
    result["structure_match"] = bool(matcher.fit(generated, reference))
    if result["structure_match"]:
        rms = matcher.get_rms_dist(generated, reference)
        result["structure_match_rms"] = None if rms is None else float(rms[0])
    return result


def _base_result(target: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return {
        "experiment_id": target["benchmark_id"], "family": target["family"],
        "target_mpid": target["material_id"], "formula": target["formula"],
        "target_spacegroup": "", "target_atom_count": "", "retrieval_k": 0,
        "retrieval_top1_similarity": "", "retrieval_mean_topk": "", "spp_corpus_count": 0,
        "pair_coverage": 0.0, "qlip_status": "NOT_RUN", "qlip_runtime": 0.0,
        "qlip_objective": "", "candidate_generated": False, "candidate_valid": False,
        "sca_status": "NOT_RUN", "minimum_distance": "", "density": "", "spp_score": "",
        "spp_percentile": "", "structure_match": False, "structure_match_rms": "",
        "local_environment_score": "", "primary_mlip_energy": "", "relaxed": False,
        "final_classification": "FAILED_OTHER", "NO_TARGET_LEAKAGE": False,
        "PAIR_COVERAGE_COMPLETE": False, "SPP_ARTIFACT_VALID": False, "SCAFFOLD_USED": False,
        "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": False, "failure_message": "",
        "run_directory": str(run_dir.resolve()),
    }


def _run_target(
    *, target: dict[str, Any], pool: dict[str, Any], crystal_root: Path, output_root: Path,
    policy: SPPOnlyBenchmarkPolicy, stages: ProductionWorkflowStages,
) -> dict[str, Any]:
    run_dir = output_root / "runs" / str(target["family"]) / str(target["benchmark_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    attempts_dir = run_dir / "development_attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    attempt_index = 1
    while (attempts_dir / f"attempt_{attempt_index:03d}").exists():
        attempt_index += 1
    attempt_dir = attempts_dir / f"attempt_{attempt_index:03d}"
    attempt_dir.mkdir(parents=True)
    attempt_token = f"attempt-{attempt_index:03d}"
    run_scope = benchmark_run_scope(output_root)
    row = _base_result(target, run_dir)
    dataset_dir = _dataset_directory(crystal_root, str(target["family"]))
    structure_ids = _structure_ids_by_candidate_key(dataset_dir)
    excluded_ids = tuple(structure_ids[key] for key in pool["excluded_candidate_keys"] if key in structure_ids)
    manifest = {
        "schema_version": "spp_only_target_manifest.v1", "target": target,
        "excluded_candidate_keys": pool["excluded_candidate_keys"], "excluded_structure_ids": excluded_ids,
        "policy": asdict(policy), "assertions": {
            "SCAFFOLD_USED": False, "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": False,
        }, "attempt_token": attempt_token, "run_scope": run_scope,
    }
    _write_json(run_dir / "target_manifest.json", manifest)
    request = _prompt(target)
    task = _task(target)
    base_config = WorkflowConfig(
        output_root=run_dir, retrieval_depth=policy.candidate_retrieval_depth,
        embedding_model=policy.embedding_model, embedding_version=policy.embedding_version,
        retrieval_demo_export=True, cutoff=policy.cutoff, excluded_structure_ids=excluded_ids,
        scaffold_mode="none", native_qlip=True, cell_mode=policy.cell_mode,
        native_grid_density=policy.native_grid_density,
        spp_artifact_contract=policy.spp_artifact_contract,
        run_id=f"{target['benchmark_id']}-{run_scope}-{attempt_token}", attempt_id="spp-only-v1",
    )
    generated: Structure | None = None
    start = time.perf_counter()
    try:
        retrieval = stages.retrieve(request, task, base_config, run_dir / "retrieval")
        database_provenance = assert_family_database_provenance(
            target=target, retrieval=retrieval, crystal_root=crystal_root,
        )
        _write_json(run_dir / "retrieval" / "database_provenance.json", database_provenance)
        core, exclusion_audit = leakage_safe_neighbourhood(
            retrieval, excluded_structure_ids=excluded_ids, limit=policy.spp_corpus_size,
        )
        required_pairs = stages.required_pairs(task, base_config)
        inventory = build_family_pair_inventory(
            crystal_root=crystal_root, dataset_dir=dataset_dir, formula=str(target["formula"]),
            cutoff=policy.cutoff, excluded_structure_ids=excluded_ids,
            semantic_retrieval=retrieval, work_dir=run_dir / "retrieval",
        )
        core_ids = [str(item["structure_id"]) for item in core["selected"]]
        core_counts = actual_pair_structure_counts(core_ids, inventory, required_pairs)
        missing_core_pairs = [pair for pair, count in core_counts.items() if count == 0]
        coverage_additions = select_pair_augmentation(
            candidates=inventory, selected_structure_ids=core_ids, priority_pairs=missing_core_pairs,
            maximum_additions=policy.maximum_corpus_size - len(core_ids), coverage_only=True,
        )
        filtered = append_augmentation_to_retrieval(
            core, coverage_additions, export_dir=run_dir / "retrieval" / "augmentation_cifs",
        )
        _retrieval_artifacts(run_dir, request, retrieval, filtered, exclusion_audit)
        _write_json(run_dir / "retrieval" / "retrieval_core.json", _jsonable(core))
        _write_json(run_dir / "retrieval" / "retrieval_augmentation.json", coverage_additions)
        _write_json(run_dir / "spp" / "required_pairs.json", {"formula": target["formula"], "required_pairs": required_pairs})
        _write_json(run_dir / "spp" / "pair_support.json", inventory)
        scores = [float(item.get("score", item.get("retrieval_score", 0.0))) for item in core["selected"]]
        row.update({
            "retrieval_k": len(core["selected"]),
            "retrieval_top1_similarity": scores[0] if scores else "",
            "retrieval_mean_topk": float(np.mean(scores)) if scores else "",
        })
        def build_evidence(current_retrieval: dict[str, Any]) -> SPPEvidenceBundle:
            assembled = assemble_spp_evidence(
                retrieval=current_retrieval, required_pairs=required_pairs,
                excluded_structure_ids=excluded_ids,
                max_ranked_structures=policy.maximum_corpus_size,
                allow_partial_pair_coverage=True,
            )
            actual_counts = actual_pair_structure_counts(
                (item.structure_id for item in assembled.selected), inventory, required_pairs,
            )
            statuses = {
                pair: {**assembled.pair_evidence_status.get(pair, {}), "local_evidence_present": actual_counts[pair] > 0,
                       "structures_contributing": actual_counts[pair]}
                for pair in required_pairs
            }
            return replace(assembled, pair_structure_counts=actual_counts, pair_evidence_status=statuses)

        evidence = build_evidence(filtered)
        _write_json(run_dir / "spp" / "evidence_bundle.json", evidence.to_dict())
        row["spp_corpus_count"] = len(evidence.selected)
        pair_checks = strict_pair_preflight(evidence, excluded_ids)
        row["NO_TARGET_LEAKAGE"] = pair_checks["NO_TARGET_LEAKAGE"]
        row["PAIR_COVERAGE_COMPLETE"] = pair_checks["PAIR_COVERAGE_COMPLETE"]
        covered = len(required_pairs) - len(pair_checks["missing_pairs"])
        row["pair_coverage"] = covered / len(required_pairs) if required_pairs else 0.0
        _write_json(run_dir / "spp" / "preflight.json", pair_checks)
        if not pair_checks["NO_TARGET_LEAKAGE"]:
            row.update(final_classification="FAILED_RETRIEVAL", failure_message="held-out structure entered SPP evidence")
        elif not pair_checks["SPP_CORPUS_VALID"]:
            row.update(final_classification="FAILED_RETRIEVAL", failure_message="no exportable non-target retrieval evidence")
        else:
            request_spp: dict[str, Any] | None = None
            fit_config = replace(base_config, retrieval_depth=policy.maximum_corpus_size)
            artifact_checks: dict[str, Any] = {}
            quality_additions: list[dict[str, Any]] = []
            fit_round = 0
            while True:
                fit_round += 1
                round_config = replace(
                    fit_config,
                    run_id=f"{target['benchmark_id']}-{run_scope}-{attempt_token}-pair-aware-{fit_round:02d}",
                )
                request_spp = stages.fit_request_spp(evidence, task, round_config, run_dir / "spp" / f"fit_round_{fit_round:02d}")
                local_artifact_checks = strict_spp_artifact_preflight(request_spp, required_pairs)
                artifact_checks = audit_spp_package(
                    required_pairs=required_pairs,
                    request_spp=request_spp,
                    regulator_root=Path(request_spp["regulator_root"]),
                    cif_chain=request_spp.get("quality", {}).get("spp_input_manifest"),
                )
                artifact_checks["local_request_artifact"] = local_artifact_checks
                _write_json(run_dir / "spp" / f"fit_round_{fit_round:02d}" / "strict_spp_audit.json", artifact_checks)
                _write_json(run_dir / "spp" / f"fit_round_{fit_round:02d}" / "spp_build_manifest.json", request_spp.get("quality", {}))
                _write_json(run_dir / "spp" / f"fit_round_{fit_round:02d}" / "pot_inventory.json", artifact_checks.get("pot_audit", {}))
                if artifact_checks["SPP_READY"]:
                    fit_config = round_config
                    break
                weak_pairs = list(dict.fromkeys(
                    list(local_artifact_checks.get("pot_audit", {}).get("missing_pairs", []))
                    + list(local_artifact_checks.get("pot_audit", {}).get("unusable_pairs", []))
                    + [
                        str(item["species_pair"])
                        for item in request_spp.get("quality", {}).get("request_pair_results", [])
                        if item.get("request_pair_status") != "REQUEST_USABLE"
                    ]
                ))
                slots = policy.maximum_corpus_size - len(filtered["selected"])
                if slots <= 0 or not weak_pairs:
                    break
                additions = select_pair_augmentation(
                    candidates=inventory,
                    selected_structure_ids=(str(item["structure_id"]) for item in filtered["selected"]),
                    priority_pairs=weak_pairs,
                    maximum_additions=min(policy.quality_augmentation_batch_size, slots),
                    coverage_only=False,
                )
                if not additions:
                    break
                quality_additions.extend(additions)
                filtered = append_augmentation_to_retrieval(
                    filtered, additions, export_dir=run_dir / "retrieval" / "augmentation_cifs",
                )
                evidence = build_evidence(filtered)
                _write_json(run_dir / "spp" / "evidence_bundle.json", evidence.to_dict())
                row["spp_corpus_count"] = len(evidence.selected)
            _write_json(run_dir / "retrieval" / "retrieval_quality_augmentation.json", quality_additions)
            _write_json(run_dir / "spp" / "artifact_preflight.json", artifact_checks)
            row["PAIR_COVERAGE_COMPLETE"] = bool(artifact_checks.get("all_required_pairs_accounted_for"))
            row["SPP_ARTIFACT_VALID"] = bool(artifact_checks.get("SPP_READY"))
            if not row["SPP_ARTIFACT_VALID"] or request_spp is None:
                unsupported = artifact_checks.get("unsupported_pairs", [])
                if unsupported:
                    row.update(
                        final_classification="FAILED_PAIR_COVERAGE",
                        failure_message="pairs absent or unusable in both request and global regulator: " + ", ".join(unsupported),
                    )
                else:
                    row.update(final_classification="FAILED_SPP_BUILD", failure_message="real-artifact SPP package audit failed")
            else:
                solve_start = time.perf_counter()
                solved = stages.solve(task, request_spp, fit_config, run_dir / "qlip")
                row["qlip_runtime"] = time.perf_counter() - solve_start
                row["qlip_status"] = str(solved.get("status", "UNKNOWN"))
                row["qlip_objective"] = solved.get("solver_objective", "")
                search_space = solved.get("search_space", {})
                row["SCAFFOLD_USED"] = bool(search_space.get("scaffold_mode") != "none" or search_space.get("symmetry_orbit_count", 0))
                qlip_terminal = _qlip_terminal_classification(
                    row["qlip_status"], candidate_present=bool(solved.get("cif_path")),
                )
                if qlip_terminal is not None:
                    row.update(
                        final_classification=qlip_terminal,
                        failure_message=f"QLIP returned {row['qlip_status']} without a candidate",
                    )
                elif row["SCAFFOLD_USED"]:
                    row.update(final_classification="FAILED_OTHER", failure_message="native solve reported scaffold use")
                else:
                    cif_path = Path(solved["cif_path"])
                    generated_dir = run_dir / "generated"
                    generated_dir.mkdir(parents=True, exist_ok=True)
                    preserved = generated_dir / "candidate.cif"
                    shutil.copy2(cif_path, preserved)
                    checks, generated = _mechanical_checks(preserved, str(target["formula"]))
                    _write_json(run_dir / "generated" / "validation.json", checks)
                    row.update({
                        "candidate_generated": bool(checks.get("CIF_created")),
                        "candidate_valid": bool(checks.get("candidate_valid")),
                        "minimum_distance": checks.get("minimum_distance", ""), "density": checks.get("density", ""),
                    })
                    if not row["candidate_valid"]:
                        row.update(final_classification="FAILED_CIF_VALIDATION", failure_message="generated CIF failed mechanical validation")
                    else:
                        sca = stages.evaluate(preserved, task)
                        _write_json(run_dir / "sca" / "result.json", sca)
                        row["sca_status"] = str(sca.get("status", sca.get("evaluation_status", "COMPLETED")))
                        topology = str(sca.get("topology_status", "NOT_APPLICABLE"))
                        row["final_classification"] = "SUCCESS_PLAUSIBLE_NONMATCH" if topology != "FAIL" else "FAILED_SCA_GEOMETRY"
    except Exception as exc:  # noqa: BLE001 - every target remains in the denominator
        row["failure_message"] = f"{type(exc).__name__}: {exc}"
        _classify_target_exception(row, exc)
    reference = _post_generation_reference(crystal_root=crystal_root, target=target, generated=generated, run_dir=run_dir)
    _write_json(run_dir / "comparison" / "reference_comparison.json", reference)
    row["target_spacegroup"] = reference.get("target_spacegroup", "")
    row["target_atom_count"] = reference.get("target_atom_count", "")
    row["structure_match"] = bool(reference.get("structure_match", False))
    row["structure_match_rms"] = reference.get("structure_match_rms") or ""
    if row["candidate_valid"] and row["structure_match"]:
        row["final_classification"] = "SUCCESS_REFERENCE_MATCH"
    row["total_runtime"] = time.perf_counter() - start
    _write_json(run_dir / "run_summary.json", row)
    _write_json(attempt_dir / "run_summary.json", row)
    return row


def benchmark_run_scope(output_root: Path) -> str:
    """Return a stable namespace that isolates QLIP artifacts by result root."""
    return hashlib.sha256(str(Path(output_root).resolve()).encode("utf-8")).hexdigest()[:12]


def _aggregate(output_root: Path, rows: list[dict[str, Any]], frozen: dict[str, Any], policy: SPPOnlyBenchmarkPolicy) -> None:
    _write_csv(output_root / "PAPER_SPP_ONLY_100_RESULTS.csv", RESULT_COLUMNS, rows)
    _write_csv(output_root / "LAYERED_RESULTS.csv", RESULT_COLUMNS, (row for row in rows if row["family"] == "layered"))
    _write_csv(output_root / "SPINEL_RESULTS.csv", RESULT_COLUMNS, (row for row in rows if row["family"] == "spinel"))
    failures = Counter(str(row["final_classification"]) for row in rows)
    _write_csv(output_root / "FAILURE_TAXONOMY.csv", ("classification", "count"), ({"classification": key, "count": value} for key, value in sorted(failures.items())))
    top = sorted((row for row in rows if row["candidate_valid"]), key=lambda row: (not row["structure_match"], float(row["qlip_objective"] or math.inf)))[:20]
    _write_csv(output_root / "TOP_CANDIDATES.csv", RESULT_COLUMNS, top)
    index = {
        "schema_version": "spp_only_run_manifest_index.v1", "freeze_sha256": frozen["freeze_sha256"],
        "policy": asdict(policy), "row_count": len(rows),
        "runs": [{"experiment_id": row["experiment_id"], "summary": str(Path(row["run_directory"]) / "run_summary.json")} for row in rows],
    }
    _write_json(output_root / "RUN_MANIFEST_INDEX.json", index)
    success = sum(str(row["final_classification"]).startswith("SUCCESS_") for row in rows)
    complete = sum(bool(row["PAIR_COVERAGE_COMPLETE"]) for row in rows)
    summary = [
        "# SPP-Only Oxide Benchmark Summary", "", f"- Frozen targets: {len(rows)} (50 layered, 50 spinel)",
        f"- Strict request-pair coverage complete: {complete}/{len(rows)}", f"- Generated valid candidates: {sum(bool(row['candidate_valid']) for row in rows)}/{len(rows)}",
        f"- Successful classifications: {success}/{len(rows)}", "", "## Terminal classifications", "",
    ] + [f"- {key}: {value}" for key, value in sorted(failures.items())]
    (output_root / "PAPER_SPP_ONLY_SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    (output_root / "PAPER_SPP_ONLY_100_RESULTS.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    manifests = ["# Dataset Manifests", "", f"- Freeze SHA256: `{frozen['freeze_sha256']}`"]
    for source in frozen.get("source_manifests", []):
        manifests.append(f"- `{source}`")
    (output_root / "DATASET_MANIFESTS.md").write_text("\n".join(manifests) + "\n", encoding="utf-8")


def run_spp_only_benchmark(
    *, frozen_path: Path, crystal_root: Path, output_root: Path,
    policy: SPPOnlyBenchmarkPolicy | None = None, resume: bool = True,
    stages: ProductionWorkflowStages | None = None,
    max_new_targets: int | None = None,
) -> list[dict[str, Any]]:
    policy = policy or SPPOnlyBenchmarkPolicy()
    stages = stages or ProductionWorkflowStages()
    frozen = json.loads(Path(frozen_path).read_text(encoding="utf-8"))
    targets = list(frozen.get("targets", []))
    pools = {str(row["benchmark_id"]): row for row in frozen.get("evidence_pools", [])}
    if len(targets) != 100 or Counter(str(row["family"]) for row in targets) != Counter({"layered": 50, "spinel": 50}):
        raise ValueError("frozen benchmark must contain exactly 50 layered and 50 spinel targets")
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    new_targets = 0
    for target in targets:
        run_dir = output_root / "runs" / str(target["family"]) / str(target["benchmark_id"])
        summary_path = run_dir / "run_summary.json"
        if resume and summary_path.is_file():
            rows.append(json.loads(summary_path.read_text(encoding="utf-8")))
            continue
        if max_new_targets is not None and new_targets >= int(max_new_targets):
            break
        rows.append(_run_target(
            target=target, pool=pools[str(target["benchmark_id"])], crystal_root=Path(crystal_root),
            output_root=output_root, policy=policy, stages=stages,
        ))
        new_targets += 1
        _aggregate(output_root, rows, frozen, policy)
    _aggregate(output_root, rows, frozen, policy)
    return rows


__all__ = [
    "RESULT_COLUMNS", "SPPOnlyBenchmarkPolicy", "benchmark_run_scope", "leakage_safe_neighbourhood",
    "normalize_pair_for_match", "run_spp_only_benchmark", "strict_pair_preflight",
    "strict_spp_artifact_preflight",
]
