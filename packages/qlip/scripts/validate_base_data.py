from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("QLIP_BASE_DATA_DIR", REPO_ROOT / "data" / "base")).resolve()
REQUIRED_FILES = {
    "elements.json",
    "radii.json",
    "ionic_radii.json",
    "radius_policy.json",
    "pair_distance_policy.json",
    "provenance.json",
}
FORBIDDEN_SOURCE_IDS = {"synthetic", "fake", "manual_unknown"}
REQUIRED_PACKAGES = {"ase", "mendeleev", "pymatgen", "smact"}


def _load(name: str) -> Dict[str, Any]:
    path = DATA_DIR / name
    if not path.exists():
        raise AssertionError(f"Missing required base data file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value)) and float(value) > 0


def _source_ids(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("source_id") and isinstance(item, str):
                yield item
            yield from _source_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _source_ids(item)


def validate() -> None:
    missing_files = [name for name in sorted(REQUIRED_FILES) if not (DATA_DIR / name).exists()]
    if missing_files:
        raise AssertionError(f"Missing base data files: {missing_files}")

    elements = _load("elements.json")
    radii = _load("radii.json")
    ionic = _load("ionic_radii.json")
    radius_policy = _load("radius_policy.json")
    pair_policy = _load("pair_distance_policy.json")
    provenance = _load("provenance.json")

    element_records = elements.get("records")
    if not isinstance(element_records, list) or len(element_records) != 118:
        raise AssertionError("elements.json must contain exactly 118 element records")

    symbols = []
    atomic_numbers = set()
    for record in element_records:
        symbol = record.get("symbol")
        z = record.get("atomic_number")
        if not isinstance(symbol, str) or not symbol:
            raise AssertionError(f"Invalid element symbol record: {record}")
        if not isinstance(z, int) or not 1 <= z <= 118:
            raise AssertionError(f"Invalid atomic number for {symbol}: {z}")
        if not _positive_number(record.get("atomic_mass")):
            raise AssertionError(f"Invalid atomic mass for {symbol}")
        if not record.get("source_id"):
            raise AssertionError(f"Missing source_id for element {symbol}")
        symbols.append(symbol)
        atomic_numbers.add(z)

    if len(set(symbols)) != 118 or len(atomic_numbers) != 118:
        raise AssertionError("Element symbols and atomic numbers must be unique")

    radius_records = radii.get("records")
    if not isinstance(radius_records, dict):
        raise AssertionError("radii.json records must be an object keyed by symbol")
    if set(radius_records) != set(symbols):
        raise AssertionError("radii.json symbols must match elements.json")

    for symbol, record in radius_records.items():
        if not isinstance(record.get("atomic_number"), int) or record["atomic_number"] not in atomic_numbers:
            raise AssertionError(f"Invalid radius atomic_number for {symbol}")
        if not _positive_number(record.get("qlip_default_radius_angstrom")):
            raise AssertionError(f"Missing usable QLIP default radius for supported element {symbol}")
        if not record.get("qlip_default_radius_source_id"):
            raise AssertionError(f"Missing QLIP default radius source for {symbol}")
        if record.get("qlip_default_radius_source_id") in FORBIDDEN_SOURCE_IDS:
            raise AssertionError(f"Forbidden default radius source for {symbol}")
        if record.get("covalent_radius_angstrom") is not None and not record.get("covalent_radius_source_id"):
            raise AssertionError(f"Missing covalent radius source for {symbol}")
        if record.get("vdw_radius_angstrom") is not None and not record.get("vdw_radius_source_id"):
            raise AssertionError(f"Missing vdw radius source for {symbol}")
        if not isinstance(record.get("notes"), list):
            raise AssertionError(f"radii notes must be a list for {symbol}")

    ionic_records = ionic.get("records")
    if not isinstance(ionic_records, dict) or set(ionic_records) != set(symbols):
        raise AssertionError("ionic_radii.json symbols must match elements.json")
    for symbol, record in ionic_records.items():
        rows = record.get("ionic_radii")
        if not isinstance(rows, list):
            raise AssertionError(f"ionic_radii for {symbol} must be a list")
        if not isinstance(record.get("source_status"), list):
            raise AssertionError(f"source_status for {symbol} must be a list")
        for row in rows:
            for key in ("oxidation_state", "coordination", "radius_angstrom", "source_id"):
                if key not in row:
                    raise AssertionError(f"Missing {key} in ionic radius row for {symbol}: {row}")
            if not isinstance(row["oxidation_state"], int):
                raise AssertionError(f"Invalid oxidation_state in ionic radius row for {symbol}")
            if not isinstance(row["coordination"], str) or not row["coordination"]:
                raise AssertionError(f"Invalid coordination in ionic radius row for {symbol}")
            if not _positive_number(row["radius_angstrom"]):
                raise AssertionError(f"Invalid radius_angstrom in ionic radius row for {symbol}")
            if row["source_id"] in FORBIDDEN_SOURCE_IDS:
                raise AssertionError(f"Forbidden ionic radius source for {symbol}")
            if row.get("method") not in {"smact_shannon", "pymatgen_ionic_radii", "mendeleev_ionic_radius"}:
                raise AssertionError(f"Invalid ionic radius method for {symbol}: {row.get('method')}")
            if not isinstance(row.get("notes"), list):
                raise AssertionError(f"ionic radius notes must be a list for {symbol}")

    if radius_policy.get("policy_id") != "qlip_radius_policy_v1":
        raise AssertionError("radius_policy.json must define qlip_radius_policy_v1")
    if radius_policy.get("allow_synthetic_fallback") is not False:
        raise AssertionError("radius_policy.json must forbid synthetic fallback")
    if radius_policy.get("missing_radius_code") != "radii_data_missing":
        raise AssertionError("radius_policy.json must use radii_data_missing")

    if pair_policy.get("radius_policy_id") != radius_policy.get("policy_id"):
        raise AssertionError("pair_distance_policy.json must reference a real radius_policy_id")
    if pair_policy.get("source_id") != "qlip_policy_v1":
        raise AssertionError("pair_distance_policy.json must be tagged with qlip_policy_v1")
    valid_range = pair_policy.get("valid_scale_range")
    if not isinstance(valid_range, list) or len(valid_range) != 2:
        raise AssertionError("pair_distance_policy.json must include valid_scale_range")

    package_versions = provenance.get("package_versions")
    if not isinstance(package_versions, dict) or set(package_versions) < REQUIRED_PACKAGES:
        raise AssertionError("provenance.json must include all required package versions")
    missing_versions = [name for name in REQUIRED_PACKAGES if not package_versions.get(name)]
    if missing_versions:
        raise AssertionError(f"Missing package versions in provenance: {missing_versions}")
    sources = provenance.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise AssertionError("provenance.json must define sources")
    if not provenance.get("generated_at_utc") or not provenance.get("generator"):
        raise AssertionError("provenance.json must include generated_at_utc and generator")
    if not isinstance(provenance.get("field_source_map"), dict) or not provenance["field_source_map"]:
        raise AssertionError("provenance.json must include field_source_map")

    referenced_sources = set(_source_ids(elements)) | set(_source_ids(radii)) | set(_source_ids(ionic))
    referenced_sources.add(radius_policy["source_id"])
    referenced_sources.add(pair_policy["source_id"])
    missing_sources = sorted(source for source in referenced_sources if source not in sources)
    if missing_sources:
        raise AssertionError(f"Missing provenance sources: {missing_sources}")
    forbidden = sorted(source for source in referenced_sources if source in FORBIDDEN_SOURCE_IDS)
    if forbidden:
        raise AssertionError(f"Forbidden synthetic/fake/manual source IDs found: {forbidden}")


def main() -> None:
    validate()
    print(f"Base data validation passed: {DATA_DIR}")


if __name__ == "__main__":
    main()
