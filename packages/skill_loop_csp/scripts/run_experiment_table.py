"""Run human-editable CSV/TSV experiment rows through the canonical CSP API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sok_llm_orchestrator.bench.prospective import FrozenReference, ProspectiveBenchmarkStages
from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    run_csp_workflow,
)


REQUIRED_COLUMNS = ("row_id", "formula", "request", "scaffold_mode", "request_spp_mode")
OPTIONAL_COLUMNS = (
    "experiment_block", "family", "corpus", "reference_id", "repeat_group", "repeat_index",
    "run_sca", "run_chgnet", "enabled", "notes", "retrieval_depth", "embedding_model",
    "embedding_version", "retrieval_demo_export", "cutoff", "request_coefficient",
    "regulator_coefficient", "outer_objective_scale", "request_spp_convention", "regulator_id",
    "registry_path", "execution_mode", "source_artifact", "source_artifact_key",
    "scaffold_dir", "cell_mode", "cell_volume_per_atom",
)
KNOWN_COLUMNS = set(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)
ROW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
PARITY_TOLERANCE = 1e-6

RESULT_FIELDS = [
    "row_id", "source_row", "experiment_block", "enabled", "formula", "family", "request",
    "notes", "scaffold_mode", "scaffold_dir", "scaffold_id", "scaffold_hash",
    "candidate_site_count", "symmetry_orbit_count", "species_fixed_orbit_count",
    "variable_orbit_count", "allocation_variable_count", "candidate_space_id",
    "repeat_group", "repeat_index", "run_sca",
    "run_chgnet",
    "request_spp_mode", "resolved_corpus", "feasible_state_count", "corpus_id", "corpus_hash",
    "retrieved_count", "retrieved_ids", "evidence_count", "evidence_ids", "evidence_hash",
    "request_spp_hash", "request_usable_pairs", "request_usable_pair_count",
    "fallback_pairs", "fallback_pair_count", "unsupported_pairs", "unsupported_pair_count",
    "solver_status", "objective_parity", "solver_objective", "independent_objective",
    "objective_difference", "cif_generated", "cif_path", "cif_hash", "sca_status",
    "sca_parse_ok", "sca_pre_dft_valid", "sca_topology_status", "sca_geometry_status",
    "sca_geometry_ok", "sca_geometry_warning_count", "sca_min_distance", "sca_min_distance_pair",
    "sca_num_bad_contacts", "sca_bond_lengths_reasonable", "sca_bond_reasonableness_score",
    "sca_chemical_species_valid", "sca_target_formula_match", "sca_space_group_consistent",
    "cell_mode", "cell_volume_per_atom_override", "cell_a_A", "cell_volume_A3",
    "cell_vpa_A3_per_atom", "cell_vpa_source", "cell_grid_spacing_A", "cell_n_target_atoms",
    "sca_multiplicity_checked", "sca_multiplicity_consistent", "sca_failed_check_count",
    "sca_failed_check_names", "sca_error_type", "sca_error_message", "reference_id",
    "reference_match", "generated_space_group", "reference_space_group", "space_group_match",
    "generated_crystal_system", "reference_crystal_system", "crystal_system_match",
    "generated_volume", "reference_volume", "volume_error_percent", "chgnet_status",
    "chgnet_converged", "relaxed_space_group", "relaxed_crystal_system", "relaxed_volume",
    "volume_change_percent", "initial_relaxed_match", "workflow_status", "failure_stage",
    "failure_code", "failure_message", "run_id", "attempt_id", "workflow_commit",
    "runtime_seconds", "stage_timings", "provenance_complete", "provenance_missing_fields",
    "execution_mode", "source_artifact", "source_artifact_key", "source_artifact_hash",
    "workflow_figure_status", "workflow_figure_png", "workflow_figure_pdf", "workflow_figure_error",
]


class TableFormatError(ValueError):
    pass


@dataclass(slots=True)
class ExperimentRow:
    source_row: int
    row_id: str
    formula: str
    request: str
    scaffold_mode: str
    request_spp_mode: str
    cell_mode: str = "native"
    experiment_block: str = ""
    family: str = ""
    corpus: str = ""
    reference_id: str = ""
    repeat_group: str = ""
    repeat_index: str = ""
    run_sca: bool = True
    run_chgnet: bool = False
    execution_mode: str = "canonical"
    source_artifact: str = ""
    source_artifact_key: str = ""
    enabled: bool = True
    notes: str = ""
    values: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    resolved_task: dict[str, Any] | None = None
    resolved_corpus: str = ""
    resolved_scaffold: str = ""
    feasible_state_count: int | None = None


@dataclass(slots=True)
class TableRunReport:
    input_path: Path
    output_root: Path
    rows_parsed: int
    rows_selected: int
    result_rows: list[dict[str, Any]]
    software_failure: bool = False


def _bool(value: str, *, default: bool, field_name: str) -> bool:
    compact = str(value or "").strip().lower()
    if not compact:
        return default
    if compact in TRUE_VALUES:
        return True
    if compact in FALSE_VALUES:
        return False
    raise ValueError(f"{field_name} must be one of yes/no, true/false, 1/0")


def _delimiter(path: Path, text: str) -> str:
    if path.suffix.lower() == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",\t").delimiter
    except csv.Error:
        return "\t" if "\t" in text.partition("\n")[0] else ","


def parse_experiment_table(path: Path) -> list[ExperimentRow]:
    source = Path(path).resolve()
    if source.suffix.lower() not in {".csv", ".tsv", ".txt"}:
        raise TableFormatError("experiment table must be .csv, .tsv, or .txt")
    text = source.read_text(encoding="utf-8-sig")
    uncommented = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    reader = csv.DictReader(io.StringIO(uncommented), delimiter=_delimiter(source, uncommented))
    headers = [str(value or "").strip() for value in (reader.fieldnames or [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise TableFormatError(f"missing required columns: {', '.join(missing)}")
    rows: list[ExperimentRow] = []
    seen: set[str] = set()
    for source_row, raw in enumerate(reader, start=2):
        values = {str(key).strip(): str(value or "").strip() for key, value in raw.items() if key is not None}
        errors = [f"{column} is required" for column in REQUIRED_COLUMNS if not values.get(column)]
        row_id = values.get("row_id", "")
        if row_id and not ROW_ID_RE.fullmatch(row_id):
            errors.append("row_id must use only letters, digits, dot, underscore, or hyphen")
        if row_id in seen:
            errors.append("row_id is duplicated")
        seen.add(row_id)
        try:
            enabled = _bool(values.get("enabled", ""), default=True, field_name="enabled")
        except ValueError as exc:
            enabled = True
            errors.append(str(exc))
        try:
            run_sca = _bool(values.get("run_sca", ""), default=True, field_name="run_sca")
            run_chgnet = _bool(values.get("run_chgnet", ""), default=False, field_name="run_chgnet")
        except ValueError as exc:
            run_sca, run_chgnet = True, False
            errors.append(str(exc))
        row = ExperimentRow(
            source_row=source_row, row_id=row_id or f"invalid_row_{source_row}",
            formula=values.get("formula", ""), request=values.get("request", ""),
            scaffold_mode=values.get("scaffold_mode", ""),
            request_spp_mode=values.get("request_spp_mode", ""),
            cell_mode=values.get("cell_mode", "") or "native", corpus=values.get("corpus", ""),
            experiment_block=values.get("experiment_block", ""), family=values.get("family", ""),
            reference_id=values.get("reference_id", ""), repeat_group=values.get("repeat_group", ""),
            repeat_index=values.get("repeat_index", ""), run_sca=run_sca, run_chgnet=run_chgnet,
            execution_mode=values.get("execution_mode", "") or "canonical",
            source_artifact=values.get("source_artifact", ""),
            source_artifact_key=values.get("source_artifact_key", ""),
            enabled=enabled, notes=values.get("notes", ""),
            values=values, errors=errors,
        )
        validate_row(row)
        rows.append(row)
    return rows


def _optional_int(row: ExperimentRow, name: str, default: int) -> int:
    value = row.values.get(name, "")
    if not value:
        return default
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _optional_float(row: ExperimentRow, name: str, default: float, *, positive: bool = False) -> float:
    value = row.values.get(name, "")
    if not value:
        return default
    parsed = float(value)
    if positive and parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def validate_row(row: ExperimentRow) -> None:
    if row.execution_mode not in {"canonical", "reuse_frozen"}:
        row.errors.append("execution_mode must be canonical or reuse_frozen")
    if row.execution_mode == "reuse_frozen":
        if not row.source_artifact:
            row.errors.append("source_artifact is required for reuse_frozen rows")
        elif not Path(row.source_artifact).resolve().is_file():
            row.errors.append(f"source_artifact does not exist: {row.source_artifact}")
        return
    if row.scaffold_mode and row.scaffold_mode not in {"none", "hard", "tight", "loose", "minimal"}:
        row.errors.append("scaffold_mode must be none, hard, tight, loose, or minimal")
    if row.request_spp_mode and row.request_spp_mode not in {"enabled", "disabled"}:
        row.errors.append("request_spp_mode must be enabled or disabled")
    if row.cell_mode not in {"native", "composition_scaled", "retrieval_derived"}:
        row.errors.append("cell_mode must be native, composition_scaled, or retrieval_derived")
    if row.values.get("cell_volume_per_atom"):
        try:
            if float(row.values["cell_volume_per_atom"]) <= 0:
                row.errors.append("cell_volume_per_atom must be positive")
        except ValueError:
            row.errors.append("cell_volume_per_atom must be a number")
        if row.cell_mode == "native":
            row.errors.append("cell_volume_per_atom is not applicable when cell_mode=native")
    stages = ProductionWorkflowStages()
    if row.formula:
        try:
            row.resolved_task = stages.normalise(row.formula)
        except Exception:
            row.errors.append(f"formula has no canonical task mapping: {row.formula}")
    if row.request and row.resolved_task is not None:
        try:
            request_task = stages.normalise(row.request)
            if request_task["formula"] != row.resolved_task["formula"]:
                row.errors.append("request resolves to a different canonical formula")
        except Exception:
            row.errors.append("request does not identify the canonical formula")
    try:
        _optional_int(row, "retrieval_depth", 40)
        _optional_float(row, "cutoff", 11.0, positive=True)
        _optional_float(row, "request_coefficient", 1.0)
        _optional_float(row, "regulator_coefficient", 2.0)
        _optional_float(row, "outer_objective_scale", 10.0)
        _bool(row.values.get("retrieval_demo_export", ""), default=True, field_name="retrieval_demo_export")
    except (TypeError, ValueError) as exc:
        row.errors.append(str(exc))
    convention = row.values.get("request_spp_convention", "")
    if convention and convention not in {"reward", "penalty"}:
        row.errors.append("request_spp_convention must be reward or penalty")
    if row.resolved_task is not None:
        registry = Path(row.values["registry_path"]).resolve() if row.values.get("registry_path") else None
        try:
            route = route_corpus(row.request, formula=row.formula, registry_path=registry)
            row.resolved_corpus = route.corpus_id
            if row.corpus and row.corpus != route.corpus_id:
                row.errors.append(f"corpus assertion mismatch: canonical route is {route.corpus_id}")
        except Exception as exc:
            row.errors.append(f"corpus resolution failed: {exc}")


_LEGACY_SCAFFOLD_SELECTION = object()


def build_workflow_config(
    row: ExperimentRow, output_root: Path, *, stages: Any = None,
    scaffolds: Path | None | object = _LEGACY_SCAFFOLD_SELECTION,
) -> WorkflowConfig:
    if scaffolds is _LEGACY_SCAFFOLD_SELECTION:
        scaffold_dir, native_qlip, scaffold_mode = None, False, row.scaffold_mode
    elif scaffolds is None:
        scaffold_dir, native_qlip, scaffold_mode = None, True, "none"
    else:
        scaffold_dir = Path(scaffolds).resolve()
        descriptor = json.loads((scaffold_dir / "registry.json").read_text(encoding="utf-8"))
        scaffold_mode = str(descriptor.get("mode") or "")
        native_qlip = False
    return WorkflowConfig(
        output_root=Path(output_root), retrieval_depth=_optional_int(row, "retrieval_depth", 40),
        embedding_model=row.values.get("embedding_model") or "text-embedding-bge-m3",
        embedding_version=row.values.get("embedding_version") or "lmstudio_v1",
        retrieval_demo_export=_bool(row.values.get("retrieval_demo_export", ""), default=True, field_name="retrieval_demo_export"),
        cutoff=_optional_float(row, "cutoff", 11.0, positive=True),
        request_coefficient=_optional_float(row, "request_coefficient", 1.0),
        regulator_coefficient=_optional_float(row, "regulator_coefficient", 2.0),
        outer_objective_scale=_optional_float(row, "outer_objective_scale", 10.0),
        request_spp_convention=row.values.get("request_spp_convention") or "reward",
        regulator_id=row.values.get("regulator_id") or "icsd_broad_regulator_v1",
        registry_path=Path(row.values["registry_path"]).resolve() if row.values.get("registry_path") else None,
        scaffold_mode=scaffold_mode, scaffold_dir=scaffold_dir, native_qlip=native_qlip,
        request_spp_mode=row.request_spp_mode, stages=stages,
        cell_mode=row.cell_mode if native_qlip else "native",
        cell_volume_per_atom=(
            float(row.values["cell_volume_per_atom"]) if row.values.get("cell_volume_per_atom") else None
        ),
    )


def resolve_reference(row: ExperimentRow, row_dir: Path) -> FrozenReference | None:
    if not row.reference_id:
        return None
    registry = Path(row.values["registry_path"]).resolve() if row.values.get("registry_path") else None
    route = route_corpus(row.request, formula=row.formula, registry_path=registry)
    from crystal_db.query import get_structure

    record = get_structure(row.reference_id, db_path=str(route.database), include_cif=True)
    if record.get("error") == "not_found":
        raise ValueError(f"reference_id not found in {route.corpus_id}: {row.reference_id}")
    if record.get("restricted") or not record.get("cif_text"):
        raise ValueError(f"reference_id cannot provide an exportable CIF: {row.reference_id}")
    reference_path = row_dir / "reference.cif"
    reference_path.write_text(str(record["cif_text"]), encoding="utf-8")
    structure = Structure.from_file(reference_path)
    if structure.composition.reduced_composition != Composition(row.formula).reduced_composition:
        raise ValueError(f"reference_id formula does not match row formula: {row.reference_id}")
    return FrozenReference.from_cif(
        case_id=row.row_id, formula=row.formula, reference_id=row.reference_id,
        source_structure_id=str(record.get("source_id") or row.reference_id), cif_path=reference_path,
    )


def dry_run_row(
    row: ExperimentRow, row_dir: Path,
    scaffolds: Path | None | object = _LEGACY_SCAFFOLD_SELECTION,
) -> dict[str, Any]:
    if row.errors:
        return input_error_result(row)
    if row.execution_mode == "reuse_frozen":
        return base_result(row) | {
            "cif_generated": "NOT_REEXECUTED", "workflow_status": "DRY_RUN_REUSE_READY",
            "solver_status": "REUSED_FROZEN_RESULT", **_frozen_source_projection(row),
        }
    stages = ProductionWorkflowStages()
    config = build_workflow_config(row, row_dir, scaffolds=scaffolds)
    try:
        from sok_llm_orchestrator.workflow.scaffold_ablation import load_selection
        if scaffolds is not _LEGACY_SCAFFOLD_SELECTION:
            resolved_cell = None
            if config.native_qlip and config.cell_mode == "composition_scaled":
                from sok_llm_orchestrator.workflow.cell_strategy import resolve_native_cell
                resolved_cell = resolve_native_cell(
                    str((row.resolved_task or {}).get("formula") or row.formula),
                    cell_mode=config.cell_mode, cell_volume_per_atom=config.cell_volume_per_atom,
                )
            selection = load_selection(
                dict(row.resolved_task or {}), None if config.native_qlip else config.scaffold_dir,
                resolved_cell=resolved_cell,
            )
            row.resolved_scaffold = selection.scaffold_id
            row.feasible_state_count = selection.feasible_state_count
            provenance = selection.provenance()
            if config.native_qlip and config.cell_mode == "retrieval_derived":
                provenance = {**provenance, "cell_provenance": {"note": "PREVIEW_UNAVAILABLE_REQUIRES_EVIDENCE_RETRIEVAL"}}
        else:
            scaffold_id, _, _ = stages._scaffold(dict(row.resolved_task or {}), config)
            row.resolved_scaffold = scaffold_id
            try:
                row.feasible_state_count = len(stages.enumerate_feasible_assignments(dict(row.resolved_task or {}), config))
            except ValueError:
                row.feasible_state_count = None
            provenance = {"scaffold_id": scaffold_id}
        return base_result(row) | {
            **provenance, **_cell_projection(provenance),
            "feasible_state_count": row.feasible_state_count if row.feasible_state_count is not None else "NOT_CHEAPLY_AVAILABLE",
            "cif_generated": "NO", "workflow_status": "DRY_RUN_READY", "solver_status": "NOT_RUN",
        }
    except Exception as exc:
        row.errors.append(str(exc))
        return input_error_result(row)


def base_result(row: ExperimentRow) -> dict[str, Any]:
    resolved_family = row.family or str((row.resolved_task or {}).get("family") or "")
    return {field: "" for field in RESULT_FIELDS} | {
        "row_id": row.row_id, "source_row": row.source_row,
        "experiment_block": row.experiment_block, "enabled": "YES" if row.enabled else "NO",
        "formula": row.formula, "family": resolved_family, "request": row.request, "notes": row.notes,
        "scaffold_mode": row.scaffold_mode, "request_spp_mode": row.request_spp_mode,
        "cell_mode": row.cell_mode, "cell_volume_per_atom_override": row.values.get("cell_volume_per_atom", ""),
        "repeat_group": row.repeat_group, "repeat_index": row.repeat_index,
        "run_sca": "YES" if row.run_sca else "NO", "run_chgnet": "YES" if row.run_chgnet else "NO",
        "resolved_corpus": row.resolved_corpus, "reference_id": row.reference_id,
        "chgnet_status": "PENDING_EXTERNAL_QC" if row.run_chgnet else "NOT_REQUESTED",
        "execution_mode": row.execution_mode, "source_artifact": row.source_artifact,
        "source_artifact_key": row.source_artifact_key,
    }


def input_error_result(row: ExperimentRow) -> dict[str, Any]:
    return base_result(row) | {
        "cif_generated": "NO", "workflow_status": "ROW_INPUT_ERROR", "failure_stage": "row_validation",
        "failure_code": "ROW_INPUT_ERROR", "failure_message": "; ".join(dict.fromkeys(row.errors)),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frozen_source_projection(row: ExperimentRow) -> dict[str, Any]:
    source = Path(row.source_artifact).resolve()
    selected: Any = None
    if source.suffix.lower() == ".csv" and row.source_artifact_key:
        key_name, separator, key_value = row.source_artifact_key.partition("=")
        if not separator or not key_name or not key_value:
            raise ValueError("source_artifact_key must use column=value syntax")
        with source.open(encoding="utf-8-sig", newline="") as handle:
            matches = [record for record in csv.DictReader(handle) if record.get(key_name) == key_value]
        if len(matches) != 1:
            raise ValueError(f"source_artifact_key matched {len(matches)} rows; expected exactly one")
        selected = matches[0]
    elif source.suffix.lower() == ".json":
        selected = json.loads(source.read_text(encoding="utf-8"))
    return {
        "source_artifact": str(source), "source_artifact_hash": _sha256(source),
        "source_artifact_key": row.source_artifact_key,
        "provenance_complete": "YES", "provenance_missing_fields": "",
        "_selected_source_record": selected,
    }


def _cell_projection(search_space: dict[str, Any]) -> dict[str, Any]:
    cell = search_space.get("cell_provenance") if isinstance(search_space, dict) else None
    if not isinstance(cell, dict):
        return {}
    # cell_mode itself is intentionally NOT projected here: base_result() already
    # carries the authoritative row.cell_mode, and a placeholder/preview cell dict
    # (e.g. the retrieval_derived dry-run preview) must not blank it out.
    return {
        "cell_a_A": cell.get("a", ""),
        "cell_volume_A3": cell.get("cell_volume_A3", ""),
        "cell_vpa_A3_per_atom": cell.get("vpa_value_A3_per_atom", ""),
        "cell_vpa_source": cell.get("vpa_source", ""),
        "cell_grid_spacing_A": cell.get("grid_spacing_A", ""),
        "cell_n_target_atoms": cell.get("n_target_atoms", ""),
    }


def _pair_lists(result: Any) -> tuple[list[str], list[str], list[str]]:
    rows = list(result.request_spp_quality.get("request_pair_results", []))
    usable = [str(item["species_pair"]) for item in rows if item.get("request_pair_status") == "REQUEST_USABLE"]
    fallback = [str(item["species_pair"]) for item in rows if str(item.get("guidance_mode", "")).startswith("REGULATOR_ONLY")]
    unsupported = [str(item["species_pair"]) for item in rows if item.get("guidance_mode") == "UNSUPPORTED_REQUIRED_PAIR"]
    return usable, fallback, unsupported


def _sca_projection(sca: dict[str, Any]) -> dict[str, Any]:
    checks = (
        "chemical_species_valid", "target_formula_match", "space_group_consistent",
        "multiplicity_consistent", "bond_lengths_reasonable", "geometry_ok", "pre_dft_valid",
    )
    failed = [name for name in checks if sca.get(name) is False]
    parse_ok = sca.get("parse_ok")
    pre_dft_valid = sca.get("pre_dft_valid")
    status = "FAIL" if parse_ok is False else "PASS" if pre_dft_valid is True else "PARTIAL"
    geometry = "PASS" if sca.get("geometry_ok") is True else "FAIL" if sca.get("geometry_ok") is False else "NOT_AVAILABLE"
    return {
        "sca_status": status, "sca_parse_ok": parse_ok, "sca_pre_dft_valid": pre_dft_valid,
        "sca_topology_status": sca.get("topology_status", "NOT_AVAILABLE"),
        "sca_geometry_status": geometry, "sca_geometry_ok": sca.get("geometry_ok"),
        "sca_geometry_warning_count": sca.get("geometry_warning_count"),
        "sca_min_distance": sca.get("min_distance"), "sca_min_distance_pair": sca.get("min_distance_pair"),
        "sca_num_bad_contacts": sca.get("num_bad_contacts"),
        "sca_bond_lengths_reasonable": sca.get("bond_lengths_reasonable"),
        "sca_bond_reasonableness_score": sca.get("bond_reasonableness_score"),
        "sca_chemical_species_valid": sca.get("chemical_species_valid"),
        "sca_target_formula_match": sca.get("target_formula_match"),
        "sca_space_group_consistent": sca.get("space_group_consistent"),
        "sca_multiplicity_checked": sca.get("multiplicity_checked"),
        "sca_multiplicity_consistent": sca.get("multiplicity_consistent"),
        "sca_failed_check_count": len(failed), "sca_failed_check_names": ";".join(failed),
        "sca_error_type": sca.get("error_type"), "sca_error_message": sca.get("error_message"),
    }


def _structure_projection(cif_path: Path, reference: FrozenReference | None) -> dict[str, Any]:
    generated = Structure.from_file(cif_path)
    generated_sga = SpacegroupAnalyzer(generated, symprec=1e-2, angle_tolerance=5)
    projected: dict[str, Any] = {
        "generated_space_group": generated_sga.get_space_group_symbol(),
        "generated_crystal_system": generated_sga.get_crystal_system(),
        "generated_volume": float(generated.volume),
    }
    if reference is None:
        return projected
    heldout = Structure.from_file(reference.cif_path)
    reference_sga = SpacegroupAnalyzer(heldout, symprec=1e-2, angle_tolerance=5)
    generated_vpa, reference_vpa = float(generated.volume / len(generated)), float(heldout.volume / len(heldout))
    projected.update({
        "reference_match": "YES" if StructureMatcher().fit(generated, heldout) else "NO",
        "reference_space_group": reference_sga.get_space_group_symbol(),
        "space_group_match": "YES" if generated_sga.get_space_group_symbol() == reference_sga.get_space_group_symbol() else "NO",
        "reference_crystal_system": reference_sga.get_crystal_system(),
        "crystal_system_match": "YES" if generated_sga.get_crystal_system() == reference_sga.get_crystal_system() else "NO",
        "reference_volume": float(heldout.volume),
        "volume_error_percent": 100.0 * abs(generated_vpa - reference_vpa) / reference_vpa,
    })
    return projected


def _link_artifact(source: Path, destination: Path) -> str:
    if not source.is_file():
        return "missing"
    if destination.exists() and destination.samefile(source):
        return "existing_hardlink"
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        os.link(source, temporary)
        mode = "hardlink"
    except OSError:
        shutil.copy2(source, temporary)
        mode = "copy"
    temporary.replace(destination)
    return mode


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_row_artifacts(row_dir: Path, row: ExperimentRow, summary: dict[str, Any], detail: dict[str, Any]) -> None:
    row_dir.mkdir(parents=True, exist_ok=True)
    _write_json(row_dir / "input.json", {"row": asdict(row), "supported_columns": list(REQUIRED_COLUMNS + OPTIONAL_COLUMNS)})
    _write_json(row_dir / "result.json", detail)
    (row_dir / "result.txt").write_text("\n".join(f"{key}: {summary.get(key, '')}" for key in RESULT_FIELDS) + "\n", encoding="utf-8")


def execute_row(
    row: ExperimentRow, row_dir: Path, workflow_fn: Callable[..., Any],
    scaffolds: Path | None | object = _LEGACY_SCAFFOLD_SELECTION,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    if row.errors:
        summary = input_error_result(row)
        return summary, {"summary": summary}, False
    if not row.enabled:
        summary = base_result(row) | {"workflow_status": "SKIPPED_DISABLED", "cif_generated": "NO", "solver_status": "NOT_RUN"}
        return summary, {"summary": summary}, False
    if row.execution_mode == "reuse_frozen":
        try:
            source = _frozen_source_projection(row)
            selected = source.pop("_selected_source_record", None)
            summary = base_result(row) | source | {
                "workflow_status": "REUSED_FROZEN_RESULT", "solver_status": "SEE_SOURCE_ARTIFACT",
                "cif_generated": "SEE_SOURCE_ARTIFACT",
            }
            return summary, {"summary": summary, "selected_source_record": selected}, False
        except Exception as exc:
            summary = base_result(row) | {
                "workflow_status": "ROW_INPUT_ERROR", "failure_stage": "frozen_source_validation",
                "failure_code": "ROW_INPUT_ERROR", "failure_message": str(exc),
                "cif_generated": "NO", "solver_status": "NOT_RUN",
            }
            return summary, {"summary": summary}, False
    try:
        reference = resolve_reference(row, row_dir)
    except Exception as exc:
        row.errors.append(str(exc))
        summary = input_error_result(row)
        return summary, {"summary": summary}, False
    stages: Any = None
    excluded: tuple[str, ...] = ()
    if reference is not None:
        stages = ProspectiveBenchmarkStages(tasks=ProductionWorkflowStages._TASKS, reference=reference)
        excluded = (reference.reference_id, reference.source_structure_id)
    config = build_workflow_config(row, row_dir, stages=stages, scaffolds=scaffolds)
    search_space: dict[str, Any] = {}
    if scaffolds is not _LEGACY_SCAFFOLD_SELECTION:
        from sok_llm_orchestrator.workflow.scaffold_ablation import load_selection
        selection = load_selection(dict(row.resolved_task or {}), None if config.native_qlip else config.scaffold_dir)
        search_space = selection.provenance()
        _write_json(row_dir / "scaffold_provenance.json", search_space)
    if excluded:
        from dataclasses import replace
        config = replace(config, excluded_structure_ids=excluded)
    try:
        result = workflow_fn(row.request, config)
        usable, fallback, unsupported = _pair_lists(result)
        cif_path = Path(result.generated_cif_path)
        direct_cif = row_dir / "generated.cif"
        artifact_modes = {"generated.cif": _link_artifact(cif_path, direct_cif)}
        attempt = Path(result.attempt_workspace)
        for name in ("workflow_trace.json", "attempt_manifest.json"):
            artifact_modes[name] = _link_artifact(attempt / name, row_dir / name)
        trace: dict[str, Any] = {}
        trace_path = attempt / "workflow_trace.json"
        if trace_path.is_file():
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        _write_json(row_dir / "sca.json", result.sca_result)
        parity = "PASS" if float(result.objective_difference) < PARITY_TOLERANCE else "FAIL"
        search_space = dict(getattr(result, "search_space_provenance", {}) or trace.get("search_space_provenance", {}) or search_space)
        summary = base_result(row) | search_space | {
            **search_space, **_cell_projection(search_space),
            "candidate_space_id": getattr(result, "scaffold_id", ""),
            "feasible_state_count": result.feasible_state_count, "corpus_id": result.corpus_id,
            "corpus_hash": result.corpus_hash, "retrieved_count": len(result.retrieved_ids),
            "retrieved_ids": ";".join(result.retrieved_ids),
            "evidence_count": getattr(result, "spp_evidence_count", trace.get("SPP_evidence_count", "")),
            "evidence_ids": ";".join(getattr(result, "spp_evidence_ids", ())) or ";".join(trace.get("SPP_evidence_ids", [])),
            "evidence_hash": trace.get("evidence_bundle", {}).get("bundle_hash", ""),
            "request_spp_hash": trace.get("request_spp_hash", "") or trace.get("request_spp_hashes", {}).get("tree_sha256", ""),
            "request_usable_pairs": ";".join(usable),
            "request_usable_pair_count": len(usable), "fallback_pairs": ";".join(fallback),
            "fallback_pair_count": len(fallback), "unsupported_pairs": ";".join(unsupported),
            "unsupported_pair_count": len(unsupported), "solver_status": result.solver_status,
            "objective_parity": parity, "solver_objective": result.solver_objective,
            "independent_objective": result.independent_objective, "objective_difference": result.objective_difference,
            "cif_generated": "YES", "cif_path": str(direct_cif.resolve()), "cif_hash": result.generated_cif_hash,
            **_sca_projection(result.sca_result), **_structure_projection(direct_cif, reference),
            "workflow_status": "PASS" if parity == "PASS" else "OBJECTIVE_PARITY_FAILURE",
            "failure_stage": "" if parity == "PASS" else "objective_parity",
            "failure_code": "" if parity == "PASS" else "OBJECTIVE_PARITY_FAILURE",
            "run_id": result.run_id, "attempt_id": result.attempt_id,
            "workflow_commit": getattr(result, "provenance_manifest", {}).get("repositories", {}).get("Skill-Loop-CSP", ""),
            "runtime_seconds": trace.get("runtime_seconds", ""),
            "stage_timings": json.dumps(trace.get("stage_timings", {}), sort_keys=True),
        }
        required_provenance = {
            "request": summary["request"], "corpus_hash": summary["corpus_hash"],
            "retrieved_ids": summary["retrieved_ids"], "evidence_ids": summary["evidence_ids"],
            "candidate_space_id": summary["candidate_space_id"], "solver_status": summary["solver_status"],
            "objective_parity": summary["objective_parity"], "cif_hash": summary["cif_hash"],
            "run_id": summary["run_id"], "attempt_id": summary["attempt_id"],
        }
        missing = [name for name, value in required_provenance.items() if value in (None, "")]
        summary["provenance_complete"] = "YES" if not missing else "NO"
        summary["provenance_missing_fields"] = ";".join(missing)
        detail = {"summary": summary, "canonical_result": result.to_dict(), "artifact_materialization": artifact_modes}
        return summary, detail, parity != "PASS"
    except WorkflowStageError as exc:
        summary = base_result(row) | search_space | {
            "workflow_status": "CONTROLLED_WORKFLOW_FAILURE", "failure_stage": exc.stage,
            "failure_code": exc.code, "failure_message": str(exc), "cif_generated": "NO",
            "solver_status": "NOT_COMPLETED",
        }
        return summary, {"summary": summary, "failure_details": exc.details}, False
    except Exception as exc:
        summary = base_result(row) | search_space | {
            "workflow_status": "SOFTWARE_FAILURE", "failure_stage": "workflow_execution",
            "failure_code": type(exc).__name__, "failure_message": str(exc), "cif_generated": "NO",
            "solver_status": "NOT_COMPLETED",
        }
        return summary, {"summary": summary}, True


def _write_results_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _markdown_value(value: Any) -> str:
    return str(value if value not in (None, "") else "—").replace("|", "\\|")


def write_results_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# Experiment Results", ""]
    formulas = list(dict.fromkeys(str(row.get("formula") or "UNRESOLVED") for row in rows))
    for formula in formulas:
        lines.extend([f"## {formula}", "", "| Row | Scaffold | Request SPP | States | QLIP | Parity | SCA | Reference | SG | Crystal system | Volume error % | Workflow |", "|---|---|---|---:|---|---|---|---|---|---|---:|---|"])
        for row in (item for item in rows if str(item.get("formula") or "UNRESOLVED") == formula):
            lines.append("| " + " | ".join(_markdown_value(row.get(key)) for key in (
                "row_id", "scaffold_mode", "request_spp_mode", "feasible_state_count", "solver_status",
                "objective_parity", "sca_status", "reference_match", "space_group_match",
                "crystal_system_match", "volume_error_percent", "workflow_status",
            )) + " |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_run_summary(path: Path, report: TableRunReport, *, dry_run: bool) -> None:
    statuses: dict[str, int] = {}
    for row in report.result_rows:
        status = str(row.get("workflow_status") or "UNKNOWN")
        statuses[status] = statuses.get(status, 0) + 1
    lines = [
        "# Run Summary", "", f"- Input: `{report.input_path}`", f"- Output: `{report.output_root}`",
        f"- Dry run: {'YES' if dry_run else 'NO'}", f"- Rows parsed: {report.rows_parsed}",
        f"- Rows selected: {report.rows_selected}", f"- Summary rows written: {len(report.result_rows)}", "",
        "## Status counts", "",
    ] + [f"- {key}: {value}" for key, value in sorted(statuses.items())]
    lines.extend(["", "QLIP status reports optimization completion. Objective parity reports mathematical execution fidelity. SCA reports structural checks. Reference fields report independent known-structure recovery; these meanings are not interchangeable."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute_table(
    input_path: Path, *, output_root: Path | None = None, only: str | None = None,
    from_row: int = 1, dry_run: bool = False, continue_on_scientific_failure: bool = False,
    resume: bool = False, workflow_fn: Callable[..., Any] | None = None,
    generate_figures: bool = False, vesta_path: str | None = None,
    scaffolds: Path | None | object = _LEGACY_SCAFFOLD_SELECTION,
) -> TableRunReport:
    source = Path(input_path).resolve()
    rows = parse_experiment_table(source)
    destination = Path(output_root).resolve() if output_root else source.parent / "results" / source.stem
    destination.mkdir(parents=True, exist_ok=True)
    selected = [row for index, row in enumerate(rows, start=1) if index >= from_row and (only is None or row.row_id == only)]
    if only is not None and not selected:
        raise TableFormatError(f"--only row_id not found: {only}")
    runner = workflow_fn or run_csp_workflow
    results: list[dict[str, Any]] = []
    software_failure = False
    for row in selected:
        row_dir = destination / "rows" / row.row_id
        row_dir.mkdir(parents=True, exist_ok=True)
        prior_path = row_dir / "result.json"
        prior_detail: dict[str, Any] | None = None
        if resume and not dry_run and prior_path.is_file():
            try:
                prior_detail = json.loads(prior_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                prior_detail = None
        prior_summary = prior_detail.get("summary") if isinstance(prior_detail, dict) else None
        if isinstance(prior_summary, dict) and prior_summary.get("workflow_status") not in {
            "SOFTWARE_FAILURE", "ROW_INPUT_ERROR",
        }:
            summary, detail, halt = prior_summary, prior_detail, False
        elif dry_run:
            summary = dry_run_row(row, row_dir, scaffolds=scaffolds)
            detail = {"summary": summary, "dry_run": True}
            halt = False
        else:
            summary, detail, halt = execute_row(row, row_dir, runner, scaffolds=scaffolds)
        if not dry_run and generate_figures:
            if summary.get("cif_generated") == "YES" and row.execution_mode == "canonical":
                try:
                    from sok_llm_orchestrator.workflow.row_visualization import build_row_workflow_figure

                    figure = build_row_workflow_figure(
                        summary, row_dir, destination / "figures", vesta_path=vesta_path,
                    )
                    summary["workflow_figure_status"] = "PASS"
                    summary["workflow_figure_png"] = figure["workflow_figure_png"]
                    summary["workflow_figure_pdf"] = figure["workflow_figure_pdf"]
                    summary["workflow_figure_error"] = ""
                    detail["workflow_figure"] = figure
                except Exception as exc:
                    summary["workflow_figure_status"] = "FAIL"
                    summary["workflow_figure_error"] = f"{type(exc).__name__}: {exc}"
                    detail["workflow_figure_error"] = summary["workflow_figure_error"]
                    halt = True
            else:
                summary["workflow_figure_status"] = "NOT_APPLICABLE"
                summary["workflow_figure_error"] = "No successful canonical CIF was emitted."
        write_row_artifacts(row_dir, row, summary, detail)
        results.append(summary)
        if halt:
            software_failure = True
    report = TableRunReport(source, destination, len(rows), len(selected), results, software_failure)
    _write_results_csv(destination / "RESULTS.csv", results)
    write_results_markdown(destination / "RESULTS.md", results)
    write_run_summary(destination / "RUN_SUMMARY.md", report, dry_run=dry_run)
    return report


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run CSV/TSV experiment rows through the canonical CSP workflow")
    value.add_argument("table", type=Path)
    value.add_argument("--output", type=Path)
    value.add_argument("--only")
    value.add_argument("--from-row", type=int, default=1)
    value.add_argument("--dry-run", action="store_true")
    value.add_argument("--resume", action="store_true")
    value.add_argument("--continue-on-scientific-failure", action="store_true")
    value.add_argument("--no-figures", action="store_true", help="Disable automatic per-row workflow figures")
    value.add_argument("--vesta-path", help="Path to the VESTA executable")
    value.add_argument("--scaffolds", type=Path, help="Explicit loose or hard scaffold registry directory; omit for native QLIP")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    args = parser().parse_args(list(argv) if argv is not None else None)
    if args.from_row < 1:
        print("--from-row must be at least 1", file=sys.stderr)
        return 2
    try:
        report = execute_table(
            args.table, output_root=args.output, only=args.only, from_row=args.from_row,
            dry_run=args.dry_run, continue_on_scientific_failure=args.continue_on_scientific_failure,
            resume=args.resume,
            generate_figures=not args.no_figures, vesta_path=args.vesta_path,
            scaffolds=args.scaffolds,
        )
    except (OSError, TableFormatError) as exc:
        print(f"TABLE_INPUT_ERROR: {exc}", file=sys.stderr)
        return 2
    for row in report.result_rows:
        print(
            f"{row['row_id']}: formula={row['formula']} scaffold={row['scaffold_mode']} "
            f"request_spp={row['request_spp_mode']} corpus={row['resolved_corpus']} "
            f"states={row['feasible_state_count'] or '—'} status={row['workflow_status']}"
        )
    print(f"Wrote {len(report.result_rows)} result rows to {report.output_root}")
    return 1 if report.software_failure or any(row["workflow_status"] == "OBJECTIVE_PARITY_FAILURE" for row in report.result_rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
