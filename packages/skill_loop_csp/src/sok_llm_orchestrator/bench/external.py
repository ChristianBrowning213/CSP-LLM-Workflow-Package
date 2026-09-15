from __future__ import annotations

import copy
import hashlib
import importlib
import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.optimization.backend_sensitivity import objective_audit_from_run_dir
from sok_llm_orchestrator.optimization.loop import OptimizationEngine
from sok_llm_orchestrator.optimization.reporting import regenerate_report_from_session_artifacts
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline
from sok_llm_orchestrator.verification.qlip_outputs import structure_signature_from_cif_path

EXTERNAL_DATASETS = ("mp_20", "perov_5", "mpts_52")
EXTERNAL_SPLITS = ("train", "val", "test")
EXTERNAL_REGIMES = (
    "qlip_baseline",
    "qlip_fixed_spp",
    "qlip_retrieval_spp",
    "qlip_full_orchestrator",
)


@dataclass(slots=True)
class ExternalDatasetLayout:
    dataset: str
    raw_dir: Path
    normalized_dir: Path
    raw_split_paths: dict[str, Path]
    normalized_split_paths: dict[str, Path]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _norm_text(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return "\n".join(lines)


def _text_signature(value: str) -> str:
    return hashlib.sha256(_norm_text(value).encode("utf-8")).hexdigest()


def _safe_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def resolve_external_dataset_layout(dataset: str, *, repo_root: Path | None = None) -> ExternalDatasetLayout:
    name = str(dataset).strip().lower()
    if name not in EXTERNAL_DATASETS:
        raise ValueError(f"Unsupported external dataset '{dataset}'. Expected one of: {', '.join(EXTERNAL_DATASETS)}.")
    root = repo_root.resolve() if repo_root is not None else _repo_root()
    dataset_root = root / "benchmarks" / "external" / name
    raw_dir = dataset_root / "raw"
    normalized_dir = dataset_root / "normalized"
    raw_split_paths = {split: raw_dir / f"{split}.lmdb" for split in EXTERNAL_SPLITS}
    normalized_split_paths = {split: normalized_dir / f"{split}.jsonl" for split in EXTERNAL_SPLITS}
    return ExternalDatasetLayout(
        dataset=name,
        raw_dir=raw_dir,
        normalized_dir=normalized_dir,
        raw_split_paths=raw_split_paths,
        normalized_split_paths=normalized_split_paths,
    )


def _import_lmdb_module() -> Any:
    try:
        return importlib.import_module("lmdb")
    except ModuleNotFoundError as exc:  # pragma: no cover - import error path is environment-dependent
        raise RuntimeError(
            "Missing optional dependency 'lmdb'. Install it to import staged external benchmark datasets."
        ) from exc


def _decode_lmdb_value(value: bytes) -> dict[str, Any]:
    try:
        parsed_json = json.loads(value.decode("utf-8"))
        if isinstance(parsed_json, dict):
            return parsed_json
    except Exception:
        pass
    parsed = pickle.loads(value)
    if isinstance(parsed, dict):
        return parsed
    if hasattr(parsed, "to_dict") and callable(parsed.to_dict):
        candidate = parsed.to_dict()
        if isinstance(candidate, dict):
            return candidate
    raise ValueError(f"Unsupported LMDB record type: {type(parsed)}")


def _iter_lmdb_records(path: Path) -> list[tuple[str, dict[str, Any]]]:
    lmdb = _import_lmdb_module()
    env = lmdb.open(str(path), subdir=False, readonly=True, lock=False, readahead=False, max_readers=1)
    rows: list[tuple[str, dict[str, Any]]] = []
    with env.begin() as txn:
        cursor = txn.cursor()
        for raw_key, raw_value in cursor:
            key = raw_key.decode("utf-8", errors="replace")
            try:
                payload = _decode_lmdb_value(raw_value)
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"Failed to decode LMDB record key={key} from {path}: {exc}") from exc
            rows.append((key, payload))
    env.close()
    return rows


_ATOMIC_SYMBOLS = (
    "",
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
)


def _symbol_for_atomic_number(number: int) -> str | None:
    if number <= 0 or number >= len(_ATOMIC_SYMBOLS):
        return None
    value = _ATOMIC_SYMBOLS[number]
    return value if value else None


def _to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist") and callable(value.tolist):
        converted = value.tolist()
        return converted if isinstance(converted, list) else list(converted)
    return []


