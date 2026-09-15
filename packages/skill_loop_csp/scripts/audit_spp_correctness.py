from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from pymatgen.core import Composition
from spp_maker.io_cif import load_cif
from spp_maker_qlip.pot_quality import audit_pot_file
from spp_maker_qlip.required_pair_extraction import _auto_supercell, _periodic_required_distances

from sok_llm_orchestrator.workflow.evidence import required_pairs_for_formula
from sok_llm_orchestrator.workflow.runner import _tree_hash
from sok_llm_orchestrator.workflow.spp_package_audit import (
    FAMILY_DATABASES,
    canonical_pair_key,
    index_pot_root,
    sha256_file,
)


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    names = list(fieldnames)
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name) for name in names})
    temporary.replace(path)


def _accepted_rows(dataset_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(dataset_dir / "accepted.json")
    return list(payload.get("rows", payload) if isinstance(payload, dict) else payload)


def _primitive_path(crystal_root: Path, row: dict[str, Any]) -> Path:
    path = Path(str(row.get("structure_bundle", {}).get("paths", {}).get("primitive", "")))
    return path if path.is_absolute() else crystal_root / path


def _family_periodic_support(
    *, crystal_root: Path, rows: list[dict[str, Any]], required_pairs: set[str], cutoff: float,
) -> tuple[dict[str, dict[str, int]], list[dict[str, Any]], Counter[str]]:
    by_structure: dict[str, dict[str, int]] = {}
    element_frequency: Counter[str] = Counter()
    for row in rows:
        structure_id = str(row["structure_id"])
        loaded = load_cif(_primitive_path(crystal_root, row))
        elements = set(loaded.symbols)
        element_frequency.update(elements)
        distances = _periodic_required_distances(
            loaded.atoms,
            required_pairs=required_pairs,
            cutoff=float(cutoff),
            supercell=_auto_supercell(loaded.cell, float(cutoff)),
        )
        by_structure[structure_id] = {pair: len(values) for pair, values in distances.items() if values}
    matrix_rows: list[dict[str, Any]] = []
    for pair in sorted(required_pairs, key=str.lower):
        supporting = [structure_id for structure_id, counts in by_structure.items() if counts.get(pair, 0) > 0]
        matrix_rows.append({
            "pair": pair,
            "structure_count": len(supporting),
            "periodic_observation_count": sum(by_structure[value].get(pair, 0) for value in supporting),
        })
    return by_structure, matrix_rows, element_frequency


def _latest_fit_manifest(run_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    manifests = sorted((run_dir / "spp").glob("fit_round_*/spp_build_manifest.json"))
    if not manifests:
        return None, None
    return manifests[-1], _read_json(manifests[-1])


def _request_pair_rows(run_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    _, manifest = _latest_fit_manifest(run_dir)
    if manifest is None:
        return {}
    return {
        canonical_pair_key(str(row["species_pair"])): dict(row)
        for row in manifest.get("request_pair_results", [])
    }


def _sample_groups(result_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups = (
        [row for row in result_rows if row["family"] == "layered" and row["final_classification"] == "SUCCESS_PLAUSIBLE_NONMATCH"][:5]
        + [row for row in result_rows if row["family"] == "layered" and row["final_classification"] == "FAILED_SPP_BUILD"][:5]
        + [row for row in result_rows if row["family"] == "layered" and row["final_classification"] == "FAILED_PAIR_COVERAGE"][:5]
        + [row for row in result_rows if row["family"] == "spinel" and row["final_classification"].startswith("FAILED_")][:5]
    )
    return groups


def _cif_chain_from_stopped_run(run_dir: Path) -> dict[str, Any]:
    evidence_path = run_dir / "spp" / "evidence_bundle.json"
    _, fit = _latest_fit_manifest(run_dir)
    if not evidence_path.is_file() or fit is None:
        return {"status": "SPP_MAKER_NOT_INVOKED", "selected_count": 0, "spp_input_count": 0}
    evidence = _read_json(evidence_path)
    selected = {str(row["structure_id"]): row for row in evidence.get("selected", [])}
    files = [Path(value) for value in fit.get("generation", {}).get("corpus_cif_files", [])]
    actual = {path.stem: path for path in files}
    rows = []
    for structure_id, item in sorted(selected.items()):
        source = Path(str(item["cif_path"]))
        destination = actual.get(structure_id)
        rows.append({
            "structure_id": structure_id,
            "source_mp_id": item.get("source_id"),
            "source_path": str(source),
            "source_sha256": sha256_file(source) if source.is_file() else None,
            "declared_source_sha256": item.get("cif_sha256"),
            "spp_input_path": str(destination) if destination else None,
            "spp_input_sha256": sha256_file(destination) if destination and destination.is_file() else None,
            "reason_included": item.get("inclusion_reason"),
        })
    matches = bool(
        set(selected) == set(actual)
        and all(row["source_sha256"] == row["declared_source_sha256"] == row["spp_input_sha256"] for row in rows)
    )
    return {
        "status": "MATCH" if matches else "MISMATCH",
        "selected_count": len(selected),
        "spp_input_count": len(actual),
        "SELECTED_CORPUS_HASHES_EQUAL_SPP_INPUT_HASHES": matches,
        "rows": rows,
        "unexpected_spp_input_ids": sorted(set(actual) - set(selected)),
    }


def run_audit(*, frozen_path: Path, stopped_results: Path, output_root: Path, crystal_root: Path, regulator_root: Path) -> dict[str, Any]:
    frozen = _read_json(frozen_path)
    targets = list(frozen["targets"])
    pools = {str(row["benchmark_id"]): row for row in frozen["evidence_pools"]}
    output_root.mkdir(parents=True, exist_ok=True)
    result_csv = stopped_results / "PAPER_SPP_ONLY_100_RESULTS.csv"
    with result_csv.open(encoding="utf-8", newline="") as handle:
        stopped_rows = list(csv.DictReader(handle))
    stopped_by_id = {row["experiment_id"]: row for row in stopped_rows}

    dataset_rows: dict[str, list[dict[str, Any]]] = {}
    candidate_to_structure: dict[str, dict[str, str]] = {}
    structure_metadata: dict[str, dict[str, dict[str, Any]]] = {}
    routing_rows: list[dict[str, Any]] = []
    family_required: dict[str, set[str]] = {"layered": set(), "spinel": set()}
    for target in targets:
        family_required[str(target["family"])].update(required_pairs_for_formula(str(target["formula"])))
    support_by_family: dict[str, dict[str, dict[str, int]]] = {}
    for family, (dataset_id, corpus_id, database_name) in FAMILY_DATABASES.items():
        dataset_dir = crystal_root / "artifacts" / "mp_oxide_families_v1" / dataset_id
        rows = _accepted_rows(dataset_dir)
        dataset_rows[family] = rows
        candidate_to_structure[family] = {str(row["candidate_key"]): str(row["structure_id"]) for row in rows}
        structure_metadata[family] = {str(row["structure_id"]): row for row in rows}
        manifest = _read_json(dataset_dir / "dataset_manifest.json")
        database = dataset_dir / database_name
        support, matrix, elements = _family_periodic_support(
            crystal_root=crystal_root, rows=rows, required_pairs=family_required[family], cutoff=11.0,
        )
        support_by_family[family] = support
        _write_csv(
            output_root / f"{family.upper()}_DB_PAIR_SUPPORT.csv", matrix,
            ("pair", "structure_count", "periodic_observation_count"),
        )
        _write_csv(
            output_root / f"{family.upper()}_DB_ELEMENT_FREQUENCY.csv",
            ({"element": element, "structure_count": count} for element, count in sorted(elements.items())),
            ("element", "structure_count"),
        )
        routing_rows.append({
            "family": family,
            "dataset_id": dataset_id,
            "dataset_schema_version": manifest.get("dataset_schema_version"),
            "materials_project_database_version": manifest.get("materials_project_database_version"),
            "corpus_id": corpus_id,
            "database_path": str(database.resolve()),
            "database_sha256": sha256_file(database),
            "record_count": len(rows),
            "vector_index_path": str(database.resolve()),
            "embedding_model": manifest.get("embedding", {}).get("model"),
            "embedding_version": manifest.get("embedding", {}).get("model_version"),
            "embedding_dimensions": _read_json(dataset_dir / "dataset_audit.json").get("embedding_dimensions"),
        })
    _write_json(output_root / "DATABASE_ROUTING_INVENTORY.json", routing_rows)

    regulator_index = index_pot_root(regulator_root)
    regulator_rows: list[dict[str, Any]] = []
    regulator_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for key, paths in sorted(regulator_index.items()):
        quality = audit_pot_file(paths[0], max_cap_fraction_threshold=0.5) if len(paths) == 1 else None
        row = {
            "canonical_pair": "-".join(key),
            "display_pair": paths[0].stem if paths else None,
            "pot_path": str(paths[0]) if len(paths) == 1 else None,
            "pot_sha256": sha256_file(paths[0]) if len(paths) == 1 else None,
            "valid": bool(quality and quality.get("raw_point_count", 0) > 0),
            "finite": bool(quality and quality.get("raw_point_count", 0) > 0),
            "usable": bool(quality and quality.get("pot_quality") == "usable"),
            "quality_status": quality.get("pot_quality") if quality else "ambiguous",
            "x_min": quality.get("x_min") if quality else None,
            "x_max": quality.get("x_max") if quality else None,
            "raw_point_count": quality.get("raw_point_count") if quality else None,
            "observation_provenance": "ICSD broad regulator artifact; pair-level REF/RDF files adjacent when available",
        }
        regulator_rows.append(row)
        regulator_by_key[key] = row
    _write_csv(
        output_root / "GLOBAL_REGULATOR_PAIR_INVENTORY.csv", regulator_rows,
        ("canonical_pair", "display_pair", "pot_path", "pot_sha256", "valid", "finite", "usable", "quality_status", "x_min", "x_max", "raw_point_count", "observation_provenance"),
    )
    regulator_summary = {
        "artifact_path": str(regulator_root.resolve()),
        "artifact_version": regulator_root.name,
        "artifact_pot_tree_sha256": _tree_hash(regulator_root),
        "pot_count": len(regulator_rows),
        "valid_pair_count": sum(bool(row["valid"]) for row in regulator_rows),
        "usable_pair_count": sum(bool(row["usable"]) for row in regulator_rows),
        "distance_domains": sorted({(row["x_min"], row["x_max"]) for row in regulator_rows if row["valid"]}),
        "production_role": "real exact-pair regulator and regulator-only evidence for missing/insufficient local curves",
    }
    _write_json(output_root / "GLOBAL_REGULATOR_SUMMARY.json", regulator_summary)

    coverage_rows: list[dict[str, Any]] = []
    target_summaries: list[dict[str, Any]] = []
    for target in targets:
        experiment_id = str(target["benchmark_id"])
        family = str(target["family"])
        required = required_pairs_for_formula(str(target["formula"]))
        pool = pools[experiment_id]
        excluded_ids = {
            candidate_to_structure[family][key]
            for key in pool.get("excluded_candidate_keys", [])
            if key in candidate_to_structure[family]
        }
        run_dir = stopped_results / "runs" / family / experiment_id
        evidence = _read_json(run_dir / "spp" / "evidence_bundle.json") if (run_dir / "spp" / "evidence_bundle.json").is_file() else None
        selected_counts = dict(evidence.get("pair_structure_counts", {})) if evidence else {}
        request_rows = _request_pair_rows(run_dir) if run_dir.is_dir() else {}
        stopped = stopped_by_id.get(experiment_id, {})
        local_all, final_all = True, True
        requires_global = False
        unsupported: list[str] = []
        for pair in required:
            key = canonical_pair_key(pair)
            supporting = [
                structure_id for structure_id, counts in support_by_family[family].items()
                if structure_id not in excluded_ids and counts.get(pair, 0) > 0
            ]
            full_observations = sum(support_by_family[family][value].get(pair, 0) for value in supporting)
            current = request_rows.get(key, {})
            local_quality = str(current.get("request_quality", "not_attempted"))
            local_curve_exists = bool(current.get("request_pot_path") and Path(str(current["request_pot_path"])).is_file())
            local_valid = bool(current.get("request_pair_status") == "REQUEST_USABLE" and local_curve_exists and local_quality == "usable")
            global_row = regulator_by_key.get(key)
            global_valid = bool(global_row and global_row["usable"])
            if local_valid and global_valid:
                intended = "request_plus_global_regulator"
            elif local_valid:
                intended = "request_only_global_missing"
            elif global_valid:
                intended = "global_regulator"
            else:
                intended = "unsupported"
                unsupported.append(pair)
            local_all &= local_valid
            final_all &= intended != "unsupported"
            requires_global |= not local_valid and global_valid
            coverage_rows.append({
                "experiment_id": experiment_id,
                "family": family,
                "formula": target["formula"],
                "required_pair": pair,
                "local_observation_count": int(current.get("observations", 0) or 0),
                "local_structure_count": int(selected_counts.get(pair, 0) or 0),
                "family_structure_count": len(supporting),
                "family_periodic_observation_count": full_observations,
                "local_curve_exists": local_curve_exists,
                "local_curve_quality": local_quality,
                "global_curve_exists": bool(global_row),
                "global_curve_valid": global_valid,
                "intended_final_source": intended,
                "currently_used_source": current.get("guidance_mode", "benchmark_stopped_before_build"),
                "coverage_should_be_possible": intended != "unsupported",
                "current_failure_reason": stopped.get("failure_message", "not_run_in_stopped_benchmark"),
            })
        target_summaries.append({
            "experiment_id": experiment_id,
            "family": family,
            "formula": target["formula"],
            "stopped_run_classification": stopped.get("final_classification", "NOT_RUN"),
            "local_selected_curves_fully_usable": local_all,
            "requires_global_support": requires_global,
            "fully_coverable_after_global": final_all,
            "genuinely_unsupported_pairs": unsupported,
            "SPP_READY_THEORETICAL": final_all,
        })
    _write_csv(
        output_root / "SPP_PAIR_COVERAGE_AUDIT_ALL_TARGETS.csv", coverage_rows,
        ("experiment_id", "family", "formula", "required_pair", "local_observation_count", "local_structure_count", "family_structure_count", "family_periodic_observation_count", "local_curve_exists", "local_curve_quality", "global_curve_exists", "global_curve_valid", "intended_final_source", "currently_used_source", "coverage_should_be_possible", "current_failure_reason"),
    )
    _write_json(output_root / "SPP_TARGET_COVERAGE_SUMMARY.json", target_summaries)

    failure_rows: list[dict[str, Any]] = []
    for stopped in stopped_rows:
        if stopped["final_classification"] not in {"FAILED_SPP_BUILD", "FAILED_PAIR_COVERAGE"}:
            continue
        target_pairs = [row for row in coverage_rows if row["experiment_id"] == stopped["experiment_id"]]
        global_unused = [row["required_pair"] for row in target_pairs if row["global_curve_valid"] and row["intended_final_source"] == "global_regulator"]
        capped = [row["required_pair"] for row in target_pairs if row["local_curve_quality"] == "capped"]
        unsupported = [row["required_pair"] for row in target_pairs if not row["coverage_should_be_possible"]]
        if unsupported:
            primary = "GLOBAL_CURVE_INVALID_OR_ABSENT"
        elif global_unused:
            primary = "GLOBAL_CURVE_AVAILABLE_BUT_UNUSED"
        elif capped:
            primary = "LOCAL_CURVE_CAPPED"
        else:
            primary = "STRICT_AUDIT_FAILURE"
        failure_rows.append({
            "experiment_id": stopped["experiment_id"],
            "family": stopped["family"],
            "formula": stopped["formula"],
            "old_classification": stopped["final_classification"],
            "primary_root_cause": primary,
            "local_capped_pairs": ";".join(capped),
            "global_available_but_unused_pairs": ";".join(global_unused),
            "genuinely_unsupported_pairs": ";".join(unsupported),
            "old_failure_message": stopped["failure_message"],
        })
    _write_csv(
        output_root / "SPP_BUILD_FAILURE_ROOT_CAUSE.csv", failure_rows,
        ("experiment_id", "family", "formula", "old_classification", "primary_root_cause", "local_capped_pairs", "global_available_but_unused_pairs", "genuinely_unsupported_pairs", "old_failure_message"),
    )

    accepted_formula_by_id = {
        family: {
            str(row["structure_id"]): str(row.get("formula") or row.get("pretty_formula") or row.get("composition", ""))
            for row in rows
        }
        for family, rows in dataset_rows.items()
    }
    samples = []
    for stopped in _sample_groups(stopped_rows):
        experiment_id, family = stopped["experiment_id"], stopped["family"]
        run_dir = stopped_results / "runs" / family / experiment_id
        target_manifest = _read_json(run_dir / "target_manifest.json")
        retrieval = _read_json(run_dir / "retrieval" / "results.json")
        query = _read_json(run_dir / "retrieval" / "query.json")
        selected = []
        for item in retrieval.get("selected", []):
            path = Path(str((item.get("cif_export") or {}).get("path", "")))
            selected.append({
                "structure_id": item.get("structure_id"),
                "source_mp_id": item.get("source_id") or (item.get("provenance") or {}).get("source_id"),
                "formula": accepted_formula_by_id[family].get(str(item.get("structure_id")), ""),
                "rank": item.get("rank"),
                "score": item.get("score", item.get("retrieval_score")),
                "exported_cif_path": str(path),
                "exported_cif_sha256": sha256_file(path) if path.is_file() else None,
                "selection_source": item.get("selection_source", "semantic_core"),
            })
        samples.append({
            "experiment_id": experiment_id,
            "family": family,
            "formula": stopped["formula"],
            "frozen_target_id": target_manifest["target"]["material_id"],
            "dataset_id": target_manifest["target"]["dataset_id"],
            "database_snapshot_path": retrieval["corpus"]["database"],
            "database_id": retrieval["corpus"]["corpus_id"],
            "database_hash": retrieval["corpus"]["hash"],
            "vector_index_path": retrieval["corpus"]["database"],
            "retrieval_query": query,
            "retrieved_neighbours": selected,
            "retrieved_neighbour_count": len(selected),
            "core_neighbour_count": len(_read_json(run_dir / "retrieval" / "retrieval_core.json").get("selected", [])),
            "augmentation_neighbour_count": len(_read_json(run_dir / "retrieval" / "retrieval_augmentation.json")),
            "cif_hash_chain": _cif_chain_from_stopped_run(run_dir),
            "EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB": any(
                row["family"] == family and row["database_path"] == str(Path(retrieval["corpus"]["database"]).resolve())
                and row["database_sha256"] == retrieval["corpus"]["hash"]
                for row in routing_rows
            ),
        })
    _write_json(output_root / "SAMPLED_RETRIEVAL_AND_CIF_PROVENANCE.json", samples)

    summary = {
        "total_targets": len(targets),
        "stopped_run_persisted_rows": len(stopped_rows),
        "targets_fully_coverable_from_selected_local_alone": sum(row["local_selected_curves_fully_usable"] for row in target_summaries),
        "targets_requiring_global_support": sum(row["requires_global_support"] for row in target_summaries),
        "targets_fully_coverable_after_global": sum(row["fully_coverable_after_global"] for row in target_summaries),
        "targets_with_genuinely_unsupported_pair": sum(bool(row["genuinely_unsupported_pairs"]) for row in target_summaries),
        "old_failed_spp_build": sum(row["final_classification"] == "FAILED_SPP_BUILD" for row in stopped_rows),
        "old_failed_pair_coverage": sum(row["final_classification"] == "FAILED_PAIR_COVERAGE" for row in stopped_rows),
        "root_cause_counts": dict(Counter(row["primary_root_cause"] for row in failure_rows)),
        "regulator": regulator_summary,
    }
    _write_json(output_root / "SPP_CORRECTNESS_AUDIT_SUMMARY.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--stopped-results", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--crystal-root", type=Path, default=Path("../Crystal-DB"))
    parser.add_argument("--regulator-root", type=Path, default=Path("../qlip/data/spp/regulators/icsd_broad_regulator_v1"))
    args = parser.parse_args()
    summary = run_audit(
        frozen_path=args.frozen.resolve(), stopped_results=args.stopped_results.resolve(),
        output_root=args.output_root.resolve(), crystal_root=args.crystal_root.resolve(),
        regulator_root=args.regulator_root.resolve(),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
