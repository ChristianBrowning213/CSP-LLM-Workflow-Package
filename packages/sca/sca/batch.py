"""Batch evaluation orchestration."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from pymatgen.core import Structure
from tqdm import tqdm

from sca.evaluators.base import CrystalEvaluator
from sca.evaluators.uniqueness import assign_duplicate_groups
from sca.io import discover_cif_files, load_manifest_frame, parse_cif
from sca.pipelines.crystallm_style import evaluate_one_cif
from sca.scoring import compute_rank_score
from sca.schemas import CrystalEvalRecord, CrystalEvaluationResult


def evaluate_one(path: str | Path, evaluator: CrystalEvaluator) -> CrystalEvaluationResult:
    """Original ALIGNN-only one-file helper retained for compatibility."""

    metadata, structure = parse_cif(path)
    if structure is None:
        return CrystalEvaluationResult.from_parts(metadata)

    evaluator_result = evaluator.evaluate(structure, metadata.input_path)
    return CrystalEvaluationResult.from_parts(metadata, evaluator_result)


def evaluate_many(
    paths,
    evaluator: CrystalEvaluator,
    show_progress: bool = True,
) -> list[CrystalEvaluationResult]:
    path_list = [Path(path) for path in paths]
    iterator = tqdm(path_list, desc="Evaluating CIFs", disable=not show_progress)
    return [evaluate_one(path, evaluator) for path in iterator]


def evaluate_folder(
    folder_path: str | Path,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    recursive: bool = True,
    reference_structures: dict[str, Structure] | None = None,
) -> list[CrystalEvalRecord]:
    paths = discover_cif_files(folder_path, recursive=recursive)
    run_id = str(uuid4())
    records: list[CrystalEvalRecord] = []
    structures: dict[str, Structure] = {}

    for path in tqdm(paths, desc="Evaluating CIFs"):
        record, structure = evaluate_one_cif(
            path,
            target_formula=target_formula,
            target_space_group=target_space_group,
            method=method,
            query_id=query_id,
            require_spacegroup=require_spacegroup,
            run_alignn=run_alignn,
            reference_structures=reference_structures,
            run_id=run_id,
        )
        records.append(record)
        if structure is not None:
            structures[record.input_path] = structure

    return _finalize_duplicate_groups(records, structures)


def evaluate_manifest(
    manifest_csv: str | Path,
    path_col: str = "cif_path",
    formula_col: str | None = None,
    spacegroup_col: str | None = None,
    method_col: str | None = None,
    query_id_col: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Structure] | None = None,
) -> list[CrystalEvalRecord]:
    frame = load_manifest_frame(manifest_csv, path_col)
    run_id = str(uuid4())
    records: list[CrystalEvalRecord] = []
    structures: dict[str, Structure] = {}

    for _, row in tqdm(list(frame.iterrows()), desc="Evaluating CIFs"):
        path = Path(str(row[path_col]))
        record, structure = evaluate_one_cif(
            path,
            target_formula=_optional_cell(row, formula_col, frame.columns),
            target_space_group=_optional_cell(row, spacegroup_col, frame.columns),
            method=_optional_cell(row, method_col, frame.columns),
            query_id=_optional_cell(row, query_id_col, frame.columns),
            require_spacegroup=require_spacegroup,
            run_alignn=run_alignn,
            reference_structures=reference_structures,
            run_id=run_id,
        )
        records.append(record)
        if structure is not None:
            structures[record.input_path] = structure

    return _finalize_duplicate_groups(records, structures)


def _finalize_duplicate_groups(
    records: list[CrystalEvalRecord],
    structures: dict[str, Structure],
) -> list[CrystalEvalRecord]:
    records = assign_duplicate_groups(records, structures)
    return [
        record.model_copy(update={"pre_dft_rank_score": compute_rank_score(record)})
        for record in records
    ]


def _optional_cell(row, column: str | None, columns) -> str | None:
    if not column or column not in columns:
        return None
    value = row[column]
    if value is None or str(value).lower() == "nan" or str(value).strip() == "":
        return None
    return str(value)
