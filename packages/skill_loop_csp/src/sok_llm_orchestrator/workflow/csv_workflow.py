"""Frozen CSV interface around the paper_final_v2 generation methodology."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from pymatgen.core import Composition

from sok_llm_orchestrator.workflow.component_paths import ComponentRoots


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "final_workflow_v1.json"
RUN_MANIFEST_FIELDS = (
    "row_id",
    "csv_row_number",
    "request_text",
    "database",
    "generation_state",
    "structured_task_status",
    "retrieval_status",
    "retrieved_count",
    "cell_policy",
    "cell_edge_a",
    "spp_contract",
    "pair_count",
    "local_usable_pair_count",
    "fallback_pair_count",
    "solver_status",
    "solver_objective",
    "solver_runtime_s",
    "candidate_cif_path",
    "candidate_sha256",
    "sca_status",
    "visualisation_status",
    "notes",
)
TERMINAL_GENERATION_STATES = frozenset({"GENERATED", "INFEASIBLE"})
ROW_STATES = frozenset(
    {"NOT_STARTED", "RUNNING", "GENERATED", "INFEASIBLE", "TECHNICAL_FAILURE"}
)


class CsvWorkflowError(RuntimeError):
    """Raised for a user-facing frozen-workflow contract violation."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(root).rglob("*.POT"), key=lambda item: item.as_posix().lower()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
        digest.update(b"\n")
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fields})


