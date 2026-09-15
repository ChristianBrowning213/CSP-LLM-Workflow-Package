"""Reusable benchmark orchestration for generated crystal structures."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pymatgen.core import Structure
from tqdm import tqdm

from sca.evaluators.pre_dft_validity import PreDftValidityBenchmarkEvaluator
from sca.evaluators.registry import create_evaluator
from sca.evaluators.uniqueness import assign_duplicate_groups
from sca.io import discover_cif_files, load_manifest_frame, resolve_manifest_path
from sca.pipelines.crystallm_style import evaluate_one_cif
from sca.scoring import compute_rank_score
from sca.schemas import BenchmarkEvaluatorResult, BenchmarkRecord, CrystalEvalRecord


def benchmark_one(
    cif_path: str | Path,
    evaluator_names: list[str] | None = None,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    target_cif_path: str | Path | None = None,
    reference_id: str | None = None,
    structure_match_mode: str = "both",
    spp_artifact: str | Path | None = None,
    hull_reference_path: str | Path | None = None,
    target_formation_energy_per_atom: float | None = None,
    target_energy_above_hull: float | None = None,
    target_band_gap: float | None = None,
    target_property_name: str | None = None,
    target_property_value: float | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Structure] | None = None,
) -> BenchmarkRecord:
    records = benchmark_paths(
        [Path(cif_path)],
        evaluator_names=evaluator_names,
        target_formula=target_formula,
        target_space_group=target_space_group,
        target_cif_path=target_cif_path,
        reference_id=reference_id,
        structure_match_mode=structure_match_mode,
        spp_artifact=spp_artifact,
        hull_reference_path=hull_reference_path,
        target_formation_energy_per_atom=target_formation_energy_per_atom,
        target_energy_above_hull=target_energy_above_hull,
        target_band_gap=target_band_gap,
        target_property_name=target_property_name,
        target_property_value=target_property_value,
        method=method,
        query_id=query_id,
        require_spacegroup=require_spacegroup,
        run_alignn=run_alignn,
        reference_structures=reference_structures,
        show_progress=False,
    )
    return records[0]


def benchmark_folder(
    folder_path: str | Path,
    evaluator_names: list[str] | None = None,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    target_cif_path: str | Path | None = None,
    reference_id: str | None = None,
    structure_match_mode: str = "both",
    spp_artifact: str | Path | None = None,
    hull_reference_path: str | Path | None = None,
    target_formation_energy_per_atom: float | None = None,
    target_energy_above_hull: float | None = None,
    target_band_gap: float | None = None,
    target_property_name: str | None = None,
    target_property_value: float | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    recursive: bool = True,
    reference_structures: dict[str, Structure] | None = None,
) -> list[BenchmarkRecord]:
    paths = discover_cif_files(folder_path, recursive=recursive)
    return benchmark_paths(
        paths,
        evaluator_names=evaluator_names,
        target_formula=target_formula,
        target_space_group=target_space_group,
        target_cif_path=target_cif_path,
        reference_id=reference_id,
        structure_match_mode=structure_match_mode,
        spp_artifact=spp_artifact,
        hull_reference_path=hull_reference_path,
        target_formation_energy_per_atom=target_formation_energy_per_atom,
        target_energy_above_hull=target_energy_above_hull,
        target_band_gap=target_band_gap,
        target_property_name=target_property_name,
        target_property_value=target_property_value,
        method=method,
        query_id=query_id,
        require_spacegroup=require_spacegroup,
        run_alignn=run_alignn,
        reference_structures=reference_structures,
    )


def benchmark_manifest(
    manifest_csv: str | Path,
    evaluator_names: list[str] | None = None,
    path_col: str = "cif_path",
    formula_col: str | None = None,
    spacegroup_col: str | None = None,
    target_cif_col: str | None = None,
    reference_id_col: str | None = None,
    method_col: str | None = None,
    query_id_col: str | None = None,
    structure_match_mode: str = "both",
    spp_artifact: str | Path | None = None,
    hull_reference_path: str | Path | None = None,
    target_formation_energy_col: str | None = "target_formation_energy_per_atom",
    target_energy_above_hull_col: str | None = "target_energy_above_hull",
    target_band_gap_col: str | None = "target_band_gap",
    target_property_name_col: str | None = "target_property_name",
    target_property_value_col: str | None = "target_property_value",
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Structure] | None = None,
) -> list[BenchmarkRecord]:
    frame = load_manifest_frame(manifest_csv, path_col)
    items = []
    for _, row in frame.iterrows():
        items.append(
            {
                "path": Path(str(row[path_col])),
                "target_formula": _optional_cell(row, formula_col, frame.columns),
                "target_space_group": _optional_cell(row, spacegroup_col, frame.columns),
                "target_cif_path": _optional_path_cell(row, target_cif_col, frame.columns, manifest_csv)
                or _optional_path_cell(row, "reference_cif_path", frame.columns, manifest_csv),
                "reference_id": _optional_cell(row, reference_id_col, frame.columns)
                or _optional_cell(row, "target_reference_id", frame.columns),
                "structure_match_mode": structure_match_mode,
                "spp_artifact": _row_path_or_global(
                    row, "spp_artifact", frame.columns, manifest_csv, spp_artifact
                ),
                "hull_reference_path": _row_path_or_global(
                    row, "hull_reference_path", frame.columns, manifest_csv, hull_reference_path
                ),
                "traceable_bundle_dir": _optional_path_cell(
                    row, "traceable_bundle_dir", frame.columns, manifest_csv
                ),
                "topology_policy": _optional_cell(row, "topology_policy", frame.columns),
                "target_formation_energy_per_atom": _optional_float_cell(row, target_formation_energy_col, frame.columns),
                "target_energy_above_hull": _optional_float_cell(row, target_energy_above_hull_col, frame.columns),
                "target_band_gap": _optional_float_cell(row, target_band_gap_col, frame.columns),
                "target_property_name": _optional_cell(row, target_property_name_col, frame.columns),
                "target_property_value": _optional_float_cell(row, target_property_value_col, frame.columns),
                "method": _optional_cell(row, method_col, frame.columns),
                "query_id": _optional_cell(row, query_id_col, frame.columns),
                "extra_context": _manifest_extra_context(row, frame.columns, path_col),
            }
        )
    return benchmark_items(
        items,
        evaluator_names=evaluator_names,
        require_spacegroup=require_spacegroup,
        run_alignn=run_alignn,
        reference_structures=reference_structures,
    )


def benchmark_paths(
    paths: list[Path],
    evaluator_names: list[str] | None = None,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    target_cif_path: str | Path | None = None,
    reference_id: str | None = None,
    structure_match_mode: str = "both",
    spp_artifact: str | Path | None = None,
    hull_reference_path: str | Path | None = None,
    target_formation_energy_per_atom: float | None = None,
    target_energy_above_hull: float | None = None,
    target_band_gap: float | None = None,
    target_property_name: str | None = None,
    target_property_value: float | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Structure] | None = None,
    show_progress: bool = True,
) -> list[BenchmarkRecord]:
    items = [
        {
            "path": Path(path),
            "target_formula": target_formula,
            "target_space_group": target_space_group,
            "target_cif_path": str(target_cif_path) if target_cif_path else None,
            "reference_id": reference_id,
            "structure_match_mode": structure_match_mode,
            "spp_artifact": str(spp_artifact) if spp_artifact else None,
            "hull_reference_path": str(hull_reference_path) if hull_reference_path else None,
            "target_formation_energy_per_atom": target_formation_energy_per_atom,
            "target_energy_above_hull": target_energy_above_hull,
            "target_band_gap": target_band_gap,
            "target_property_name": target_property_name,
            "target_property_value": target_property_value,
            "method": method,
            "query_id": query_id,
        }
        for path in paths
    ]
    return benchmark_items(
        items,
        evaluator_names=evaluator_names,
        require_spacegroup=require_spacegroup,
        run_alignn=run_alignn,
        reference_structures=reference_structures,
        show_progress=show_progress,
    )


def benchmark_items(
    items: list[dict],
    evaluator_names: list[str] | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Structure] | None = None,
    show_progress: bool = True,
) -> list[BenchmarkRecord]:
    evaluator_names = evaluator_names or ["pre_dft_validity"]
    run_id = str(uuid4())
    pre_dft_records: list[CrystalEvalRecord | None] = []
    structures: dict[str, Structure] = {}

    iterator = tqdm(items, desc="Benchmarking CIFs", disable=not show_progress)
    for item in iterator:
        if "pre_dft_validity" not in evaluator_names:
            pre_dft_records.append(None)
            continue
        record, structure = evaluate_one_cif(
            item["path"],
            target_formula=item.get("target_formula"),
            target_space_group=item.get("target_space_group"),
            method=item.get("method"),
            query_id=item.get("query_id"),
            require_spacegroup=require_spacegroup,
            run_alignn=run_alignn,
            reference_structures=reference_structures,
            run_id=run_id,
        )
        pre_dft_records.append(record)
        if structure is not None:
            structures[record.input_path] = structure

    finalized_pre_dft = _finalize_pre_dft(pre_dft_records, structures)
    other_evaluators = {}
    row_evaluators = {}
    evaluator_create_errors = {}
    for name in evaluator_names:
        if name == "pre_dft_validity":
            continue
        try:
            evaluator = create_evaluator(name)
            if hasattr(evaluator, "evaluate_row"):
                row_evaluators[name] = evaluator
            else:
                other_evaluators[name] = evaluator
        except Exception as exc:
            evaluator_create_errors[name] = exc
    pre_dft_evaluator = PreDftValidityBenchmarkEvaluator()
    benchmark_records: list[BenchmarkRecord] = []

    for item, pre_dft_record in zip(items, finalized_pre_dft, strict=True):
        path = Path(item["path"])
        outputs = {}
        flattened = {}
        error_type = None
        error_message = None

        if pre_dft_record is not None:
            outputs["pre_dft_validity"] = pre_dft_evaluator.from_record(pre_dft_record)
            flattened.update(pre_dft_record.to_row())
            error_type = pre_dft_record.error_type
            error_message = pre_dft_record.error_message
        _add_item_context(flattened, item)

        for name, exc in evaluator_create_errors.items():
            result = _structured_evaluator_error(name, exc, skipped=True)
            outputs[name] = result
            _flatten_evaluator_metrics(flattened, name, result)

        for name, evaluator in other_evaluators.items():
            result = _evaluate_other_evaluator(name, evaluator, item)
            outputs[name] = result
            _flatten_evaluator_metrics(flattened, name, result)

        for name, evaluator in sorted(row_evaluators.items(), key=lambda item: _row_evaluator_order(item[0])):
            result = _evaluate_row_evaluator(name, evaluator, flattened)
            outputs[name] = result
            _flatten_evaluator_metrics(flattened, name, result)

        flattened["rediscovery_label"] = _rediscovery_label(flattened)
        flattened["benchmark_rank_score"] = _benchmark_rank_score(flattened)

        benchmark_records.append(
            BenchmarkRecord(
                run_id=run_id,
                method=item.get("method"),
                query_id=item.get("query_id"),
                input_path=str(path),
                file_name=path.name,
                evaluator_outputs=outputs,
                flattened=flattened,
                error_type=error_type,
                error_message=error_message,
            )
        )

    return benchmark_records


def _finalize_pre_dft(
    records: list[CrystalEvalRecord | None],
    structures: dict[str, Structure],
) -> list[CrystalEvalRecord | None]:
    present = [record for record in records if record is not None]
    if present:
        finalized_by_path = {
            record.input_path: record.model_copy(update={"pre_dft_rank_score": compute_rank_score(record)})
            for record in assign_duplicate_groups(present, structures)
        }
        return [
            finalized_by_path.get(record.input_path) if record is not None else None
            for record in records
        ]
    return records


def _optional_cell(row, column: str | None, columns) -> str | None:
    if not column or column not in columns:
        return None
    value = row[column]
    if value is None or str(value).lower() == "nan" or str(value).strip() == "":
        return None
    return str(value)


def _optional_float_cell(row, column: str | None, columns) -> float | None:
    value = _optional_cell(row, column, columns)
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _optional_path_cell(row, column: str | None, columns, manifest_csv: str | Path) -> str | None:
    value = _optional_cell(row, column, columns)
    if value is None:
        return None
    return str(resolve_manifest_path(value, manifest_csv))


def _row_path_or_global(
    row,
    column: str,
    columns,
    manifest_csv: str | Path,
    global_value: str | Path | None,
) -> str | None:
    """Resolve a row-specific artifact path, falling back to a CLI/global value."""

    row_value = _optional_path_cell(row, column, columns, manifest_csv)
    if row_value is not None:
        return row_value
    return str(global_value) if global_value else None


def _add_item_context(flattened: dict, item: dict) -> None:
    flattened.setdefault("input_path", str(item["path"]))
    for key, value in (item.get("extra_context") or {}).items():
        if value is not None and str(value).strip() != "":
            flattened.setdefault(key, value)
    for key in (
        "benchmark_id",
        "benchmark_group",
        "attempt_id",
        "target_structure_family",
        "target_crystal_system",
        "paper_source",
        "paper_name",
        "prompt",
        "reference_cif_path",
        "reference_id",
        "reference_source",
        "target_formation_energy_per_atom",
        "target_energy_above_hull",
        "target_band_gap",
        "target_property_name",
        "target_property_value",
        "hull_reference_path",
        "spp_artifact",
        "traceable_bundle_dir",
        "topology_policy",
    ):
        value = item.get(key)
        if value is not None:
            flattened[key] = value


def _manifest_extra_context(row, columns, path_col: str) -> dict:
    excluded = {path_col}
    context = {}
    for column in columns:
        if column in excluded:
            continue
        value = row[column]
        if value is None or str(value).lower() == "nan" or str(value).strip() == "":
            continue
        context[str(column)] = value
    return context


def _evaluate_other_evaluator(name: str, evaluator, item: dict) -> BenchmarkEvaluatorResult:
    try:
        if hasattr(evaluator, "evaluate_item"):
            return evaluator.evaluate_item(item)
        return evaluator.evaluate_path(item["path"])
    except Exception as exc:
        return _structured_evaluator_error(name, exc)


def _evaluate_row_evaluator(name: str, evaluator, row: dict) -> BenchmarkEvaluatorResult:
    try:
        return evaluator.evaluate_row(row)
    except Exception as exc:
        return _structured_evaluator_error(name, exc)


def _row_evaluator_order(name: str) -> int:
    order = {"predicted_hull": 10, "property_targets": 20, "mlip_ensemble": 30}
    return order.get(name, 100)


def _flatten_evaluator_metrics(
    flattened: dict,
    name: str,
    result: BenchmarkEvaluatorResult,
) -> None:
    for key, value in result.metrics.items():
        flattened.setdefault(key, value)
        flattened[f"{name}_{key}"] = value


def _structured_evaluator_error(
    name: str,
    exc: Exception,
    skipped: bool = False,
) -> BenchmarkEvaluatorResult:
    return BenchmarkEvaluatorResult(
        name=name,
        ok=False,
        skipped=skipped,
        summary="unavailable" if skipped else "failed",
        error_type=type(exc).__name__,
        error_message=str(exc),
    )


def _rediscovery_label(row: dict) -> str:
    if row.get("parse_ok") is False:
        return "invalid"
    if _as_bool(row.get("novelty_checked")) is not True:
        return "valid_reference_not_checked"
    if _as_bool(row.get("known_match")) is True:
        return "valid_known_match"
    if _as_bool(row.get("novel_by_structure_matcher")) is True:
        return "valid_novel"
    return "valid_unknown"


def _as_bool(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _benchmark_rank_score(row: dict) -> float:
    score = 0.0
    if _as_bool(row.get("parse_ok")) is not True:
        score += 10_000.0
    if _as_bool(row.get("pre_dft_valid")) is False:
        score += 1_000.0
    if _as_bool(row.get("target_formula_match")) is False:
        score += 500.0
    if _as_bool(row.get("structure_match")) is False:
        score += 250.0
    if row.get("rediscovery_label") == "valid_known_match":
        score += 100.0
    if _as_bool(row.get("is_duplicate")) is True:
        score += 50.0
    spp_score = _as_float(row.get("spp_score_per_atom"))
    if spp_score is not None:
        score += spp_score
    energy = _first_float(
        row,
        (
            "mlip_energy_mean",
            "chgnet_energy_per_atom",
            "m3gnet_energy_per_atom",
            "mace_energy_per_atom",
            "sevennet_energy_per_atom",
            "formation_energy_per_atom",
        ),
    )
    if energy is not None:
        score += energy
    if _as_bool(row.get("mlip_disagreement_flag")) is True:
        score += 25.0
    hull = _as_float(row.get("predicted_energy_above_hull"))
    if hull is not None:
        score += hull
    property_error = _as_float(row.get("property_error"))
    if property_error is not None:
        score += abs(property_error)
    return float(score)


def _first_float(row: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _as_float(row.get(key))
        if value is not None:
            return value
    return None


def _as_float(value) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
