"""Strict real-artifact audit for request plus global-regulator SPP packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from spp_maker_qlip.pot_quality import audit_pot_file


FAMILY_DATABASES = {
    "layered": (
        "MP_LAYERED_BATTERY_OXIDES_V1",
        "mp_layered_battery_oxides_v1",
        "MP_LAYERED_BATTERY_OXIDES_V1.db",
    ),
    "spinel": (
        "MP_SPINEL_OXIDES_V1",
        "mp_spinel_oxides_v1",
        "MP_SPINEL_OXIDES_V1.db",
    ),
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def final_curve_provenance_hash(
    *, source: str, request_hash: str | None, global_hash: str | None,
    local_weight: float, global_weight: float,
) -> tuple[str | None, str | None]:
    if source == "request_plus_global_regulator":
        digest = hashlib.sha256(json.dumps({
            "global_curve_hash": global_hash,
            "global_weight": global_weight,
            "local_weight": local_weight,
            "request_curve_hash": request_hash,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return digest, "weighted_component_manifest"
    if source == "request_only_global_missing":
        return request_hash, "pot_artifact"
    if source == "global_regulator":
        return global_hash, "pot_artifact"
    return None, None


def canonical_pair_key(pair: str) -> tuple[str, str]:
    parts = [part.strip() for part in str(pair).split("-")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid species-pair identifier: {pair!r}")
    return tuple(sorted((parts[0].casefold(), parts[1].casefold())))


def index_pot_root(root: Path) -> dict[tuple[str, str], list[Path]]:
    indexed: dict[tuple[str, str], list[Path]] = {}
    root = Path(root)
    if not root.is_dir():
        return indexed
    for path in sorted(root.rglob("*.POT"), key=lambda item: item.as_posix().lower()):
        indexed.setdefault(canonical_pair_key(path.stem), []).append(path.resolve())
    return indexed


def assert_family_database_provenance(
    *, target: Mapping[str, Any], retrieval: Mapping[str, Any], crystal_root: Path,
) -> dict[str, Any]:
    family = str(target.get("family", ""))
    if family not in FAMILY_DATABASES:
        raise ValueError(f"unsupported benchmark family: {family!r}")
    expected_dataset, expected_corpus, database_name = FAMILY_DATABASES[family]
    expected_database = (
        Path(crystal_root) / "artifacts" / "mp_oxide_families_v1" / expected_dataset / database_name
    ).resolve()
    corpus = retrieval.get("corpus") if isinstance(retrieval.get("corpus"), Mapping) else {}
    actual_database = Path(str(corpus.get("database", ""))).resolve()
    actual_hash = str(corpus.get("hash", ""))
    checks = {
        "family": family,
        "expected_dataset_id": expected_dataset,
        "actual_dataset_id": str(target.get("dataset_id", "")),
        "expected_corpus_id": expected_corpus,
        "actual_corpus_id": str(corpus.get("corpus_id", "")),
        "expected_database": str(expected_database),
        "actual_database": str(actual_database),
        "expected_database_sha256": sha256_file(expected_database) if expected_database.is_file() else None,
        "actual_database_sha256": actual_hash or None,
    }
    checks["EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB"] = bool(
        checks["actual_dataset_id"] == expected_dataset
        and checks["actual_corpus_id"] == expected_corpus
        and actual_database == expected_database
        and expected_database.is_file()
        and actual_hash == checks["expected_database_sha256"]
    )
    if not checks["EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB"]:
        raise RuntimeError(f"benchmark family database provenance mismatch: {checks}")
    return checks


def audit_cif_hash_chain(
    *, evidence: Any, input_dir: Path, excluded_structure_ids: Iterable[str] = (),
) -> dict[str, Any]:
    excluded = {str(value) for value in excluded_structure_ids}
    expected: dict[str, dict[str, Any]] = {}
    for item in evidence.selected:
        structure_id = str(item.structure_id)
        source = Path(item.cif_path).resolve()
        digest = sha256_file(source) if source.is_file() else None
        expected[structure_id] = {
            "structure_id": structure_id,
            "source_mp_id": getattr(item, "source_id", None),
            "source_path": str(source),
            "source_sha256": digest,
            "declared_source_sha256": str(item.cif_sha256),
            "reason_included": str(item.inclusion_reason),
            "family": getattr(item, "family", None),
        }
    actual: dict[str, dict[str, Any]] = {}
    input_dir = Path(input_dir).resolve()
    for path in sorted(input_dir.glob("*.cif"), key=lambda item: item.name.lower()):
        actual[path.stem] = {
            "structure_id": path.stem,
            "spp_input_path": str(path),
            "spp_input_sha256": sha256_file(path),
        }
    selected_hashes_match_declared = all(
        row["source_sha256"] == row["declared_source_sha256"] for row in expected.values()
    )
    selected_equals_input = bool(
        set(expected) == set(actual)
        and all(expected[key]["source_sha256"] == actual[key]["spp_input_sha256"] for key in expected)
    )
    leaked = sorted(set(expected) & excluded)
    return {
        "input_directory": str(input_dir),
        "selected_count": len(expected),
        "spp_input_count": len(actual),
        "selected_structure_ids": sorted(expected),
        "spp_input_structure_ids": sorted(actual),
        "selected_hashes_match_declared": selected_hashes_match_declared,
        "SELECTED_CORPUS_HASHES_EQUAL_SPP_INPUT_HASHES": selected_equals_input,
        "excluded_structure_ids_present": leaked,
        "NO_TARGET_LEAKAGE": not leaked,
        "selected": [expected[key] | actual.get(key, {}) for key in sorted(expected)],
        "unexpected_input_cifs": [actual[key] for key in sorted(set(actual) - set(expected))],
    }


def audit_spp_package(
    *, required_pairs: Iterable[str], request_spp: Mapping[str, Any] | None,
    regulator_root: Path, cif_chain: Mapping[str, Any] | None = None,
    max_cap_fraction_threshold: float = 0.5,
) -> dict[str, Any]:
    """Audit exact real POT artifacts; never invent a missing-pair fallback."""
    required = list(dict.fromkeys(str(pair) for pair in required_pairs))
    request_spp = request_spp or {}
    request_root_value = request_spp.get("pot_root")
    request_root = Path(str(request_root_value)) if request_root_value else None
    request_index = index_pot_root(request_root) if request_root is not None else {}
    regulator_root = Path(regulator_root).resolve()
    regulator_index = index_pot_root(regulator_root)
    pair_result_rows = request_spp.get("quality", {}).get("request_pair_results", [])
    results_by_key = {
        canonical_pair_key(str(row.get("species_pair"))): dict(row)
        for row in pair_result_rows
        if row.get("species_pair")
    }
    rows: list[dict[str, Any]] = []
    for pair in required:
        key = canonical_pair_key(pair)
        result = results_by_key.get(key, {})
        request_paths = request_index.get(key, [])
        regulator_paths = regulator_index.get(key, [])
        request_quality = (
            audit_pot_file(request_paths[0], max_cap_fraction_threshold=max_cap_fraction_threshold)
            if len(request_paths) == 1 else None
        )
        regulator_quality = (
            audit_pot_file(regulator_paths[0], max_cap_fraction_threshold=max_cap_fraction_threshold)
            if len(regulator_paths) == 1 else None
        )
        request_status = str(result.get("request_pair_status", "REQUEST_MISSING"))
        request_valid = bool(
            len(request_paths) == 1
            and request_status == "REQUEST_USABLE"
            and request_quality
            and request_quality.get("pot_quality") == "usable"
        )
        regulator_valid = bool(
            len(regulator_paths) == 1
            and regulator_quality
            and regulator_quality.get("pot_quality") == "usable"
        )
        if request_valid and regulator_valid:
            source = "request_plus_global_regulator"
            weight_local, weight_global = 1.0, 2.0
        elif request_valid:
            source = "request_only_global_missing"
            weight_local, weight_global = 1.0, 0.0
        elif regulator_valid:
            source = "global_regulator"
            weight_local, weight_global = 0.0, 2.0
        else:
            source = "unsupported"
            weight_local, weight_global = 0.0, 0.0
        request_hash = sha256_file(request_paths[0]) if len(request_paths) == 1 else None
        global_hash = sha256_file(regulator_paths[0]) if len(regulator_paths) == 1 else None
        final_hash, final_hash_kind = final_curve_provenance_hash(
            source=source, request_hash=request_hash, global_hash=global_hash,
            local_weight=weight_local, global_weight=weight_global,
        )
        rows.append({
            "required_pair": pair,
            "pair": pair,
            "request_pair_status": request_status,
            "local_observations": int(result.get("observations", 0) or 0),
            "local_observation_count": int(result.get("observations", 0) or 0),
            "local_structure_count": int(result.get("structures_contributing", 0) or 0),
            "local_curve_exists": len(request_paths) == 1,
            "local_curve_valid": request_valid,
            "local_curve_ambiguous": len(request_paths) > 1,
            "local_curve_quality": request_quality.get("pot_quality") if request_quality else "missing",
            "request_pot_path": str(request_paths[0]) if len(request_paths) == 1 else None,
            "request_pot_sha256": request_hash,
            "request_curve_hash": request_hash,
            "global_curve_exists": len(regulator_paths) == 1,
            "global_curve_ambiguous": len(regulator_paths) > 1,
            "global_curve_valid": regulator_valid,
            "global_curve_quality": regulator_quality.get("pot_quality") if regulator_quality else "missing",
            "regulator_pot_path": str(regulator_paths[0]) if len(regulator_paths) == 1 else None,
            "regulator_pot_sha256": global_hash,
            "global_curve_hash": global_hash,
            "intended_final_source": source,
            "final_source": source,
            "final_curve_hash": final_hash,
            "final_curve_hash_kind": final_hash_kind,
            "currently_used_source": str(result.get("guidance_mode", "not_built")),
            "weight_local": weight_local,
            "weight_global": weight_global,
            "local_weight": weight_local,
            "global_weight": weight_global,
            "coverage_should_be_possible": source != "unsupported",
        })
    unsupported = [row["required_pair"] for row in rows if not row["coverage_should_be_possible"]]
    chain_valid = True if cif_chain is None else bool(
        cif_chain.get("SELECTED_CORPUS_HASHES_EQUAL_SPP_INPUT_HASHES")
        and cif_chain.get("NO_TARGET_LEAKAGE")
    )
    return {
        "required_pairs": required,
        "regulator_root": str(regulator_root),
        "pair_diagnostics": rows,
        "unsupported_pairs": unsupported,
        "all_required_pairs_accounted_for": not unsupported,
        "cif_provenance_valid": chain_valid,
        "SPP_READY": not unsupported and chain_valid,
        "uses_synthetic_fallback": False,
    }


__all__ = [
    "FAMILY_DATABASES", "assert_family_database_provenance", "audit_cif_hash_chain",
    "audit_spp_package", "canonical_pair_key", "final_curve_provenance_hash",
    "index_pot_root", "sha256_file",
]
