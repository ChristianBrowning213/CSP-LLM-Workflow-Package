from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pymatgen.core import Composition, Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from crystal_db.db import connect, init_db  # noqa: E402
from crystal_db.fingerprint import fingerprint_structure  # noqa: E402
from scripts.build_crystaldb_corpus import copy_structure_rows  # noqa: E402


TARGET_FORMULA = "Na3Zr2Si2PO12"
TARGET_ELEMENTS = ("Na", "Zr", "Si", "P", "O")
FP_NEAR_DUPLICATE_THRESHOLD = 0.95
CENTER_CUTOFFS = {
    "Zr": 2.55,
    "V": 2.50,
    "Ti": 2.50,
    "Cr": 2.50,
    "Sc": 2.60,
    "Si": 2.05,
    "P": 2.05,
}
KNOWN_NASICON_FORMULAS = {
    "Na3Zr2Si2PO12",
    "Na3V2(PO4)3",
    "Na3Ti2(PO4)3",
    "Na3Cr2(PO4)3",
    "NaZr2(PO4)3",
    "LiZr2(PO4)3",
    "Na4Zr2(SiO4)3",
    "Na3Sc2(PO4)3",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    a = np.asarray(left, dtype=float)
    b = np.asarray(right, dtype=float)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def framework_metrics(structure: Structure) -> dict[str, Any]:
    centers = [index for index, site in enumerate(structure) if site.specie.symbol in CENTER_CUTOFFS]
    coordination = {index: 0 for index in centers}
    shared_oxygen_counts: dict[tuple[int, int], int] = {}
    periodic_edges: list[tuple[int, int, tuple[int, int, int]]] = []
    max_cutoff = max(CENTER_CUTOFFS.values())
    for oxygen in structure:
        if oxygen.specie.symbol != "O":
            continue
        neighbors: list[tuple[int, np.ndarray]] = []
        for neighbor in structure.get_neighbors(oxygen, max_cutoff):
            symbol = neighbor.specie.symbol
            if symbol not in CENTER_CUTOFFS or float(neighbor.nn_distance) > CENTER_CUTOFFS[symbol]:
                continue
            neighbors.append((int(neighbor.index), np.asarray(neighbor.image, dtype=int)))
            coordination[int(neighbor.index)] += 1
        for (left, left_image), (right, right_image) in itertools.combinations(neighbors, 2):
            if left == right:
                continue
            translation = tuple(int(value) for value in (right_image - left_image))
            periodic_edges.append((left, right, translation))
            pair = tuple(sorted((left, right)))
            shared_oxygen_counts[pair] = shared_oxygen_counts.get(pair, 0) + 1

    adjacency: dict[int, list[tuple[int, np.ndarray]]] = {index: [] for index in centers}
    for left, right, translation in periodic_edges:
        vector = np.asarray(translation, dtype=int)
        adjacency[left].append((right, vector))
        adjacency[right].append((left, -vector))

    visited: set[int] = set()
    component_ranks: list[int] = []
    for start in centers:
        if start in visited:
            continue
        potentials = {start: np.zeros(3, dtype=int)}
        stack = [start]
        residuals: list[np.ndarray] = []
        while stack:
            node = stack.pop()
            visited.add(node)
            for neighbor, translation in adjacency[node]:
                candidate = potentials[node] + translation
                if neighbor not in potentials:
                    potentials[neighbor] = candidate
                    stack.append(neighbor)
                else:
                    residual = candidate - potentials[neighbor]
                    if np.any(residual):
                        residuals.append(residual)
        rank = int(np.linalg.matrix_rank(np.asarray(residuals, dtype=float))) if residuals else 0
        component_ranks.append(rank)

    expected = {
        index: 4 if structure[index].specie.symbol in {"Si", "P"} else 6
        for index in centers
    }
    sharing = Counter(shared_oxygen_counts.values())
    total_center_pairs = sum(sharing.values())
    return {
        "framework_center_count": len(centers),
        "framework_components": len(component_ranks),
        "framework_dimensionality": max(component_ranks) if component_ranks else 0,
        "coordination_counts": {
            symbol: [
                coordination[index]
                for index in centers
                if structure[index].specie.symbol == symbol
            ]
            for symbol in CENTER_CUTOFFS
            if any(structure[index].specie.symbol == symbol for index in centers)
        },
        "coordination_expected": {
            "Si": 4,
            "P": 4,
            "other_framework_cations": 6,
        },
        "coordination_all_expected": all(coordination[index] == expected[index] for index in centers),
        "corner_sharing_fraction": (sharing.get(1, 0) / total_center_pairs) if total_center_pairs else 0.0,
        "edge_sharing_fraction": (sharing.get(2, 0) / total_center_pairs) if total_center_pairs else 0.0,
        "face_sharing_fraction": (sum(count for shared, count in sharing.items() if shared >= 3) / total_center_pairs)
        if total_center_pairs
        else 0.0,
        "cutoffs_angstrom": CENTER_CUTOFFS,
    }


def required_pairs() -> list[str]:
    return [
        "-".join(sorted((TARGET_ELEMENTS[i], TARGET_ELEMENTS[j]), key=str.lower))
        for i in range(len(TARGET_ELEMENTS))
        for j in range(i, len(TARGET_ELEMENTS))
    ]


def pair_coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pair in required_pairs():
        left, right = pair.split("-", 1)
        supporters = []
        for record in records:
            elements = set(record["elements"])
            if left in elements and right in elements:
                supporters.append(record["internal_id"])
        rows.append(
            {
                "pair": pair,
                "covered": bool(supporters),
                "support_count": len(supporters),
                "supporting_internal_ids": ";".join(supporters),
            }
        )
    return rows


def source_structure_id(db_path: Path, material_id: str) -> str:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT structure_id FROM provenance WHERE source_id IN (?, ?) ORDER BY structure_id LIMIT 1",
        (f"{material_id}.cif", material_id),
    ).fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"No source database row for {material_id} in {db_path}")
    return str(row[0])