def _formula_from_atomic_numbers(value: Any) -> str | None:
    atomic = _to_list(value)
    if not atomic:
        return None
    counts: dict[str, int] = {}
    for item in atomic:
        if hasattr(item, "item") and callable(item.item):
            item = item.item()
        if not isinstance(item, int):
            try:
                item = int(item)
            except (TypeError, ValueError):
                return None
        symbol = _symbol_for_atomic_number(item)
        if symbol is None:
            return None
        counts[symbol] = counts.get(symbol, 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: pair[0])
    return "".join(f"{sym}{count if count > 1 else ''}" for sym, count in ordered)


def _extract_identifier(record: dict[str, Any]) -> str | None:
    for key in ("case_id", "identifier", "ids", "material_id", "mp_id", "id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in ("identifier", "ids", "material_id", "mp_id", "id"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _extract_composition(record: dict[str, Any]) -> str:
    for key in (
        "composition",
        "formula",
        "pretty_formula",
        "reduced_formula",
        "chemical_formula",
        "formula_pretty",
    ):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "composition",
            "formula",
            "pretty_formula",
            "reduced_formula",
            "chemical_formula",
            "formula_pretty",
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    formula = _formula_from_atomic_numbers(record.get("atomic_numbers"))
    if isinstance(formula, str) and formula:
        return formula
    return "UNKNOWN"


def _matrix_3x3(value: Any) -> list[list[float]] | None:
    rows = _to_list(value)
    if len(rows) != 3:
        return None
    out: list[list[float]] = []
    for row in rows:
        values = _to_list(row)
        if len(values) != 3:
            return None
        parsed: list[float] = []
        for item in values:
            if hasattr(item, "item") and callable(item.item):
                item = item.item()
            if not isinstance(item, (int, float)):
                try:
                    item = float(item)
                except (TypeError, ValueError):
                    return None
            parsed.append(float(item))
        out.append(parsed)
    return out


def _positions(value: Any) -> list[list[float]] | None:
    rows = _to_list(value)
    if not rows:
        return None
    out: list[list[float]] = []
    for row in rows:
        values = _to_list(row)
        if len(values) != 3:
            return None
        parsed: list[float] = []
        for item in values:
            if hasattr(item, "item") and callable(item.item):
                item = item.item()
            if not isinstance(item, (int, float)):
                try:
                    item = float(item)
                except (TypeError, ValueError):
                    return None
            parsed.append(float(item))
        out.append(parsed)
    return out


def _cif_from_structure_arrays(record: dict[str, Any]) -> str | None:
    cell = _matrix_3x3(record.get("cell"))
    atomic_numbers = _to_list(record.get("atomic_numbers"))
    pos = _positions(record.get("frac_coords")) or _positions(record.get("pos"))
    if cell is None or not atomic_numbers or pos is None or len(pos) != len(atomic_numbers):
        return None
    try:
        from pymatgen.core import Lattice, Structure
        from pymatgen.io.cif import CifWriter
    except Exception:  # pragma: no cover - optional dependency path
        return None

    species: list[str] = []
    for item in atomic_numbers:
        if hasattr(item, "item") and callable(item.item):
            item = item.item()
        if not isinstance(item, int):
            item = int(item)
        species.append(_symbol_for_atomic_number(item) or f"X{item}")

    max_abs = max(abs(coord) for row in pos for coord in row)
    coords_are_cartesian = max_abs > 1.2
    structure = Structure(
        lattice=Lattice(cell),
        species=species,
        coords=pos,
        coords_are_cartesian=coords_are_cartesian,
        to_unit_cell=True,
    )
    cif = str(CifWriter(structure))
    if cif.strip():
        return cif
    return None


def _placeholder_cif(*, composition: str, case_id: str) -> str:
    safe_id = case_id.replace(" ", "_")
    comp = composition if composition else "UNKNOWN"
    return (
        f"data_{safe_id}\n"
        f"_chemical_formula_sum '{comp}'\n"
        "# source_cif_unavailable_in_lmdb_record\n"
    )


def _extract_cif(record: dict[str, Any], *, composition: str, case_id: str) -> str:
    for key in ("cif", "cif_str", "cif_string", "target_cif", "structure_cif"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value
    structure = record.get("structure")
    if isinstance(structure, dict):
        for key in ("cif", "cif_str", "cif_string"):
            value = structure.get(key)
            if isinstance(value, str) and value.strip():
                return value
    generated = _cif_from_structure_arrays(record)
    if isinstance(generated, str) and generated.strip():
        return generated
    return _placeholder_cif(composition=composition, case_id=case_id)


def _normalized_case_id(dataset: str, split: str, index: int, identifier: str | None) -> str:
    if isinstance(identifier, str) and identifier.strip():
        token = identifier.strip().replace(" ", "_")
        return f"{dataset}_{split}_{token}"
    return f"{dataset}_{split}_{index:06d}"


def _normalize_lmdb_record(
    *,
    dataset: str,
    split: str,
    index: int,
    source_key: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    identifier = _extract_identifier(record)
    composition = _extract_composition(record)
    case_id = _normalized_case_id(dataset, split, index, identifier)
    cif = _extract_cif(record, composition=composition, case_id=case_id)
    metadata: dict[str, Any] = {
        "source_key": source_key,
        "identifier": identifier,
        "source_record_keys": sorted(record.keys()),
        "reference_cif_signature": _text_signature(cif),
    }
    return {
        "benchmark_dataset": dataset,
        "split": split,
        "case_id": case_id,
        "composition": composition,
        "cif": cif,
        "source_metadata": metadata,
    }


def import_external_dataset(
    *,
    dataset: str,
    repo_root: Path | None = None,
    max_records_per_split: int | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    layout = resolve_external_dataset_layout(dataset, repo_root=repo_root)
    missing = [str(path) for path in layout.raw_split_paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing raw LMDB split files for dataset '{dataset}': {missing}. "
            "Expected train/val/test under benchmarks/external/<dataset>/raw/."
        )
    layout.normalized_dir.mkdir(parents=True, exist_ok=True)
    split_counts: dict[str, int] = {}
    normalized_paths: dict[str, str] = {}
    for split in EXTERNAL_SPLITS:
        output_path = layout.normalized_split_paths[split]
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"Normalized split already exists: {output_path}")
        records = _iter_lmdb_records(layout.raw_split_paths[split])
        rows: list[dict[str, Any]] = []
        for index, (source_key, record) in enumerate(records):
            if isinstance(max_records_per_split, int) and max_records_per_split >= 0 and index >= max_records_per_split:
                break
            rows.append(
                _normalize_lmdb_record(
                    dataset=layout.dataset,
                    split=split,
                    index=index,
                    source_key=source_key,
                    record=record,
                )
            )
        with output_path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        split_counts[split] = len(rows)
        normalized_paths[split] = str(output_path)
    return {
        "schema_version": "benchmark.external.import.v1",
        "dataset": layout.dataset,
        "raw_dir": str(layout.raw_dir),
        "normalized_dir": str(layout.normalized_dir),
        "split_counts": split_counts,
        "normalized_split_paths": normalized_paths,
    }


def import_external_datasets(
    *,
    datasets: list[str] | None = None,
    repo_root: Path | None = None,
    max_records_per_split: int | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    selected = [item.strip().lower() for item in (datasets or list(EXTERNAL_DATASETS)) if item.strip()]
    if not selected:
        selected = list(EXTERNAL_DATASETS)
    summaries: list[dict[str, Any]] = []
    for dataset in selected:
        summaries.append(
            import_external_dataset(
                dataset=dataset,
                repo_root=repo_root,
                max_records_per_split=max_records_per_split,
                overwrite=overwrite,
            )
        )
    return {
        "schema_version": "benchmark.external.import.batch.v1",
        "datasets": selected,
        "imports": summaries,
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _query_for_case(row: dict[str, Any]) -> str:
    dataset = str(row.get("benchmark_dataset", "external"))
    split = str(row.get("split", "unknown"))
    composition = str(row.get("composition", "UNKNOWN"))
    case_id = str(row.get("case_id", "case"))
    return f"{composition} external benchmark case {case_id} dataset {dataset} split {split}"


def _extract_cif_path_from_run_dir(run_dir: Path) -> str | None:
    solve_payload = _safe_json(run_dir / "artifacts" / "qlip_solve.json")
    if not isinstance(solve_payload, dict):
        return None
    result = solve_payload.get("result", solve_payload)
    nested = result.get("result", result) if isinstance(result, dict) else {}
    outputs = nested.get("outputs", {}) if isinstance(nested, dict) else {}
    cif = outputs.get("cif") if isinstance(outputs, dict) else None
    if isinstance(cif, str) and cif.strip():
        return cif
    fallback = result.get("cif_path") if isinstance(result, dict) else None
    return fallback if isinstance(fallback, str) and fallback.strip() else None


def _extract_property_x_from_run_dir(run_dir: Path) -> float | None:
    solve_payload = _safe_json(run_dir / "artifacts" / "qlip_solve.json")
    if not isinstance(solve_payload, dict):
        return None
    result = solve_payload.get("result", solve_payload)
    nested = result.get("result", result) if isinstance(result, dict) else {}
    outputs = nested.get("outputs", {}) if isinstance(nested, dict) else {}
    estimates = outputs.get("property_estimates", {}) if isinstance(outputs, dict) else {}
    if isinstance(estimates, dict):
        value = estimates.get("property_x")
        if isinstance(value, (int, float)):
            return float(value)
    summary = nested.get("summary", {}) if isinstance(nested, dict) else {}
    value = summary.get("property_x") if isinstance(summary, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def _verification_ok(run_dir: Path) -> bool:
    verification = _safe_json(run_dir / "artifacts" / "verification_report.json")
    if isinstance(verification, dict) and "ok" in verification:
        return bool(verification.get("ok"))
    return False


def _regime_overrides(regime: str) -> tuple[bool, dict[str, Any] | None]:
    if regime == "qlip_baseline":
        return False, {"guidance_mode": "none", "use_spp": False}
    if regime == "qlip_fixed_spp":
        return True, {
            "retrieval_mode": "text",
            "retrieval_candidate_k": 1,
            "corpus_strategy": "top_k",
            "corpus_top_k": 1,
            "corpus_strategy_candidates": ["top_k"],
            "corpus_top_k_candidates": [1],
            "spp_package_alternatives": ["default"],
            "spp_package_variant": "default",
            "weighting_profile": "balanced",
            "structure_perturbation_profile": "minimal",
        }
    if regime == "qlip_retrieval_spp":
        return True, {
            "retrieval_mode": "hybrid",
            "retrieval_candidate_k": 5,
            "corpus_strategy": "composition_tight",
            "corpus_strategy_candidates": ["composition_tight", "top_k", "property_biased"],
            "corpus_top_k": 4,
            "corpus_top_k_candidates": [3, 4, 6],
            "spp_package_alternatives": ["default", "focus"],
            "weighting_profile": "guidance_dominant",
            "structure_perturbation_profile": "moderate",
        }
    raise ValueError(f"Unsupported non-orchestrator regime: {regime}")


def _pipeline_matrix_row(
    *,
    regime: str,
    mode: str,
    workspace: Path,
    settings: Settings,
    case: dict[str, Any],
    budget: dict[str, Any],
) -> dict[str, Any]:
    with_spp, overrides = _regime_overrides(regime)
    run = run_csp_pipeline(
        query=_query_for_case(case),
        with_spp=with_spp,
        mode=mode,
        workspace=workspace,
        settings=settings,
        execution_overrides=overrides,
    )
    objective_audit = objective_audit_from_run_dir(run.run_dir) or {}
    cif_path = _extract_cif_path_from_run_dir(run.run_dir)
    signature = structure_signature_from_cif_path(cif_path)
    request_payload = _safe_json(run.run_dir / "artifacts" / "qlip_request.json") or {}
    guidance = request_payload.get("guidance", []) if isinstance(request_payload, dict) else []
    guidance_ids = [
        str(item.get("id")) for item in guidance if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    solved_valid = run.status == "SUCCEEDED" and _verification_ok(run.run_dir)
    reference_sig = None
    source_metadata = case.get("source_metadata")
    if isinstance(source_metadata, dict) and isinstance(source_metadata.get("reference_cif_signature"), str):
        reference_sig = str(source_metadata.get("reference_cif_signature"))
    out_sig = signature.get("structure_content_hash")
    rediscovery_match = (
        isinstance(reference_sig, str)
        and isinstance(out_sig, str)
        and reference_sig == out_sig
    )
    return {
        "dataset": case.get("benchmark_dataset"),
        "split": case.get("split"),
        "case_id": case.get("case_id"),
        "composition": case.get("composition"),
        "regime": regime,
        "budget": budget,
        "status": run.status,
        "solved_valid": bool(solved_valid),
        "best_objective_within_budget": (
            float(objective_audit.get("objective_total"))
            if isinstance(objective_audit.get("objective_total"), (int, float))
            else None
        ),
        "structure_diversity_within_budget": 1 if isinstance(signature.get("structure_signature"), str) else 0,
        "structure_signature": signature.get("structure_signature"),
        "structure_artifact_path": cif_path,
        "property_x": _extract_property_x_from_run_dir(run.run_dir),
        "rediscovery_match": rediscovery_match,
        "reference_cif_signature": reference_sig,
        "objective_term_signature": objective_audit.get("objective_terms_signature"),
        "objective_terms_count": (
            len(objective_audit.get("objective_terms", []))
            if isinstance(objective_audit.get("objective_terms"), list)
            else 0
        ),
        "spp_term": (
            float(objective_audit.get("spp_term"))
            if isinstance(objective_audit.get("spp_term"), (int, float))
            else None
        ),
        "request_guidance_ids": guidance_ids,
        "run_reference": {
            "run_id": run.run_id,
            "run_dir": str(run.run_dir),
            "manifest_path": str(run.manifest_path),
        },
    }


def _orchestrator_matrix_row(
    *,
    mode: str,
    workspace: Path,
    settings: Settings,
    case: dict[str, Any],
    max_iterations: int,
    selection_metric_view: str,
    budget: dict[str, Any],
) -> dict[str, Any]:
    case_settings = copy.deepcopy(settings)
    case_settings.optimization_max_iterations = int(max_iterations)
    case_settings.optimization_selection_metric_view = str(selection_metric_view).strip().lower()
    engine = OptimizationEngine(workspace=workspace, settings=case_settings, mode=mode)
    start = engine.start(
        query=_query_for_case(case),
        auto_run=True,
        seed_hint=f"external:{case.get('benchmark_dataset')}:{case.get('split')}:{case.get('case_id')}",
        case_metadata={"case_id": case.get("case_id"), "composition": case.get("composition")},
    )
    report = regenerate_report_from_session_artifacts(start.session_path)
    objective_trace = report.get("objective_audit_trace", [])
    objectives = [
        float(item.get("objective_total"))
        for item in objective_trace
        if isinstance(item, dict) and isinstance(item.get("objective_total"), (int, float))
    ]
    structure_summary = report.get("structure_diversity_summary", {})
    if not isinstance(structure_summary, dict):
        structure_summary = {}
    spp_exploration = report.get("spp_exploration_summary", {})
    if not isinstance(spp_exploration, dict):
        spp_exploration = {}
    diagnostics = report.get("diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    reference_sig = None
    source_metadata = case.get("source_metadata")
    if isinstance(source_metadata, dict) and isinstance(source_metadata.get("reference_cif_signature"), str):
        reference_sig = str(source_metadata.get("reference_cif_signature"))
    best_structure = report.get("best_structure_artifact_path")
    best_sig = structure_signature_from_cif_path(best_structure).get("structure_content_hash")
    rediscovery_match = (
        isinstance(reference_sig, str)
        and isinstance(best_sig, str)
        and reference_sig == best_sig
    )
    solved_valid = (
        isinstance(report.get("iteration_count"), int)
        and int(report.get("iteration_count")) > 0
        and report.get("final_best_score") is not None
    )
    return {
        "dataset": case.get("benchmark_dataset"),
        "split": case.get("split"),
        "case_id": case.get("case_id"),
        "composition": case.get("composition"),
        "regime": "qlip_full_orchestrator",
        "budget": budget,
        "status": report.get("status"),
        "solved_valid": bool(solved_valid),
        "best_objective_within_budget": max(objectives) if objectives else None,
        "structure_diversity_within_budget": (
            int(structure_summary.get("unique_structure_signature_count"))
            if isinstance(structure_summary.get("unique_structure_signature_count"), int)
            else 0
        ),
        "structure_signature": structure_signature_from_cif_path(best_structure).get("structure_signature"),
        "structure_artifact_path": best_structure,
        "property_x": (
            float(report.get("best_so_far", {}).get("reward", {}).get("property_estimate"))
            if isinstance(report.get("best_so_far"), dict)
            and isinstance(report.get("best_so_far", {}).get("reward"), dict)
            and isinstance(report.get("best_so_far", {}).get("reward", {}).get("property_estimate"), (int, float))
            else None
        ),
        "rediscovery_match": rediscovery_match,
        "reference_cif_signature": reference_sig,
        "objective_term_signature": (
            objective_trace[-1].get("objective_terms_signature")
            if objective_trace and isinstance(objective_trace[-1], dict)
            else None
        ),
        "objective_terms_count": (
            len(objective_trace[-1].get("objective_terms", []))
            if objective_trace
            and isinstance(objective_trace[-1], dict)
            and isinstance(objective_trace[-1].get("objective_terms"), list)
            else 0
        ),
        "spp_term": (
            float(objective_trace[-1].get("spp_term"))
            if objective_trace and isinstance(objective_trace[-1], dict) and isinstance(objective_trace[-1].get("spp_term"), (int, float))
            else None
        ),
        "request_guidance_ids": [
            str(item)
            for item in diagnostics.get("spp_exploration_summary", {}).get("unique_guidance_id_values", [])
            if isinstance(item, str)
        ]
        if isinstance(diagnostics.get("spp_exploration_summary"), dict)
        else [],
        "run_reference": {
            "session_id": report.get("session_id"),
            "session_path": str(start.session_path),
            "selection_metric_view": report.get("selection_metric_view"),
            "iteration_count": report.get("iteration_count"),
            "best_action_id": report.get("best_action_id"),
            "best_action_family": report.get("best_action_family"),
        },
        "orchestrator_diagnostics": {
            "branch_switch_count": diagnostics.get("branch_switch_count"),
            "spp_unique_corpus_strategy_count": spp_exploration.get("unique_corpus_strategy_count"),
            "spp_unique_package_variant_count": spp_exploration.get("unique_spp_package_variant_count"),
            "spp_unique_payload_signature_count": spp_exploration.get("unique_spp_payload_signature_count"),
            "richer_exploration_detected": spp_exploration.get("richer_exploration_detected"),
        },
    }


def _matrix_id(
    *,
    datasets: list[str],
    splits: list[str],
    regimes: list[str],
    mode: str,
    max_cases_per_split: int | None,
    max_iterations: int,
    selection_metric_view: str,
) -> str:
    payload = {
        "datasets": sorted(datasets),
        "splits": sorted(splits),
        "regimes": list(regimes),
        "mode": mode,
        "max_cases_per_split": max_cases_per_split,
        "max_iterations": int(max_iterations),
        "selection_metric_view": selection_metric_view,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"external-matrix-{digest}"


def _group_key(row: dict[str, Any]) -> tuple[str, str, str, int]:
    budget = row.get("budget", {})
    max_iter = int(budget.get("max_iterations", 1)) if isinstance(budget, dict) else 1
    return (
        str(row.get("dataset")),
        str(row.get("split")),
        str(row.get("regime")),
        max_iter,
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def build_external_benchmark_report(matrix_raw: dict[str, Any]) -> dict[str, Any]:
    rows = list(matrix_raw.get("rows", [])) if isinstance(matrix_raw.get("rows"), list) else []
    grouped: dict[tuple[str, str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        grouped.setdefault(_group_key(row), []).append(row)

    group_rows: list[dict[str, Any]] = []
    for (dataset, split, regime, max_iter), group in sorted(grouped.items()):
        total = len(group)
        solved = sum(1 for item in group if bool(item.get("solved_valid", False)))
        objectives = [
            float(item["best_objective_within_budget"])
            for item in group
            if isinstance(item.get("best_objective_within_budget"), (int, float))
        ]
        structure_div = [
            float(item["structure_diversity_within_budget"])
            for item in group
            if isinstance(item.get("structure_diversity_within_budget"), (int, float))
        ]
        matches = [bool(item.get("rediscovery_match", False)) for item in group if item.get("rediscovery_match") is not None]
        diagnostics_rows = [
            item.get("orchestrator_diagnostics", {})
            for item in group
            if isinstance(item.get("orchestrator_diagnostics"), dict)
        ]
        branch_counts = [
            int(item.get("branch_switch_count"))
            for item in diagnostics_rows
            if isinstance(item.get("branch_switch_count"), int)
        ]
        corpus_counts = [
            int(item.get("spp_unique_corpus_strategy_count"))
            for item in diagnostics_rows
            if isinstance(item.get("spp_unique_corpus_strategy_count"), int)
        ]
        package_counts = [
            int(item.get("spp_unique_package_variant_count"))
            for item in diagnostics_rows
            if isinstance(item.get("spp_unique_package_variant_count"), int)
        ]
        payload_counts = [
            int(item.get("spp_unique_payload_signature_count"))
            for item in diagnostics_rows
            if isinstance(item.get("spp_unique_payload_signature_count"), int)
        ]
        richer_count = sum(1 for item in diagnostics_rows if bool(item.get("richer_exploration_detected", False)))
        group_rows.append(
            {
                "dataset": dataset,
                "split": split,
                "regime": regime,
                "budget_max_iterations": max_iter,
                "total_cases": total,
                "solved_valid_count": solved,
                "solved_valid_rate": (solved / total) if total else 0.0,
                "mean_best_objective_within_budget": _mean(objectives),
                "mean_structure_diversity_within_budget": _mean(structure_div),
                "rediscovery_match_rate": (_mean([1.0 if m else 0.0 for m in matches]) if matches else None),
                "full_orchestrator_diagnostics": {
                    "mean_branch_switch_count": _mean([float(v) for v in branch_counts]) if branch_counts else None,
                    "mean_spp_unique_corpus_strategy_count": _mean([float(v) for v in corpus_counts]) if corpus_counts else None,
                    "mean_spp_unique_package_variant_count": _mean([float(v) for v in package_counts]) if package_counts else None,
                    "mean_spp_unique_payload_signature_count": _mean([float(v) for v in payload_counts]) if payload_counts else None,
                    "richer_exploration_case_rate": (richer_count / len(diagnostics_rows)) if diagnostics_rows else None,
                }
                if regime == "qlip_full_orchestrator"
                else {},
            }
        )

    return {
        "schema_version": "benchmark.external.matrix.report.v1",
        "matrix_id": matrix_raw.get("matrix_id"),
        "mode": matrix_raw.get("mode"),
        "datasets": list(matrix_raw.get("datasets", [])),
        "splits": list(matrix_raw.get("splits", [])),
        "regimes": list(matrix_raw.get("regimes", [])),
        "budget": dict(matrix_raw.get("budget", {})) if isinstance(matrix_raw.get("budget"), dict) else {},
        "grouped_summary": group_rows,
        "row_count": len(rows),
    }


def regenerate_external_benchmark_report(results_path: Path) -> dict[str, Any]:
    raw = json.loads(results_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("External matrix results payload must be a JSON object.")
    return build_external_benchmark_report(raw)


def compare_external_benchmark_reports(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_rows = left.get("grouped_summary", [])
    right_rows = right.get("grouped_summary", [])
    if not isinstance(left_rows, list):
        left_rows = []
    if not isinstance(right_rows, list):
        right_rows = []
    left_map = {
        (str(row.get("dataset")), str(row.get("split")), str(row.get("regime")), int(row.get("budget_max_iterations", 1))): row
        for row in left_rows
        if isinstance(row, dict)
    }
    right_map = {
        (str(row.get("dataset")), str(row.get("split")), str(row.get("regime")), int(row.get("budget_max_iterations", 1))): row
        for row in right_rows
        if isinstance(row, dict)
    }
    keys = sorted(set(left_map.keys()) | set(right_map.keys()))
    deltas: list[dict[str, Any]] = []
    for key in keys:
        left_row = left_map.get(key, {})
        right_row = right_map.get(key, {})
        left_solved = float(left_row.get("solved_valid_rate", 0.0)) if isinstance(left_row.get("solved_valid_rate"), (int, float)) else 0.0
        right_solved = float(right_row.get("solved_valid_rate", 0.0)) if isinstance(right_row.get("solved_valid_rate"), (int, float)) else 0.0
        left_obj = left_row.get("mean_best_objective_within_budget")
        right_obj = right_row.get("mean_best_objective_within_budget")
        left_div = left_row.get("mean_structure_diversity_within_budget")
        right_div = right_row.get("mean_structure_diversity_within_budget")
        deltas.append(
            {
                "dataset": key[0],
                "split": key[1],
                "regime": key[2],
                "budget_max_iterations": key[3],
                "delta_solved_valid_rate": right_solved - left_solved,
                "delta_mean_best_objective_within_budget": (
                    float(right_obj) - float(left_obj)
                    if isinstance(left_obj, (int, float)) and isinstance(right_obj, (int, float))
                    else None
                ),
                "delta_mean_structure_diversity_within_budget": (
                    float(right_div) - float(left_div)
                    if isinstance(left_div, (int, float)) and isinstance(right_div, (int, float))
                    else None
                ),
            }
        )
    return {
        "schema_version": "benchmark.external.matrix.compare.v1",
        "left_matrix_id": left.get("matrix_id"),
        "right_matrix_id": right.get("matrix_id"),
        "group_deltas": deltas,
    }


def run_external_benchmark_matrix(
    *,
    datasets: list[str],
    mode: str,
    workspace: Path,
    settings: Settings,
    splits: list[str] | None = None,
    regimes: list[str] | None = None,
    max_cases_per_split: int | None = None,
    max_iterations: int = 4,
    selection_metric_view: str = "property_decomp_aware",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    split_values = [item.strip().lower() for item in (splits or list(EXTERNAL_SPLITS)) if item.strip()]
    for split in split_values:
        if split not in EXTERNAL_SPLITS:
            raise ValueError(f"Unsupported split '{split}'. Expected one of {', '.join(EXTERNAL_SPLITS)}.")
    regime_values = [item.strip().lower() for item in (regimes or list(EXTERNAL_REGIMES)) if item.strip()]
    for regime in regime_values:
        if regime not in EXTERNAL_REGIMES:
            raise ValueError(f"Unsupported regime '{regime}'. Expected one of {', '.join(EXTERNAL_REGIMES)}.")

    dataset_values = [item.strip().lower() for item in datasets if item.strip()]
    for dataset in dataset_values:
        if dataset not in EXTERNAL_DATASETS:
            raise ValueError(f"Unsupported dataset '{dataset}'. Expected one of {', '.join(EXTERNAL_DATASETS)}.")
    matrix_id = _matrix_id(
        datasets=dataset_values,
        splits=split_values,
        regimes=regime_values,
        mode=mode,
        max_cases_per_split=max_cases_per_split,
        max_iterations=max_iterations,
        selection_metric_view=selection_metric_view,
    )
    out_dir = workspace / "benchmarks" / "external_matrix" / matrix_id
    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_paths: dict[str, dict[str, str]] = {}
    rows: list[dict[str, Any]] = []

    for dataset in dataset_values:
        layout = resolve_external_dataset_layout(dataset, repo_root=repo_root)
        normalized_paths[dataset] = {}
        for split in split_values:
            split_path = layout.normalized_split_paths[split]
            if not split_path.exists():
                raise FileNotFoundError(
                    f"Normalized split missing for dataset '{dataset}' split '{split}': {split_path}. "
                    "Run 'benchmark import-external' first."
                )
            normalized_paths[dataset][split] = str(split_path)
            cases = _load_jsonl(split_path)
            if isinstance(max_cases_per_split, int) and max_cases_per_split >= 0:
                cases = cases[:max_cases_per_split]
            for case in cases:
                for regime in regime_values:
                    if regime == "qlip_full_orchestrator":
                        row = _orchestrator_matrix_row(
                            mode=mode,
                            workspace=workspace,
                            settings=settings,
                            case=case,
                            max_iterations=max_iterations,
                            selection_metric_view=selection_metric_view,
                            budget={
                                "max_iterations": int(max_iterations),
                                "max_cases_per_split": max_cases_per_split,
                            },
                        )
                    else:
                        row = _pipeline_matrix_row(
                            regime=regime,
                            mode=mode,
                            workspace=workspace,
                            settings=settings,
                            case=case,
                            budget={
                                "max_iterations": 1,
                                "max_cases_per_split": max_cases_per_split,
                            },
                        )
                    rows.append(row)

    raw = {
        "schema_version": "benchmark.external.matrix.v1",
        "matrix_id": matrix_id,
        "mode": mode,
        "datasets": dataset_values,
        "splits": split_values,
        "regimes": regime_values,
        "budget": {
            "max_cases_per_split": max_cases_per_split,
            "max_iterations": int(max_iterations),
            "selection_metric_view": selection_metric_view,
        },
        "normalized_sources": normalized_paths,
        "rows": rows,
    }
    results_path = out_dir / "external_benchmark_matrix_results.json"
    results_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = build_external_benchmark_report(raw)
    report_path = out_dir / "external_benchmark_matrix_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "matrix_id": matrix_id,
        "results_path": str(results_path),
        "report_path": str(report_path),
    }
