"""Merge lawful targeted MP pair-completion records into frozen NASICON v2 corpora."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from spp_maker_qlip.required_pair_extraction import collect_required_pair_distances


REPO_ROOT = Path(__file__).resolve().parents[1]
CRYSTAL_DB_ROOT = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
if str(CRYSTAL_DB_ROOT) not in sys.path:
    sys.path.insert(0, str(CRYSTAL_DB_ROOT))

from crystal_db.db import init_db  # noqa: E402
from scripts.build_crystaldb_corpus import copy_structure_rows  # noqa: E402


TARGET = Composition("Na3Zr2Si2PO12").reduced_composition
FAILED_V1_PAIRS = {"Na-Zr", "Na-Si", "Zr-Zr", "Si-Zr", "P-Zr", "Si-Si", "P-Si", "P-P"}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_sid(conn: sqlite3.Connection, material_id: str) -> str:
    row = conn.execute(
        "SELECT structure_id FROM provenance WHERE source_id IN (?, ?) ORDER BY structure_id LIMIT 1",
        (material_id, f"{material_id}.cif"),
    ).fetchone()
    if row is None:
        raise ValueError(f"No source structure for {material_id}")
    return str(row[0])


def _new_records(manifest_path: Path, source_db: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    source = sqlite3.connect(source_db)
    source.row_factory = sqlite3.Row
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for row in rows:
        if row.get("status") != "OK" or not row.get("cif_path"):
            rejected.append({"material_id": row.get("material_id"), "reason": "acquisition_not_ok"})
            continue
        cif_path = Path(str(row["cif_path"]))
        if not cif_path.is_absolute():
            cif_path = CRYSTAL_DB_ROOT / cif_path
        structure = Structure.from_file(cif_path)
        elements = sorted(element.symbol for element in structure.composition.elements)
        present_pairs = {
            "-".join(sorted((left, right), key=str.lower))
            for left in elements for right in elements
        }
        supported_sparse_pairs = sorted(present_pairs & FAILED_V1_PAIRS, key=str.lower)
        if not supported_sparse_pairs:
            rejected.append({"material_id": row.get("material_id"), "reason": "no_sparse_pair_supported"})
            continue
        cif_hash = _sha256(cif_path)
        if cif_hash in seen_hashes:
            rejected.append({"material_id": row.get("material_id"), "reason": "duplicate_new_cif_sha256"})
            continue
        seen_hashes.add(cif_hash)
        material_id = str(row["material_id"])
        analyzer = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
        accepted.append(
            {
                "internal_id": f"nasicon-{material_id.replace('mp-', 'mp')}",
                "source": "Materials Project",
                "source_id": material_id,
                "source_version": "Materials Project API database current at retrieval 2026-08-03",
                "formula": row.get("formula_pretty") or row.get("formula"),
                "reduced_formula": structure.composition.reduced_formula,
                "chemical_system": row.get("chemical_system"),
                "elements": elements,
                "space_group": analyzer.get_space_group_symbol(),
                "space_group_number": analyzer.get_space_group_number(),
                "crystal_system": analyzer.get_crystal_system(),
                "number_of_sites": len(structure),
                "topology_tier": "TIER_2_PAIR_COMPLETION",
                "family_assignment": "NASICON chemically relevant pair completion",
                "family_assignment_method": "targeted_materials_project_chemical_system_query",
                "family_assignment_evidence": {
                    "supported_sparse_pairs": supported_sparse_pairs,
                    "topology_claimed": False,
                    "query_name": "nasicon_v2_pair_support",
                },
                "cif_sha256": cif_hash,
                "builder_manifest_cif_sha256": row.get("cif_sha256"),
                "retrieval_timestamp": row.get("retrieved_at"),
                "license_policy": {
                    "policy_id": "local_cif",
                    "allow_cif_store": True,
                    "allow_cif_return": True,
                    "allow_derivatives": True,
                    "allow_export": False,
                    "notes": "Materials Project API data; external redistribution remains policy-gated.",
                },
                "exact_target": structure.composition.reduced_composition == TARGET,
                "exact_target_exclusion_status": "not_exact_target",
                "near_duplicate_comparison_applicable": set(elements) == {"Na", "Zr", "Si", "P", "O"},
                "near_duplicate_fingerprint_similarity": None,
                "near_duplicate_threshold": 0.95,
                "near_duplicate_metric_scope": "Only target-chemsys records require calibrated fingerprint comparison; none were acquired.",
                "is_ordered": structure.is_ordered,
                "occupancies": sorted({float(value) for site in structure for value in site.species.values()}),
                "source_cif_path": str(cif_path),
                "source_db_path": str(source_db),
                "source_structure_id": _source_sid(source, material_id),
                "energy_above_hull_eV_per_atom": row.get("energy_above_hull"),
                "formation_energy_eV_per_atom": row.get("formation_energy_per_atom"),
            }
        )
    source.close()
    return accepted, rejected


def _freeze(
    *, base_root: Path, out_root: Path, corpus_id: str, additions: list[dict[str, Any]], source_db: Path
) -> list[dict[str, Any]]:
    if out_root.exists():
        raise FileExistsError(f"Refusing to overwrite existing corpus: {out_root}")
    (out_root / "cifs").mkdir(parents=True)
    (out_root / "records").mkdir()
    base_records = [
        json.loads(line) for line in (base_root / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    existing_hashes = {str(row["cif_sha256"]) for row in base_records}
    existing_sources = {str(row["source_id"]) for row in base_records}
    retained_additions = [
        dict(row) for row in additions
        if row["cif_sha256"] not in existing_hashes and row["source_id"] not in existing_sources
    ]
    records = [dict(row) for row in base_records] + retained_additions

    shutil.copy2(base_root / "crystaldb.sqlite", out_root / "crystaldb.sqlite")
    dest = sqlite3.connect(out_root / "crystaldb.sqlite")
    dest.row_factory = sqlite3.Row
    init_db(dest)
    dest.execute("UPDATE structure_annotations SET corpus_id=?", (corpus_id,))
    source = sqlite3.connect(source_db)
    source.row_factory = sqlite3.Row
    try:
        for record in records:
            source_cif = Path(str(record.get("source_cif_path") or record.get("frozen_cif_path")))
            if not source_cif.is_absolute():
                source_cif = CRYSTAL_DB_ROOT / source_cif
            if not source_cif.is_file():
                source_cif = base_root / "cifs" / f"{record['internal_id']}.cif"
            frozen = out_root / "cifs" / f"{record['internal_id']}.cif"
            shutil.copy2(source_cif, frozen)
            record["frozen_cif_path"] = str(frozen)
            (out_root / "records" / f"{record['internal_id']}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        for record in retained_additions:
            copy_structure_rows(source, dest, record["source_structure_id"], record["internal_id"])
            dest.execute(
                "INSERT OR REPLACE INTO structure_annotations "
                "(structure_id, corpus_id, topology_tier, family_assignment, family_assignment_method, "
                "family_assignment_evidence_json, source_version, chemical_system, crystal_system, number_of_sites, "
                "cif_sha256, exact_target_exclusion_status, near_duplicate_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["internal_id"], corpus_id, record["topology_tier"], record["family_assignment"],
                    record["family_assignment_method"], json.dumps(record["family_assignment_evidence"], sort_keys=True),
                    record["source_version"], record["chemical_system"], record["crystal_system"],
                    record["number_of_sites"], record["cif_sha256"], record["exact_target_exclusion_status"],
                    None, datetime.now(timezone.utc).isoformat(),
                ),
            )
        dest.commit()
    finally:
        source.close()
        dest.close()
    (out_root / "manifest.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in records), encoding="utf-8"
    )
    (out_root / "corpus_card.json").write_text(
        json.dumps(
            {
                "corpus_id": corpus_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "structure_count": len(records),
                "new_v2_structure_count": len(retained_additions),
                "topology_tier_counts": dict(Counter(row["topology_tier"] for row in records)),
                "policy": "local research corpus; external CIF export remains policy-gated",
                "parent_corpus_id": _load_json(base_root / "corpus_card.json").get("corpus_id"),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, default=REPO_ROOT / "data" / "corpora")
    parser.add_argument("--artifact-root", type=Path, default=REPO_ROOT / "artifacts" / "nasicon_spp_quality")
    args = parser.parse_args()
    additions, rejected = _new_records(args.manifest.resolve(), args.source_db.resolve())
    args.artifact_root.mkdir(parents=True, exist_ok=True)
    outputs = {}
    for name, base_name in (
        ("nasicon_specialist_v2", "nasicon_specialist_v1"),
        ("nasicon_specialist_leave_target_out_v2", "nasicon_specialist_leave_target_out_v1"),
    ):
        records = _freeze(
            base_root=args.out_root / base_name,
            out_root=args.out_root / name,
            corpus_id=name,
            additions=additions,
            source_db=args.source_db.resolve(),
        )
        outputs[name] = len(records)

    extraction = collect_required_pair_distances(
        cif_dir=(args.manifest.parent / "cifs").resolve(), formula="Na3Zr2Si2PO12", cutoff=6.0
    )
    effect_rows = []
    for cif in extraction["cifs"]:
        material_id = Path(str(cif["file"])).stem
        for pair, stats in cif["geometric_pairs_within_cutoff"].items():
            if pair in FAILED_V1_PAIRS:
                effect_rows.append(
                    {
                        "material_id": material_id,
                        "pair": pair,
                        "added_raw_observations": stats["count"],
                        "minimum_distance_A": stats["min_distance"],
                        "maximum_distance_A": stats["max_distance"],
                    }
                )
    with (args.artifact_root / "NASICON_V2_RECORD_PAIR_EFFECT.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(effect_rows[0]))
        writer.writeheader()
        writer.writerows(effect_rows)
    summary = {
        "acquired_ok": 71,
        "accepted_pair_completion_records": len(additions),
        "rejected": rejected,
        "corpus_counts": outputs,
        "exact_target_additions": sum(bool(row["exact_target"]) for row in additions),
        "target_chemsys_additions": sum(bool(row["near_duplicate_comparison_applicable"]) for row in additions),
        "duplicate_addition_hashes": len(additions) - len({row["cif_sha256"] for row in additions}),
    }
    (args.artifact_root / "NASICON_V2_ENRICHMENT_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