def representation_status(db_path: Path, material_id: str) -> dict[str, Any]:
    sid = source_structure_id(db_path, material_id)
    conn = sqlite3.connect(db_path)
    counts = {
        "crystalcard": conn.execute("SELECT COUNT(*) FROM structure_crystalcards WHERE structure_id=?", (sid,)).fetchone()[0],
        "fingerprint": conn.execute("SELECT COUNT(*) FROM structure_fingerprints WHERE structure_id=?", (sid,)).fetchone()[0],
        "text_doc": conn.execute("SELECT COUNT(*) FROM text_docs WHERE structure_id=? AND status='OK'", (sid,)).fetchone()[0],
        "text_embedding": conn.execute(
            "SELECT COUNT(*) FROM text_embeddings e JOIN text_docs d ON d.id=e.text_doc_id WHERE d.structure_id=? AND e.status='OK'",
            (sid,),
        ).fetchone()[0],
        "sequence": conn.execute("SELECT COUNT(*) FROM structure_sequences WHERE structure_id=?", (sid,)).fetchone()[0],
        "sequence_embedding": conn.execute(
            "SELECT COUNT(*) FROM structure_embeddings WHERE structure_id=? AND modality='seq'", (sid,)
        ).fetchone()[0],
    }
    conn.close()
    return {"source_structure_id": sid, **{key: bool(value) for key, value in counts.items()}}


