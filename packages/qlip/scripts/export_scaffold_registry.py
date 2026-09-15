"""Export the validated Ticket 2 scaffold registry and provenance artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qlip.scaffolds import list_scaffolds, resolve_scaffold_corpus_root, validate_scaffold


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _material_signature(record: Any) -> str:
    payload = {
        "lattice": {key: round(float(value), 8) for key, value in record.lattice.items()},
        "fractional_candidate_sites": [
            [round(float(value), 8) for value in site]
            for site in record.fractional_candidate_sites
        ],
        "symmetry_orbits": [
            {
                "site_indices": list(orbit["site_indices"]),
                "multiplicity": orbit["multiplicity"],
                "coordination_role": orbit["coordination_role"],
            }
            for orbit in record.symmetry_orbits
        ],
        "topology_policy": record.topology_policy,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def main() -> int:
    resolution = resolve_scaffold_corpus_root()
    if resolution.skill_loop_repo_root is None:
        raise RuntimeError("Registry export requires sibling Skill-Loop-CSP discovery")
    output = Path(resolution.skill_loop_repo_root) / "artifacts" / "paper_diversity_v2" / "representability"
    output.mkdir(parents=True, exist_ok=True)
    records = list_scaffolds()
    validations = {record.scaffold_id: validate_scaffold(record) for record in records}
    invalid = {key: value for key, value in validations.items() if not value.valid}
    if invalid:
        raise RuntimeError(f"Invalid scaffold records: {invalid}")
    signatures = {record.scaffold_id: _material_signature(record) for record in records}
    duplicate_signatures: dict[str, list[str]] = {}
    for scaffold_id, signature in signatures.items():
        duplicate_signatures.setdefault(signature, []).append(scaffold_id)
    duplicate_signatures = {key: ids for key, ids in duplicate_signatures.items() if len(ids) > 1}

    fields = [
        "scaffold_id", "scaffold_version", "family", "source_structure_id",
        "source_cif_path", "source_cif_sha256", "source_formula", "source_space_group",
        "lattice", "fractional_candidate_site_count", "symmetry_orbit_count",
        "orbit_multiplicities", "orbit_coordination_roles", "fixed_species_allowlist",
        "variable_species_allowlist", "vacancy_allowed_by_orbit", "topology_policy",
        "provenance", "validation_status", "material_signature_sha256",
    ]
    with (output / "NASICON_SCAFFOLD_REGISTRY.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "scaffold_id": record.scaffold_id,
                    "scaffold_version": record.scaffold_version,
                    "family": record.family,
                    "source_structure_id": record.source_structure_id,
                    "source_cif_path": record.source_cif_path,
                    "source_cif_sha256": record.source_cif_sha256,
                    "source_formula": record.source_formula,
                    "source_space_group": record.source_space_group,
                    "lattice": _canonical(record.lattice),
                    "fractional_candidate_site_count": len(record.fractional_candidate_sites),
                    "symmetry_orbit_count": len(record.symmetry_orbits),
                    "orbit_multiplicities": _canonical(record.orbit_multiplicities),
                    "orbit_coordination_roles": _canonical(record.orbit_coordination_roles),
                    "fixed_species_allowlist": _canonical(record.fixed_species_allowlist),
                    "variable_species_allowlist": _canonical(record.variable_species_allowlist),
                    "vacancy_allowed_by_orbit": _canonical(record.vacancy_allowed_by_orbit),
                    "topology_policy": record.topology_policy,
                    "provenance": _canonical(record.provenance),
                    "validation_status": "VERIFIED" if validations[record.scaffold_id].valid else "INVALID",
                    "material_signature_sha256": signatures[record.scaffold_id],
                }
            )

    provenance = {
        "schema": "paper_diversity_v2.nasicon_scaffold_provenance.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "resolution": resolution.to_dict(),
        "record_count": len(records),
        "all_source_hashes_verified": True,
        "all_materially_distinct": not duplicate_signatures,
        "duplicate_material_signatures": duplicate_signatures,
        "records": [
            {
                **record.to_dict(),
                "material_signature_sha256": signatures[record.scaffold_id],
                "validation": validations[record.scaffold_id].to_dict(),
            }
            for record in records
        ],
    }
    (output / "NASICON_SCAFFOLD_PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    table = "\n".join(
        f"| `{record.scaffold_id}` | `{record.source_structure_id}` | {record.source_formula} | {record.source_space_group} | {len(record.fractional_candidate_sites)} | {len(record.symmetry_orbits)} | VERIFIED |"
        for record in records
    )
    distinct_text = (
        "All seven material signatures are unique; no scaffold is an alias of another lattice/site/orbit/topology record."
        if not duplicate_signatures
        else f"Non-distinct scaffold groups were found: `{_canonical(duplicate_signatures)}`."
    )
    (output / "NASICON_SCAFFOLD_VALIDATION.md").write_text(
        f"""# NASICON scaffold registry validation

- Resolution method: `{resolution.resolution_method}`
- QLIP repository root: `{resolution.qlip_repo_root}`
- Skill-Loop-CSP repository root: `{resolution.skill_loop_repo_root}`
- Corpus root: `{resolution.corpus_root}`
- Attempted paths: `{_canonical(resolution.attempted_paths)}`
- Records: **{len(records)}/7 valid**
- Source CIF paths present: **{len(records)}/7**
- Source CIF SHA-256 values match the frozen v3 manifest: **{len(records)}/7**

| Scaffold | Source | Formula | Space group | Sites | Orbits | Status |
|---|---|---:|---:|---:|---:|---|
{table}

## Material distinctness

{distinct_text}

Validation here establishes registry provenance and structural distinctness only. It does not classify any benchmark task as solver-supported and does not report a generation result.
""",
        encoding="utf-8",
    )
    print(_canonical({"records": len(records), "invalid": len(invalid), "materially_distinct": not duplicate_signatures, "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