def _safe_name(value: str, *, fallback: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    if not sanitized:
        sanitized = fallback
    if sanitized in {".", ".."}:
        raise CsvWorkflowError(f"unsafe row identifier: {value!r}")
    return sanitized[:96]


def _parse_bool(value: str, *, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise CsvWorkflowError(f"{field} must be true or false, got {value!r}")


def load_workflow_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    payload = _read_json(Path(path))
    if payload.get("schema_version") != "csv_workflow_config.v1":
        raise CsvWorkflowError(f"unsupported workflow config schema: {path}")
    if payload.get("workflow_version") != "csv_workflow_v1":
        raise CsvWorkflowError("the final workflow config must freeze csv_workflow_v1")
    defaults = payload.get("defaults") or {}
    required = {
        "database",
        "retrieval_top_k",
        "spp_contract",
        "cell_policy",
        "solver_time_limit_s",
        "solver_threads",
        "solver_mip_gap",
        "proximity_scale",
        "random_seed",
        "cutoff_angstrom",
        "grid_density",
        "spp_evidence_limit",
    }
    missing = sorted(required - set(defaults))
    if missing:
        raise CsvWorkflowError(f"frozen workflow defaults are incomplete: {missing}")
    if defaults["spp_contract"] != "dmytro_gr_v1":
        raise CsvWorkflowError("csv_workflow_v1 must default to dmytro_gr_v1")
    if defaults["cell_policy"] != "retrieval_feasible_cell_v1":
        raise CsvWorkflowError("csv_workflow_v1 must default to retrieval_feasible_cell_v1")
    return payload


@dataclass(frozen=True, slots=True)
class BatchRow:
    row_id: str
    csv_row_number: int
    request_text: str
    source_row: dict[str, str]
    effective_config: dict[str, Any]
    structured_task: dict[str, Any]


def _infer_structured_task(request: str, stages: Any) -> dict[str, Any]:
    try:
        return dict(stages.normalise(request))
    except ValueError:
        pass
    marker = re.search(
        r"(?:composition|formula)\s*(?:is|=|:)?\s*([A-Z][A-Za-z0-9()]*\d*)",
        request,
        flags=re.IGNORECASE,
    )
    candidates = [marker.group(1)] if marker else []
    candidates.extend(re.findall(r"\b[A-Z][A-Za-z]*(?:\d+|\([A-Za-z0-9]+\)\d*)[A-Za-z0-9()]*\b", request))
    formula = None
    for candidate in candidates:
        try:
            composition = Composition(candidate)
        except Exception:
            continue
        if len(composition) >= 1 and composition.num_atoms >= 2:
            formula = candidate
            break
    if formula is None:
        raise CsvWorkflowError(
            "request_text could not be normalized to a composition; include an explicit formula"
        )
    lowered = request.lower()
    if "halide perovskite" in lowered:
        family = "halide perovskite"
    elif "perovskite" in lowered:
        family = "perovskite"
    elif "spinel" in lowered:
        family = "spinel"
    elif "layered" in lowered and "oxide" in lowered:
        family = "layered oxide"
    elif "rocksalt" in lowered or "rock salt" in lowered:
        family = "rocksalt"
    elif "cscl" in lowered or "b2" in lowered:
        family = "cscl"
    elif "zinc-blende" in lowered or "zinc blende" in lowered or "b3" in lowered:
        family = "zinc blende"
    elif "anti-fluorite" in lowered or "antifluorite" in lowered:
        family = "fluorite or anti-fluorite"
    elif "fluorite" in lowered:
        family = "fluorite"
    elif "olivine" in lowered:
        family = "olivine phosphate"
    elif "argyrodite" in lowered:
        family = "argyrodite"
    else:
        family = "unspecified"
    return {
        "formula": formula,
        "family": family,
        "prototype": None,
        "space_group": None,
        "normalisation": "deterministic_formula_and_intent_parser.v1",
    }


def _typed_effective_config(raw: dict[str, str], defaults: dict[str, Any]) -> dict[str, Any]:
    value = dict(defaults)
    integer_fields = {"retrieval_top_k", "solver_time_limit_s", "solver_threads", "random_seed"}
    float_fields = {"solver_mip_gap", "proximity_scale"}
    boolean_fields = {"exclude_target_reference"}
    for name, raw_value in raw.items():
        if name in {"row_id", "request_text", "notes"} or raw_value.strip() == "":
            continue
        try:
            if name in integer_fields:
                value[name] = int(raw_value)
            elif name in float_fields:
                value[name] = float(raw_value)
            elif name in boolean_fields:
                value[name] = _parse_bool(raw_value, field=name)
            else:
                value[name] = raw_value.strip()
        except ValueError as exc:
            raise CsvWorkflowError(f"invalid {name} value {raw_value!r}") from exc
    if value["retrieval_top_k"] < 1:
        raise CsvWorkflowError("retrieval_top_k must be positive")
    if value["solver_time_limit_s"] < 1 or value["solver_threads"] < 1:
        raise CsvWorkflowError("solver_time_limit_s and solver_threads must be positive")
    if value["solver_mip_gap"] < 0 or value["proximity_scale"] <= 0:
        raise CsvWorkflowError("solver_mip_gap must be non-negative and proximity_scale positive")
    if value["spp_contract"] != "dmytro_gr_v1":
        raise CsvWorkflowError("csv_workflow_v1 supports only spp_contract=dmytro_gr_v1")
    if value["cell_policy"] != "retrieval_feasible_cell_v1":
        raise CsvWorkflowError(
            "csv_workflow_v1 supports only cell_policy=retrieval_feasible_cell_v1"
        )
    if value.get("exclude_target_reference") and not value.get("target_reference_id"):
        raise CsvWorkflowError(
            "exclude_target_reference=true requires a non-empty target_reference_id"
        )
    return value


def validate_csv(
    input_path: Path,
    workflow_config: Mapping[str, Any],
    *,
    stages: Any | None = None,
) -> list[BatchRow]:
    path = Path(input_path)
    if not path.is_file():
        raise CsvWorkflowError(f"input CSV does not exist: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CsvWorkflowError("input CSV has no header")
        fields = [str(field).strip() for field in reader.fieldnames]
        if "request_text" not in fields:
            raise CsvWorkflowError("input CSV must contain request_text")
        allowed = set(workflow_config["allowed_csv_columns"])
        unsupported = sorted(set(fields) - allowed)
        if unsupported:
            raise CsvWorkflowError(f"unsupported CSV columns: {unsupported}")
        raw_rows = [
            {str(key).strip(): str(value or "") for key, value in row.items() if key is not None}
            for row in reader
        ]
    if not raw_rows:
        raise CsvWorkflowError("input CSV contains no data rows")
    if stages is None:
        from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

        stages = ProductionWorkflowStages()
    result: list[BatchRow] = []
    ids: set[str] = set()
    defaults = dict(workflow_config["defaults"])
    logical_databases = set(workflow_config["logical_databases"])
    for index, raw in enumerate(raw_rows, 1):
        request = raw.get("request_text", "")
        if not request.strip():
            raise CsvWorkflowError(f"CSV row {index + 1} has empty request_text")
        fallback = f"row_{index:04d}"
        row_id = _safe_name(raw.get("row_id", ""), fallback=fallback)
        if row_id in ids:
            raise CsvWorkflowError(f"duplicate row_id after sanitization: {row_id}")
        ids.add(row_id)
        effective = _typed_effective_config(raw, defaults)
        if effective["database"] not in logical_databases:
            raise CsvWorkflowError(
                f"CSV row {index + 1} has unsupported logical database {effective['database']!r}"
            )
        task = _infer_structured_task(request, stages)
        Composition(str(task["formula"]))
        result.append(BatchRow(row_id, index + 1, request, raw, effective, task))
    return result


def _initial_manifest_row(row: BatchRow) -> dict[str, Any]:
    return {
        "row_id": row.row_id,
        "csv_row_number": row.csv_row_number,
        "request_text": row.request_text,
        "database": row.effective_config["database"],
        "generation_state": "NOT_STARTED",
        "structured_task_status": "VALIDATED",
        "retrieval_status": "NOT_STARTED",
        "retrieved_count": 0,
        "cell_policy": row.effective_config["cell_policy"],
        "cell_edge_a": "",
        "spp_contract": row.effective_config["spp_contract"],
        "pair_count": 0,
        "local_usable_pair_count": 0,
        "fallback_pair_count": 0,
        "solver_status": "NOT_STARTED",
        "solver_objective": "",
        "solver_runtime_s": "",
        "candidate_cif_path": "",
        "candidate_sha256": "",
        "sca_status": "NOT_RUN",
        "visualisation_status": "NOT_RUN",
        "notes": row.source_row.get("notes", ""),
    }


def _read_manifest(run_root: Path) -> list[dict[str, str]]:
    path = run_root / "run_manifest.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _save_manifest(run_root: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    _write_csv(run_root / "run_manifest.csv", rows, RUN_MANIFEST_FIELDS)


def _update_manifest(run_root: Path, row_id: str, **updates: Any) -> None:
    rows = _read_manifest(run_root)
    found = False
    for row in rows:
        if row["row_id"] == row_id:
            row.update({key: value for key, value in updates.items() if key in RUN_MANIFEST_FIELDS})
            found = True
            break
    if not found:
        raise CsvWorkflowError(f"run manifest has no row {row_id}")
    _save_manifest(run_root, rows)


def _initialize_run(
    input_path: Path,
    run_root: Path,
    rows: Sequence[BatchRow],
    workflow_config: Mapping[str, Any],
    roots: ComponentRoots,
    *,
    resume: bool,
) -> None:
    root = Path(run_root)
    config_path = root / "run_config.json"
    input_hash = _sha256(input_path)
    frozen_hash = _sha256(DEFAULT_CONFIG_PATH)
    if root.exists() and not resume:
        raise CsvWorkflowError(f"output exists; use --resume to continue safely: {root}")
    if config_path.is_file():
        existing = _read_json(config_path)
        if existing.get("input_csv_sha256") != input_hash:
            raise CsvWorkflowError("--resume input CSV hash differs from the existing run")
        if existing.get("frozen_config_sha256") != frozen_hash:
            raise CsvWorkflowError("--resume frozen workflow config differs from the existing run")
        return
    root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(input_path, root / "input.csv")
    _write_json(
        config_path,
        {
            "schema_version": "csv_workflow_run_config.v1",
            "workflow_version": workflow_config["workflow_version"],
            "scientific_parent": workflow_config["scientific_parent"],
            "created_at": _now(),
            "input_csv_sha256": input_hash,
            "frozen_config_path": str(DEFAULT_CONFIG_PATH),
            "frozen_config_sha256": frozen_hash,
            "defaults": workflow_config["defaults"],
            "generation_ends_before_sca": True,
        },
    )
    _write_json(root / "run_provenance.json", roots.provenance())
    _save_manifest(root, [_initial_manifest_row(row) for row in rows])


def _workflow_config(row: BatchRow, row_root: Path, roots: ComponentRoots) -> Any:
    from sok_llm_orchestrator.workflow.paper_final_v2 import paper_workflow_config

    base = paper_workflow_config(row_root, run_id=f"csv-workflow-v1-{row.row_id}")
    effective = row.effective_config
    excluded = (
        (str(effective["target_reference_id"]),)
        if effective.get("exclude_target_reference")
        else ()
    )
    return replace(
        base,
        retrieval_depth=int(effective["retrieval_top_k"]),
        database_selector=str(effective["database"]),
        crystal_db_root=roots.crystal_db,
        qlip_runtime_root=row_root,
        qlip_data_root=roots.qlip / "data" / "spp",
        regulator_root=roots.qlip / "data" / "spp" / "regulators" / base.regulator_id,
        excluded_structure_ids=excluded,
        solver_time_limit_s=int(effective["solver_time_limit_s"]),
        solver_threads=int(effective["solver_threads"]),
        solver_mip_gap=float(effective["solver_mip_gap"]),
        solver_seed=int(effective["random_seed"]),
        proximity_scale=float(effective["proximity_scale"]),
        attempt_id="generation",
    )


def _ensure_row_inputs(row: BatchRow, row_root: Path) -> None:
    input_root = row_root / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    request_path = input_root / "request.txt"
    if request_path.exists() and request_path.read_text(encoding="utf-8") != row.request_text:
        raise CsvWorkflowError(f"refusing to replace a different request in {row_root}")
    request_path.write_text(row.request_text, encoding="utf-8", newline="")
    _write_json(input_root / "input_row.json", row.source_row)
    _write_json(input_root / "effective_config.json", row.effective_config)
    _write_json(row_root / "structured_task" / "structured_task.json", row.structured_task)
    _write_json(
        row_root / "structured_task" / "provenance.json",
        {
            "workflow_version": "csv_workflow_v1",
            "source": row.structured_task.get("normalisation", "ProductionWorkflowStages.normalise"),
            "original_request_sha256": hashlib.sha256(row.request_text.encode("utf-8")).hexdigest(),
        },
    )


def _portable_retrieval(
    row_root: Path,
    row: BatchRow,
    retrieval: dict[str, Any],
    evidence: Any,
) -> None:
    directory = row_root / "retrieval"
    neighbours = directory / "neighbours"
    neighbours.mkdir(parents=True, exist_ok=True)
    evidence_ids = {str(item.structure_id) for item in evidence.selected}
    manifest: list[dict[str, Any]] = []
    hashes: list[dict[str, Any]] = []
    portable_selected: list[dict[str, Any]] = []
    for index, item in enumerate(retrieval.get("selected", []), 1):
        export = item.get("cif_export") or {}
        source = Path(str(export.get("path") or item.get("internal_spp_cif_path") or ""))
        structure_id = str(item.get("structure_id") or f"rank_{index:04d}")
        destination = neighbours / f"{index:04d}_{_safe_name(structure_id, fallback=f'rank_{index:04d}')}.cif"
        digest = ""
        relative = ""
        if source.is_file():
            shutil.copy2(source, destination)
            digest = _sha256(destination)
            relative = destination.relative_to(row_root).as_posix()
        record = {
            "rank": item.get("rank", index),
            "structure_id": structure_id,
            "similarity_score": item.get("retrieval_score", item.get("score", "")),
            "contributed_to_spp": structure_id in evidence_ids,
            "portable_cif_path": relative,
            "cif_sha256": digest,
            "source_cif_path": str(source) if source else "",
        }
        manifest.append(record)
        hashes.append(
            {
                "structure_id": structure_id,
                "portable_cif_path": relative,
                "cif_sha256": digest,
            }
        )
        portable_selected.append(
            {
                **item,
                "portable_cif_path": relative,
                "cif_sha256": digest,
                "contributed_to_spp": structure_id in evidence_ids,
            }
        )
    _write_json(directory / "query.json", {"query_text": row.request_text, "formula": row.structured_task["formula"]})
    _write_json(
        directory / "retrieval_config.json",
        {
            "backend": retrieval.get("backend"),
            "corpus": retrieval.get("corpus"),
            "query": retrieval.get("config"),
            "logical_database": row.effective_config["database"],
        },
    )
    _write_csv(
        directory / "retrieval_manifest.csv",
        manifest,
        (
            "rank",
            "structure_id",
            "similarity_score",
            "contributed_to_spp",
            "portable_cif_path",
            "cif_sha256",
            "source_cif_path",
        ),
    )
    _write_json(
        directory / "retrieval_manifest.json",
        {
            "corpus": retrieval.get("corpus"),
            "backend": retrieval.get("backend"),
            "config": retrieval.get("config"),
            "selected": portable_selected,
            "spp_evidence": evidence.to_dict(),
        },
    )
    _write_csv(
        directory / "neighbour_hashes.csv",
        hashes,
        ("structure_id", "portable_cif_path", "cif_sha256"),
    )


def _portable_spp(row_root: Path, request_spp: dict[str, Any], evidence: Any) -> dict[str, Any]:
    directory = row_root / "spp"
    potentials = directory / "potentials"
    source_root = Path(request_spp["pot_root"])
    if potentials.exists():
        raise FileExistsError(f"refusing to overwrite persisted SPP potentials: {potentials}")
    shutil.copytree(source_root, potentials)
    pair_rows: list[dict[str, Any]] = []
    for item in request_spp["quality"]["request_pair_results"]:
        selected_name = Path(str(item.get("selected_pot_path") or "")).name
        selected = next(iter(potentials.rglob(selected_name)), None) if selected_name else None
        decision = item.get("blend_decision") or {}
        pair_rows.append(
            {
                "species_pair": item["species_pair"],
                "request_evidence_status": item.get("request_pair_status"),
                "structures_contributing": item.get("structures_contributing", 0),
                "observations": item.get("observations", 0),
                "selected_pot_source": item.get("selected_pot_source", item.get("guidance_mode")),
                "guidance_mode": item.get("guidance_mode"),
                "selected_pot_path": selected.relative_to(row_root).as_posix() if selected else "",
                "selected_pot_sha256": _sha256(selected) if selected else "",
                "prior_weight": decision.get("global_weight"),
            }
        )
    _write_json(
        directory / "config.json",
        {
            "artifact_contract": "dmytro_gr_v1",
            "portable_pot_root": potentials.relative_to(row_root).as_posix(),
            "tree_sha256": _tree_hash(potentials),
        },
    )
    _write_csv(
        directory / "pair_manifest.csv",
        pair_rows,
        (
            "species_pair",
            "request_evidence_status",
            "structures_contributing",
            "observations",
            "selected_pot_source",
            "guidance_mode",
            "selected_pot_path",
            "selected_pot_sha256",
            "prior_weight",
        ),
    )
    _write_csv(
        directory / "evidence_counts.csv",
        (
            {"species_pair": pair, "structures_contributing": count}
            for pair, count in evidence.pair_structure_counts.items()
        ),
        ("species_pair", "structures_contributing"),
    )
    _write_csv(
        directory / "blend_weights.csv",
        pair_rows,
        ("species_pair", "prior_weight", "selected_pot_source"),
    )
    portable = dict(request_spp)
    portable["pot_root"] = str(potentials.resolve())
    portable["artifact"] = str(directory.resolve())
    _write_json(
        directory / "provenance.json",
        {
            "evidence_bundle": evidence.to_dict(),
            "request_spp": portable,
            "pair_manifest": pair_rows,
        },
    )
    _write_json(directory / "request_spp_cache.json", portable)
    return portable


def _load_preflight(row_root: Path) -> dict[str, Any]:
    status = _read_json(row_root / "status" / "generation_status.json")
    if status.get("preflight_status") != "PASS":
        raise CsvWorkflowError(f"row preflight is not complete: {row_root}")
    return _read_json(row_root / "spp" / "request_spp_cache.json")


def _prepare_row(
    row: BatchRow,
    row_root: Path,
    roots: ComponentRoots,
    *,
    stages: Any,
    dynamic_resolver: Callable[..., tuple[Any, dict[str, Any]]],
) -> dict[str, Any]:
    status_path = row_root / "status" / "generation_status.json"
    if status_path.is_file() and _read_json(status_path).get("preflight_status") == "PASS":
        return _load_preflight(row_root)
    _ensure_row_inputs(row, row_root)
    config = _workflow_config(row, row_root, roots)
    retrieval = stages.retrieve(row.request_text, row.structured_task, config, row_root / "retrieval" / "build")
    required_pairs = stages.required_pairs(row.structured_task, config)
    from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence

    evidence = assemble_spp_evidence(
        retrieval=retrieval,
        required_pairs=required_pairs,
        excluded_structure_ids=config.excluded_structure_ids,
        max_ranked_structures=int(row.effective_config["spp_evidence_limit"]),
        allow_partial_pair_coverage=True,
    )
    _portable_retrieval(row_root, row, retrieval, evidence)
    built = stages.fit_request_spp(
        evidence,
        row.structured_task,
        config,
        row_root / "spp" / "build",
    )
    request_spp = _portable_spp(row_root, built, evidence)
    cell, provenance = dynamic_resolver(
        str(row.structured_task["formula"]),
        evidence.selected,
        grid_density=int(row.effective_config["grid_density"]),
        proximity_scale=float(row.effective_config["proximity_scale"]),
    )
    request_spp["dynamic_cell"] = cell.to_dict()
    _write_json(row_root / "spp" / "request_spp_cache.json", request_spp)
    cell_root = row_root / "cell"
    _write_json(cell_root / "retrieval_volume_prior.json", provenance["retrieval_volume_prior"])
    _write_json(cell_root / "dynamic_cell.json", cell.to_dict())
    _write_json(cell_root / "feasibility_trace.json", provenance)
    _write_json(
        cell_root / "search_space.json",
        cell.to_dict()
        | {
            "grid_dimensions": [int(row.effective_config["grid_density"])] * 3,
            "candidate_site_count": int(row.effective_config["grid_density"]) ** 3,
        },
    )
    qlip_root = row_root / "qlip"
    solver_config = {
        "name": "gurobi",
        "time_limit_s": config.solver_time_limit_s,
        "threads": config.solver_threads,
        "mip_gap": config.solver_mip_gap,
        "seed": config.solver_seed,
        "parameters": {"NonConvex": 2},
        "proximity_scale": config.proximity_scale,
    }
    _write_json(qlip_root / "solver_config.json", solver_config)
    (qlip_root / "logs").mkdir(parents=True, exist_ok=True)
    _write_json(
        status_path,
        {
            "schema_version": "csv_workflow_generation_state.v1",
            "row_id": row.row_id,
            "generation_state": "NOT_STARTED",
            "preflight_status": "PASS",
            "scientific_attempt_count": 0,
            "technical_attempt_count": 0,
            "updated_at": _now(),
        },
    )
    return request_spp


def _write_failure(status_path: Path, current: dict[str, Any], exc: Exception) -> None:
    current.update(
        {
            "generation_state": "TECHNICAL_FAILURE",
            "technical_attempt_count": int(current.get("technical_attempt_count", 0)) + 1,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "updated_at": _now(),
        }
    )
    _write_json(status_path, current)


def _solve_row(
    row: BatchRow,
    row_root: Path,
    roots: ComponentRoots,
    *,
    stages: Any,
    retry_technical_failures: bool,
) -> None:
    status_path = row_root / "status" / "generation_status.json"
    state = _read_json(status_path)
    generation_state = str(state.get("generation_state"))
    if generation_state in TERMINAL_GENERATION_STATES:
        return
    if generation_state == "TECHNICAL_FAILURE" and not retry_technical_failures:
        raise CsvWorkflowError(
            f"{row.row_id} is TECHNICAL_FAILURE; use --retry-technical-failures explicitly"
        )
    if int(state.get("scientific_attempt_count", 0)) != 0:
        raise CsvWorkflowError(f"exactly-once guard refuses {row.row_id}: {state}")
    config = _workflow_config(row, row_root, roots)
    request_spp = _load_preflight(row_root)
    state.update(
        {
            "generation_state": "RUNNING",
            "scientific_attempt_count": 1,
            "started_at": _now(),
            "updated_at": _now(),
        }
    )
    _write_json(status_path, state)
    started = time.perf_counter()
    try:
        solved = stages.solve(row.structured_task, request_spp, config, row_root / "qlip")
        runtime = time.perf_counter() - started
        generated = row_root / "generated"
        generated.mkdir(parents=True, exist_ok=True)
        candidate = generated / "candidate.cif"
        if candidate.exists():
            raise FileExistsError(f"refusing to overwrite successful candidate: {candidate}")
        shutil.copy2(Path(solved["cif_path"]), candidate)
        digest = _sha256(candidate)
        (generated / "candidate.sha256").write_text(
            f"{digest}  candidate.cif\n", encoding="ascii"
        )
        components = solved["components"]
        result = {
            "status": solved["status"],
            "solver_objective": solved["solver_objective"],
            "runtime_s": runtime,
            "solver_summary": solved.get("solver_summary"),
            "solver_diagnostics": solved.get("solver_diagnostics"),
            "search_space": solved.get("search_space"),
            "qlip_adapter": solved.get("qlip_adapter"),
            "generated_cif_path": "generated/candidate.cif",
            "generated_cif_sha256": digest,
        }
        _write_json(row_root / "qlip" / "solver_result.json", result)
        diagnostics = solved.get("solver_diagnostics") or {}
        _write_json(
            row_root / "qlip" / "problem_size.json",
            dict(diagnostics.get("model_stats") or {})
            | {
                "candidate_positions": int(row.effective_config["grid_density"]) ** 3,
                "auxiliary_linearisation_variables": 0,
            },
        )
        _write_json(
            row_root / "qlip" / "objective_check.json",
            {
                "solver_objective": solved["solver_objective"],
                "independent_objective": components.solver_objective,
                "absolute_difference": solved["difference"],
                "status": "PASS" if solved["difference"] <= 1e-6 else "FAIL",
            },
        )
        state.update(
            {
                "generation_state": "GENERATED",
                "solver_status": solved["status"],
                "candidate_sha256": digest,
                "finished_at": _now(),
                "updated_at": _now(),
            }
        )
        _write_json(status_path, state)
        _update_manifest(
            row_root.parent,
            row.row_id,
            generation_state="GENERATED",
            solver_status=solved["status"],
            solver_objective=solved["solver_objective"],
            solver_runtime_s=runtime,
            candidate_cif_path=f"{row.row_id}/generated/candidate.cif",
            candidate_sha256=digest,
        )
    except Exception as exc:
        runtime = time.perf_counter() - started
        from sok_llm_orchestrator.workflow.runner import WorkflowStageError

        if isinstance(exc, WorkflowStageError) and str(exc.details.get("qlip_status") or "") in {
            "INFEASIBLE",
            "TIME_LIMIT_NO_SOLUTION",
        }:
            solver_status = str(exc.details.get("qlip_status"))
            _write_json(
                row_root / "qlip" / "solver_result.json",
                {
                    "status": solver_status,
                    "runtime_s": runtime,
                    "error": str(exc),
                    "details": exc.details,
                },
            )
            state.update(
                {
                    "generation_state": "INFEASIBLE",
                    "solver_status": solver_status,
                    "finished_at": _now(),
                    "updated_at": _now(),
                }
            )
            _write_json(status_path, state)
            _update_manifest(
                row_root.parent,
                row.row_id,
                generation_state="INFEASIBLE",
                solver_status=solver_status,
                solver_runtime_s=runtime,
                notes=str(exc),
            )
            return
        state["scientific_attempt_count"] = 0
        _write_failure(status_path, state, exc)
        _update_manifest(
            row_root.parent,
            row.row_id,
            generation_state="TECHNICAL_FAILURE",
            solver_status="TECHNICAL_FAILURE",
            solver_runtime_s=runtime,
            notes=f"{type(exc).__name__}: {exc}",
        )
        raise


def _select_rows(rows: Sequence[BatchRow], selectors: Iterable[str] | None) -> list[BatchRow]:
    requested = {value for value in (selectors or ()) if value}
    if not requested:
        return list(rows)
    available = {row.row_id for row in rows}
    unknown = sorted(requested - available)
    if unknown:
        raise CsvWorkflowError(f"unknown --rows values: {unknown}")
    return [row for row in rows if row.row_id in requested]


def generate_batch(
    *,
    input_path: Path,
    output_root: Path,
    roots: ComponentRoots,
    rows: Iterable[str] | None = None,
    resume: bool = False,
    fail_fast: bool = False,
    dry_run: bool = False,
    preflight_only: bool = False,
    retry_technical_failures: bool = False,
    stages: Any | None = None,
    dynamic_resolver: Callable[..., tuple[Any, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    roots.activate_imports()
    config = load_workflow_config()
    if stages is None:
        from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

        stages = ProductionWorkflowStages()
    parsed = validate_csv(input_path, config, stages=stages)
    selected = _select_rows(parsed, rows)
    if dry_run:
        return {
            "status": "DRY_RUN_PASS",
            "workflow_version": config["workflow_version"],
            "validated_rows": len(parsed),
            "selected_rows": [row.row_id for row in selected],
            "output": str(Path(output_root).resolve()),
        }
    _initialize_run(input_path, output_root, parsed, config, roots, resume=resume)
    if dynamic_resolver is None:
        from sok_llm_orchestrator.workflow.dynamic_cell import resolve_dynamic_cell

        dynamic_resolver = resolve_dynamic_cell
    failures: list[dict[str, str]] = []
    for row in selected:
        row_root = Path(output_root) / row.row_id
        try:
            request_spp = _prepare_row(
                row,
                row_root,
                roots,
                stages=stages,
                dynamic_resolver=dynamic_resolver,
            )
            pair_rows = request_spp["quality"]["request_pair_results"]
            cell = request_spp["dynamic_cell"]
            _update_manifest(
                Path(output_root),
                row.row_id,
                structured_task_status="PASS",
                retrieval_status="PASS",
                retrieved_count=len(_read_json(row_root / "retrieval" / "retrieval_manifest.json")["selected"]),
                cell_edge_a=cell["a"],
                pair_count=len(pair_rows),
                local_usable_pair_count=sum(
                    item.get("request_pair_status") == "REQUEST_USABLE" for item in pair_rows
                ),
                fallback_pair_count=sum(
                    str(item.get("guidance_mode", "")).startswith("REGULATOR_ONLY_")
                    for item in pair_rows
                ),
            )
            if not preflight_only:
                _solve_row(
                    row,
                    row_root,
                    roots,
                    stages=stages,
                    retry_technical_failures=retry_technical_failures,
                )
        except Exception as exc:
            failures.append({"row_id": row.row_id, "error": f"{type(exc).__name__}: {exc}"})
            if row_root.exists() and not (row_root / "status" / "generation_status.json").is_file():
                status_path = row_root / "status" / "generation_status.json"
                _write_failure(status_path, {"scientific_attempt_count": 0}, exc)
                _update_manifest(
                    Path(output_root),
                    row.row_id,
                    generation_state="TECHNICAL_FAILURE",
                    notes=f"{type(exc).__name__}: {exc}",
                )
            if fail_fast:
                raise
    result = {
        "status": "PASS" if not failures else "PARTIAL_FAILURE",
        "workflow_version": config["workflow_version"],
        "mode": "PREFLIGHT_ONLY" if preflight_only else "GENERATE",
        "selected_rows": [row.row_id for row in selected],
        "failures": failures,
        "run_manifest": str((Path(output_root) / "run_manifest.csv").resolve()),
    }
    _write_json(Path(output_root) / "last_command_result.json", result)
    if failures:
        raise CsvWorkflowError(f"{len(failures)} row(s) failed; see last_command_result.json")
    return result


def _row_task(row_root: Path) -> dict[str, Any]:
    return _read_json(row_root / "structured_task" / "structured_task.json")


def _sca_one(row_root: Path, roots: ComponentRoots, *, force: bool = False) -> dict[str, Any]:
    result_path = row_root / "sca" / "result.json"
    if result_path.is_file() and not force:
        return _read_json(row_root / "sca" / "summary.json")
    candidate = row_root / "generated" / "candidate.cif"
    if not candidate.is_file():
        return {"row_id": row_root.name, "sca_status": "SKIPPED_NO_CANDIDATE"}
    roots.activate_imports(include_sca=True)
    before = _sha256(candidate)
    from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages

    raw = ProductionWorkflowStages().evaluate(candidate, _row_task(row_root))
    after = _sha256(candidate)
    if before != after:
        raise CsvWorkflowError(f"SCA modified immutable candidate: {row_root}")
    parse = bool(raw.get("parse_ok"))
    composition = bool(raw.get("target_formula_match"))
    geometry = raw.get("geometry_ok") is True
    contacts = int(raw.get("num_bad_contacts") or 0)
    topology = str(raw.get("topology_status") or "NOT_EVALUATED")
    outcome = (
        "PASS"
        if parse and composition and geometry and contacts == 0 and topology in {"PASS", "NOT_EVALUATED"}
        else "PARTIAL"
        if parse and composition
        else "FAIL"
    )
    summary = {
        "row_id": row_root.name,
        "sca_status": outcome,
        "source_candidate_sha256": before,
        "candidate_sha256_after": after,
        "parse_ok": raw.get("parse_ok"),
        "composition_match": raw.get("target_formula_match"),
        "detected_space_group": raw.get("detected_space_group"),
        "requested_space_group": raw.get("target_space_group"),
        "space_group_match": raw.get("space_group_consistent"),
        "topology_result": topology,
        "geometry_valid": raw.get("geometry_ok"),
        "bad_contacts": contacts,
        "minimum_distance_angstrom": raw.get("min_distance"),
        "structure_match_result": raw.get("novel_by_structure_matcher"),
    }
    sca_root = row_root / "sca"
    _write_json(
        sca_root / "config.json",
        {
            "backend": "sca.pipelines.evaluate_one_cif",
            "run_alignn": False,
            "SCA_ROOT": str(roots.sca),
            "source_candidate_sha256": before,
        },
    )
    _write_json(result_path, raw)
    _write_json(sca_root / "summary.json", summary)
    return summary


def run_sca(
    *,
    roots: ComponentRoots,
    row: Path | None = None,
    run: Path | None = None,
    rows: Iterable[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if (row is None) == (run is None):
        raise CsvWorkflowError("sca requires exactly one of --row or --run")
    if row is not None:
        row_root = Path(row).resolve()
        summary = _sca_one(row_root, roots, force=force)
        run_root = row_root.parent
        if (run_root / "run_manifest.csv").is_file():
            _update_manifest(run_root, row_root.name, sca_status=summary["sca_status"])
        return summary
    run_root = Path(run).resolve()
    manifest = _read_manifest(run_root)
    requested = set(rows or ())
    summaries: list[dict[str, Any]] = []
    for manifest_row in manifest:
        row_id = manifest_row["row_id"]
        if requested and row_id not in requested:
            continue
        if manifest_row.get("generation_state") != "GENERATED":
            summaries.append({"row_id": row_id, "sca_status": "SKIPPED_NO_CANDIDATE"})
            continue
        summary = _sca_one(run_root / row_id, roots, force=force)
        summaries.append(summary)
        _update_manifest(run_root, row_id, sca_status=summary["sca_status"])
    fields = (
        "row_id",
        "sca_status",
        "source_candidate_sha256",
        "parse_ok",
        "composition_match",
        "detected_space_group",
        "requested_space_group",
        "space_group_match",
        "topology_result",
        "geometry_valid",
        "bad_contacts",
        "minimum_distance_angstrom",
        "structure_match_result",
    )
    _write_csv(run_root / "SCA_RUN_SUMMARY.csv", summaries, fields)
    _write_json(run_root / "SCA_RUN_SUMMARY.json", summaries)
    return {"run": str(run_root), "rows": summaries}


def visualise_row(row: Path) -> dict[str, Any]:
    from sok_llm_orchestrator.workflow.portable_visualization import render_portable_row

    row_root = Path(row).resolve()
    result = render_portable_row(row_root)
    run_root = row_root.parent
    if (run_root / "run_manifest.csv").is_file():
        _update_manifest(run_root, row_root.name, visualisation_status="PASS")
    return result


def doctor(roots: ComponentRoots) -> dict[str, Any]:
    rows = roots.diagnostics()
    return {"status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL", "components": rows}


__all__ = [
    "BatchRow",
    "CsvWorkflowError",
    "doctor",
    "generate_batch",
    "load_workflow_config",
    "run_sca",
    "validate_csv",
    "visualise_row",
]