def build_records(
    *,
    topology_manifest: Path,
    topology_db: Path,
    pair_manifest: Path,
    pair_db: Path,
    reference_cif: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    reference_structure = Structure.from_file(reference_cif)
    reference_fp = fingerprint_structure(cif_text=reference_cif.read_text(encoding="utf-8"), store=False)["vector"]
    records: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for tier, manifest_path, db_path in (
        ("TIER_1_TOPOLOGY", topology_manifest, topology_db),
        ("TIER_2_PAIR_COMPLETION", pair_manifest, pair_db),
    ):
        for source_row in load_manifest(manifest_path):
            cif_path = Path(source_row["cif_path"])
            structure = Structure.from_file(cif_path)
            actual_hash = sha256_file(cif_path)
            if actual_hash in seen_hashes:
                rejected.append({"material_id": source_row["material_id"], "reason": "duplicate_cif_sha256", "cif_sha256": actual_hash})
                continue
            seen_hashes.add(actual_hash)
            metrics = framework_metrics(structure) if tier == "TIER_1_TOPOLOGY" else None
            tier_1_pass = bool(
                source_row.get("formula") in KNOWN_NASICON_FORMULAS
                and structure.is_ordered
                and metrics
                and metrics["coordination_all_expected"]
                and metrics["framework_components"] == 1
                and metrics["framework_dimensionality"] == 3
            )
            if tier == "TIER_1_TOPOLOGY" and not tier_1_pass:
                rejected.append(
                    {
                        "material_id": source_row["material_id"],
                        "reason": "tier_1_geometry_proxy_failed",
                        "framework_metrics": metrics,
                    }
                )
                continue
            if tier == "TIER_2_PAIR_COMPLETION" and not {"Si", "P"}.issubset(
                {element.symbol for element in structure.composition.elements}
            ):
                rejected.append({"material_id": source_row["material_id"], "reason": "tier_2_missing_Si_P_pair"})
                continue

            analyzed = SpacegroupAnalyzer(structure, symprec=0.01, angle_tolerance=5.0)
            fp = fingerprint_structure(cif_text=cif_path.read_text(encoding="utf-8"), store=False)["vector"]
            near_score = cosine_similarity(reference_fp, fp)
            reduced_formula = structure.composition.reduced_formula
            exact_target = Composition(reduced_formula).reduced_composition == Composition(TARGET_FORMULA).reduced_composition
            elements = sorted(element.symbol for element in structure.composition.elements)
            near_duplicate_comparison_applicable = set(elements) == set(TARGET_ELEMENTS)
            reps = representation_status(db_path, str(source_row["material_id"]))
            records.append(
                {
                    "internal_id": f"nasicon-{str(source_row['material_id']).replace('mp-', 'mp')}",
                    "source": "Materials Project",
                    "source_id": source_row["material_id"],
                    "source_version": "Materials Project API database current at retrieval 2026-08-03",
                    "formula": source_row.get("formula_pretty") or source_row.get("formula"),
                    "reduced_formula": reduced_formula,
                    "chemical_system": source_row.get("chemical_system"),
                    "elements": elements,
                    "space_group": analyzed.get_space_group_symbol(),
                    "space_group_number": analyzed.get_space_group_number(),
                    "crystal_system": analyzed.get_crystal_system(),
                    "number_of_sites": len(structure),
                    "topology_tier": tier,
                    "family_assignment": "NASICON" if tier == "TIER_1_TOPOLOGY" else "NASICON chemistry support only",
                    "family_assignment_method": "formula_anchor_plus_coordination_and_3d_periodic_framework_proxy"
                    if tier == "TIER_1_TOPOLOGY"
                    else "required_pair_chemistry_query",
                    "family_assignment_evidence": metrics
                    if metrics is not None
                    else {"required_pair": "Si-P", "topology_claimed": False},
                    "cif_sha256": actual_hash,
                    "builder_manifest_cif_sha256": source_row.get("cif_sha256"),
                    "retrieval_timestamp": source_row.get("retrieved_at"),
                    "license_policy": {
                        "policy_id": "local_cif",
                        "allow_cif_store": True,
                        "allow_cif_return": True,
                        "allow_derivatives": True,
                        "allow_export": False,
                        "notes": "Materials Project API data; cite MP and review redistribution policy before external CIF export.",
                    },
                    "exact_target": exact_target,
                    "exact_target_exclusion_status": "included_in_full_exact_target" if exact_target else "not_exact_target",
                    "near_duplicate_fingerprint_similarity": near_score,
                    "near_duplicate_threshold": FP_NEAR_DUPLICATE_THRESHOLD,
                    "near_duplicate_comparison_applicable": near_duplicate_comparison_applicable,
                    "near_duplicate_metric_scope": "Crystal-DB fingerprint threshold applied only within the target chemical system, consistent with calibration grouping",
                    "is_ordered": structure.is_ordered,
                    "occupancies": sorted({float(value) for site in structure for value in site.species.values()}),
                    "source_cif_path": str(cif_path),
                    "source_db_path": str(db_path),
                    "representations": reps,
                    "energy_above_hull_eV_per_atom": source_row.get("energy_above_hull"),
                    "formation_energy_eV_per_atom": source_row.get("formation_energy_per_atom"),
                }
            )
    return records, rejected


def safe_rebuild_dir(path: Path, allowed_parent: Path, force: bool) -> None:
    resolved = path.resolve()
    parent = allowed_parent.resolve()
    if parent not in resolved.parents:
        raise ValueError(f"Refusing to rebuild path outside {parent}: {resolved}")
    if resolved.exists():
        if not force:
            raise FileExistsError(f"{resolved} exists; use --force")
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def write_corpus(
    *,
    corpus_id: str,
    records: list[dict[str, Any]],
    out_dir: Path,
    out_root: Path,
    force: bool,
) -> None:
    safe_rebuild_dir(out_dir, out_root, force)
    cif_dir = out_dir / "cifs"
    record_dir = out_dir / "records"
    cif_dir.mkdir()
    record_dir.mkdir()
    db_path = out_dir / "crystaldb.sqlite"
    dest = connect(str(db_path))
    init_db(dest)
    source_connections: dict[str, sqlite3.Connection] = {}
    try:
        for record in records:
            source_cif = Path(record["source_cif_path"])
            destination_cif = cif_dir / f"{record['internal_id']}.cif"
            shutil.copyfile(source_cif, destination_cif)
            if sha256_file(destination_cif) != record["cif_sha256"]:
                raise ValueError(f"CIF hash changed while freezing {record['internal_id']}")
            record["frozen_cif_path"] = str(destination_cif)
            (record_dir / f"{record['internal_id']}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

            source_db = str(record["source_db_path"])
            if source_db not in source_connections:
                conn = sqlite3.connect(source_db)
                conn.row_factory = sqlite3.Row
                source_connections[source_db] = conn
            source_sid = record["representations"]["source_structure_id"]
            new_sid = record["internal_id"]
            copy_structure_rows(source_connections[source_db], dest, source_sid, new_sid)
            dest.execute(
                "INSERT OR REPLACE INTO structure_annotations "
                "(structure_id, corpus_id, topology_tier, family_assignment, family_assignment_method, "
                "family_assignment_evidence_json, source_version, chemical_system, crystal_system, number_of_sites, "
                "cif_sha256, exact_target_exclusion_status, near_duplicate_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_sid,
                    corpus_id,
                    record["topology_tier"],
                    record["family_assignment"],
                    record["family_assignment_method"],
                    json.dumps(record["family_assignment_evidence"], sort_keys=True),
                    record["source_version"],
                    record["chemical_system"],
                    record["crystal_system"],
                    record["number_of_sites"],
                    record["cif_sha256"],
                    record["exact_target_exclusion_status"],
                    record["near_duplicate_fingerprint_similarity"],
                    now_iso(),
                ),
            )
        dest.commit()
    finally:
        for conn in source_connections.values():
            conn.close()
        dest.close()

    with (out_dir / "manifest.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    (out_dir / "corpus_card.json").write_text(
        json.dumps(
            {
                "corpus_id": corpus_id,
                "created_at": now_iso(),
                "structure_count": len(records),
                "topology_tier_counts": dict(Counter(record["topology_tier"] for record in records)),
                "embedding_backend": "lmstudio/text-embedding-bge-m3",
                "near_duplicate_threshold": FP_NEAR_DUPLICATE_THRESHOLD,
                "policy": "local research corpus; external CIF export remains policy-gated",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def write_artifacts(
    *,
    full_records: list[dict[str, Any]],
    leave_records: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    artifact_root: Path,
) -> None:
    artifact_root.mkdir(parents=True, exist_ok=True)
    columns = [
        "internal_id",
        "source",
        "source_id",
        "source_version",
        "formula",
        "reduced_formula",
        "chemical_system",
        "space_group",
        "crystal_system",
        "number_of_sites",
        "topology_tier",
        "family_assignment",
        "family_assignment_method",
        "cif_sha256",
        "retrieval_timestamp",
        "exact_target_exclusion_status",
        "near_duplicate_fingerprint_similarity",
    ]
    with (artifact_root / "NASICON_CORPUS_MANIFEST.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in full_records:
            writer.writerow({column: record.get(column) for column in columns})

    full_coverage = pair_coverage(full_records)
    leave_coverage = pair_coverage(leave_records)
    with (artifact_root / "NASICON_PAIR_COVERAGE.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["corpus", "pair", "covered", "support_count", "supporting_internal_ids"])
        writer.writeheader()
        for corpus, rows in (("nasicon_specialist_v1", full_coverage), ("nasicon_specialist_leave_target_out_v1", leave_coverage)):
            for row in rows:
                writer.writerow({"corpus": corpus, **row})

    summary = {
        "schema_version": "nasicon_corpus_summary.v1",
        "number_acquired": len(full_records) + len(rejected),
        "number_parsed": len(full_records),
        "number_rejected": len(rejected),
        "rejections": rejected,
        "full_structure_count": len(full_records),
        "leave_target_out_structure_count": len(leave_records),
        "topology_tier_counts": dict(Counter(record["topology_tier"] for record in full_records)),
        "leave_target_out_topology_tier_counts": dict(Counter(record["topology_tier"] for record in leave_records)),
        "description_count": sum(bool(record["representations"]["text_doc"]) for record in full_records),
        "embedding_count": sum(bool(record["representations"]["text_embedding"]) for record in full_records),
        "formula_distribution": dict(Counter(record["reduced_formula"] for record in full_records)),
        "element_distribution": dict(Counter(element for record in full_records for element in set(record["elements"]))),
        "space_group_distribution": dict(Counter(record["space_group"] for record in full_records)),
        "duplicate_cif_hash_count": len([item for item in rejected if item.get("reason") == "duplicate_cif_sha256"]),
        "exact_target_exclusions": sum(record["exact_target"] for record in full_records),
        "near_duplicate_exclusions": sum(
            bool(record["near_duplicate_comparison_applicable"])
            and not bool(record["exact_target"])
            and float(record["near_duplicate_fingerprint_similarity"]) >= FP_NEAR_DUPLICATE_THRESHOLD
            for record in full_records
        ),
        "required_pair_coverage_full_complete": all(row["covered"] for row in full_coverage),
        "required_pair_coverage_leave_target_out_complete": all(row["covered"] for row in leave_coverage),
        "required_pair_count": len(full_coverage),
        "embedding_backend": "lmstudio/text-embedding-bge-m3",
        "hash_embedding_fallback_used": False,
        "generated_at": now_iso(),
    }
    (artifact_root / "NASICON_CORPUS_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        "# NASICON specialist corpus ingestion report",
        "",
        f"- Acquired candidates: {summary['number_acquired']}",
        f"- Retained full corpus: {summary['full_structure_count']}",
        f"- Retained leave-target-out corpus: {summary['leave_target_out_structure_count']}",
        f"- Rejected: {summary['number_rejected']}",
        f"- Tier counts: `{json.dumps(summary['topology_tier_counts'], sort_keys=True)}`",
        f"- Descriptions: {summary['description_count']}",
        f"- Production text embeddings: {summary['embedding_count']}",
        f"- Full pair coverage complete: {summary['required_pair_coverage_full_complete']}",
        f"- Leave-target-out pair coverage complete: {summary['required_pair_coverage_leave_target_out_complete']}",
        "",
        "Tier 1 requires a known NASICON-family formula anchor, full ordering, expected octahedral/tetrahedral coordination, a single framework component and rank-3 periodic connectivity under recorded cutoffs. Tier 2 records support Si-P pair statistics only and carry no NASICON topology claim.",
        "",
        "All CIFs came from the Materials Project API. The frozen byte hash is recomputed from each downloaded file because the generic builder manifest hash was observed not to match its written CIF bytes. Crystal-DB's conservative local-CIF policy is preserved: external CIF export remains blocked pending an explicit policy decision and citation review.",
    ]
    (artifact_root / "NASICON_INGESTION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build frozen full and leave-target-out NASICON specialist corpora.")
    parser.add_argument("--topology-manifest", type=Path, required=True)
    parser.add_argument("--topology-db", type=Path, required=True)
    parser.add_argument("--pair-manifest", type=Path, required=True)
    parser.add_argument("--pair-db", type=Path, required=True)
    parser.add_argument("--reference-cif", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records, rejected = build_records(
        topology_manifest=args.topology_manifest,
        topology_db=args.topology_db,
        pair_manifest=args.pair_manifest,
        pair_db=args.pair_db,
        reference_cif=args.reference_cif,
    )
    full_records = records
    leave_records = []
    for record in full_records:
        if record["exact_target"]:
            continue
        if (
            record["near_duplicate_comparison_applicable"]
            and record["near_duplicate_fingerprint_similarity"] >= FP_NEAR_DUPLICATE_THRESHOLD
        ):
            record = dict(record)
            record["exact_target_exclusion_status"] = "excluded_calibrated_near_duplicate"
            continue
        kept = dict(record)
        kept["exact_target_exclusion_status"] = "retained_leave_target_out"
        leave_records.append(kept)
    write_corpus(
        corpus_id="nasicon_specialist_v1",
        records=full_records,
        out_dir=args.out_root / "nasicon_specialist_v1",
        out_root=args.out_root,
        force=args.force,
    )
    write_corpus(
        corpus_id="nasicon_specialist_leave_target_out_v1",
        records=leave_records,
        out_dir=args.out_root / "nasicon_specialist_leave_target_out_v1",
        out_root=args.out_root,
        force=args.force,
    )
    write_artifacts(
        full_records=full_records,
        leave_records=leave_records,
        rejected=rejected,
        artifact_root=args.artifact_root,
    )
    print(
        json.dumps(
            {
                "full": len(full_records),
                "leave_target_out": len(leave_records),
                "rejected": len(rejected),
                "full_pair_coverage": all(row["covered"] for row in pair_coverage(full_records)),
                "leave_pair_coverage": all(row["covered"] for row in pair_coverage(leave_records)),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
