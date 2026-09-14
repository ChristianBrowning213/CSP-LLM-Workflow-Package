"""Build versioned layered-battery-oxide and spinel-oxide Crystal-DB corpora."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pymatgen.core import Structure  # noqa: E402

from crystal_db.crystalcard import build_crystalcard  # noqa: E402
from crystal_db.db import connect  # noqa: E402
from crystal_db.embeddings import (  # noqa: E402
    LMSTUDIO_MODEL_NAME,
    LMSTUDIO_MODEL_VERSION,
)
from crystal_db.family_classification import (  # noqa: E402
    CLASSIFIER_VERSION,
    classify_layered_battery_oxide,
    classify_spinel_oxide,
)
from crystal_db.family_dataset import (  # noqa: E402
    DATASET_SCHEMA_VERSION,
    json_safe,
    layered_oxide_candidate_reason,
    spinel_stoichiometry_compatible,
    write_json_atomic,
    write_structure_bundle,
)
from crystal_db.fingerprint import fingerprint_structure  # noqa: E402
from crystal_db.ingest_folder import ingest_folder  # noqa: E402
from crystal_db.text_index import embed_text_docs  # noqa: E402
from crystal_db.textgen import generate_robocrys  # noqa: E402
from scripts.build_crystaldb_corpus import load_mp_api_key  # noqa: E402


DATASET_IDS = {
    "spinel": "MP_SPINEL_OXIDES_V1",
    "layered": "MP_LAYERED_BATTERY_OXIDES_V1",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunks(values: list[str], size: int = 200) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def discover_spinel(mpr: Any) -> list[dict[str, Any]]:
    docs: list[tuple[int, dict[str, Any]]] = []
    fields = [
        "material_id",
        "formula_pretty",
        "symmetry",
        "energy_above_hull",
        "formation_energy_per_atom",
        "is_stable",
    ]
    for count in (2, 3):
        docs.extend(
            (count, doc)
            for doc in mpr.materials.summary.search(
                elements=["O"],
                num_elements=count,
                spacegroup_number=227,
                include_gnome=False,
                fields=fields,
            )
        )
    rows = []
    for element_count, doc in docs:
        formula = str(doc.get("formula_pretty") or "")
        if not spinel_stoichiometry_compatible(formula):
            continue
        rows.append(
            {
                "candidate_key": str(doc["material_id"]),
                "material_id": str(doc["material_id"]),
                "formula": formula,
                "working_ion": None,
                "source_endpoint": "materials.summary",
                "source_query": {
                    "elements": ["O"],
                    "num_elements": element_count,
                    "spacegroup_number": 227,
                    "include_gnome": False,
                    "local_stoichiometry": "AB2O4_or_A3O4",
                },
                "summary": json_safe(doc),
            }
        )
    return sorted(rows, key=lambda row: row["candidate_key"])


def discover_layered(mpr: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted_candidates: dict[tuple[str, str], dict[str, Any]] = {}
    rejected_candidates: list[dict[str, Any]] = []
    fields = [
        "battery_formula",
        "working_ion",
        "framework_formula",
        "formula_charge",
        "formula_discharge",
        "id_charge",
        "id_discharge",
        "material_ids",
    ]
    for ion in ("Li", "Na"):
        docs = mpr.materials.insertion_electrodes.search(
            working_ion=ion,
            elements=["O"],
            fields=fields,
        )
        for doc in docs:
            material_id = str(doc.get("id_discharge") or "")
            formula = str(doc.get("formula_discharge") or "")
            reason = layered_oxide_candidate_reason(formula, ion)
            base = {
                "candidate_key": f"{ion}_{material_id or 'missing'}",
                "material_id": material_id or None,
                "formula": formula,
                "working_ion": ion,
                "source_endpoint": "materials.insertion_electrodes",
                "source_query": {
                    "working_ion": ion,
                    "elements": ["O"],
                    "structure_role": "discharged",
                },
                "electrode": json_safe(doc),
            }
            if not material_id or reason:
                rejected_candidates.append(
                    {**base, "status": "REJECTED", "reason_codes": [reason or "STRUCTURE_ID_MISSING"]}
                )
                continue
            accepted_candidates[(ion, material_id)] = base
    rows = sorted(accepted_candidates.values(), key=lambda row: row["candidate_key"])
    rejected_candidates.sort(key=lambda row: row["candidate_key"])
    return rows, rejected_candidates


def fetch_summaries(mpr: Any, material_ids: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    fields = [
        "material_id",
        "formula_pretty",
        "symmetry",
        "structure",
        "energy_above_hull",
        "formation_energy_per_atom",
        "is_stable",
    ]
    for batch in chunks(sorted(set(material_ids))):
        for doc in mpr.materials.summary.search(material_ids=batch, fields=fields):
            result[str(doc["material_id"])] = doc
    return result


def source_id_map(db_path: Path) -> dict[str, str]:
    conn = connect(str(db_path))
    rows = conn.execute(
        "SELECT source_id, structure_id FROM provenance WHERE source = 'materials_project'"
    ).fetchall()
    conn.close()
    return {str(row["source_id"]): str(row["structure_id"]) for row in rows}


def requires_robocrys(family: str, primitive_structure: Structure) -> bool:
    max_sites = 28 if family == "spinel" else 24
    elements = {element.symbol for element in primitive_structure.composition.elements}
    return primitive_structure.is_ordered and len(primitive_structure) <= max_sites and "O" in elements


def build_family(
    *,
    family: str,
    candidates: list[dict[str, Any]],
    acquisition_rejections: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    output_root: Path,
    database_version: str,
    skip_embeddings: bool,
) -> dict[str, Any]:
    dataset_id = DATASET_IDS[family]
    root = output_root / dataset_id
    records_dir = root / "records"
    cifs_dir = root / "candidate_cifs"
    write_json_atomic(root / "raw_candidates.json", {"rows": candidates})
    write_json_atomic(root / "acquisition_rejections.json", {"rows": acquisition_rejections})

    missing: list[dict[str, Any]] = []
    for candidate in candidates:
        summary = summaries.get(str(candidate["material_id"]))
        if not summary or not summary.get("structure"):
            missing.append(
                {**candidate, "status": "ERROR", "reason_codes": ["MP_STRUCTURE_MISSING"]}
            )
            continue
        key = candidate["candidate_key"]
        bundle = write_structure_bundle(
            root / "structures", key, Structure.from_dict(summary["structure"])
        )
        primitive_text = Path(bundle["paths"]["primitive"]).read_text(encoding="utf-8")
        cifs_dir.mkdir(parents=True, exist_ok=True)
        (cifs_dir / f"{key}.cif").write_text(primitive_text, encoding="utf-8")
        candidate["summary"] = json_safe({k: v for k, v in summary.items() if k != "structure"})
        candidate["structure_bundle"] = bundle

    db_path = root / f"{dataset_id}.db"
    ingest_folder(
        db_path=str(db_path),
        folder_path=str(cifs_dir),
        source="materials_project",
        policy_name="local_cif",
    )
    ids = source_id_map(db_path)
    rows: list[dict[str, Any]] = []
    accepted_ids: list[str] = []
    for index, candidate in enumerate(candidates, start=1):
        key = candidate["candidate_key"]
        structure_id = ids.get(f"{key}.cif")
        if not structure_id or "structure_bundle" not in candidate:
            continue
        record_path = records_dir / f"{key}.json"
        if record_path.is_file():
            previous = json.loads(record_path.read_text(encoding="utf-8"))
            if previous.get("classifier_version") == CLASSIFIER_VERSION:
                rows.append(previous)
                if previous.get("status") == "ACCEPTED":
                    accepted_ids.append(structure_id)
                continue
        structure = Structure.from_file(candidate["structure_bundle"]["paths"]["primitive"])
        robocrys = None
        if requires_robocrys(family, structure):
            robocrys = generate_robocrys(structure_id=structure_id, db_path=str(db_path))
        if robocrys is not None and "error" in robocrys:
            record = {
                **candidate,
                "structure_id": structure_id,
                "status": "ERROR",
                "reason_codes": ["ROBOCRYS_ERROR"],
                "error": robocrys,
                "classifier_version": CLASSIFIER_VERSION,
            }
        else:
            if family == "spinel":
                decision = classify_spinel_oxide(
                    structure,
                    robocrys_description=robocrys["text"] if robocrys else None,
                    robocrys_condensed=robocrys["condensed"] if robocrys else None,
                )
            else:
                decision = classify_layered_battery_oxide(
                    structure,
                    working_ion=str(candidate["working_ion"]),
                    robocrys_description=robocrys["text"] if robocrys else None,
                    robocrys_condensed=robocrys["condensed"] if robocrys else None,
                )
            record = {
                **candidate,
                "structure_id": structure_id,
                "status": decision.status,
                "reason_codes": list(decision.reason_codes),
                "classifier_version": decision.classifier_version,
                "classifier_evidence": decision.evidence,
                "robocrys": robocrys,
            }
            if decision.accepted:
                build_crystalcard(structure_id=structure_id, db_path=str(db_path), store=True)
                fingerprint_structure(structure_id=structure_id, db_path=str(db_path), store=True)
                accepted_ids.append(structure_id)
        write_json_atomic(record_path, record)
        rows.append(record)
        if index % 25 == 0 or index == len(candidates):
            print(f"[{dataset_id}] {index}/{len(candidates)} classified")

    rows.extend(missing)
    rows.extend(acquisition_rejections)
    rows.sort(key=lambda row: str(row.get("candidate_key") or ""))
    for status, filename in (
        ("ACCEPTED", "accepted.json"),
        ("QUARANTINED", "quarantined.json"),
        ("REJECTED", "rejected.json"),
        ("ERROR", "errors.json"),
    ):
        write_json_atomic(root / filename, {"rows": [row for row in rows if row.get("status") == status]})

    embedding_result: dict[str, Any] = {"status": "SKIPPED"}
    if not skip_embeddings and accepted_ids:
        embedding_result = embed_text_docs(
            db_path=str(db_path),
            text_engine="robocrys",
            text_view="robocrys",
            embed_engine="lmstudio",
            model_name=LMSTUDIO_MODEL_NAME,
            model_version=LMSTUDIO_MODEL_VERSION,
            structure_ids=sorted(set(accepted_ids)),
            batch=8,
            progress_every=25,
        )
    counts = dict(Counter(str(row.get("status")) for row in rows))
    manifest = {
        "dataset_id": dataset_id,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "materials_project_database_version": database_version,
        "generated_at": now_iso(),
        "counts": counts,
        "accepted_structure_ids": sorted(set(accepted_ids)),
        "database_path": str(db_path),
        "embedding": embedding_result,
        "fingerprint_method": "fp.simple.v1",
        "source": "Materials Project",
        "source_license_notes": "Check Materials Project terms before redistribution/export.",
    }
    write_json_atomic(root / "dataset_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=REPO_ROOT / "artifacts" / "mp_oxide_families_v1")
    parser.add_argument("--family", choices=("all", "spinel", "layered"), default="all")
    parser.add_argument("--limit", type=int, default=0, help="Deterministic per-family development limit; 0 means all.")
    parser.add_argument("--skip-embeddings", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api_key = load_mp_api_key()
    if not api_key:
        raise SystemExit("Materials Project API credential is unavailable")
    from mp_api.client import MPRester

    families = ("spinel", "layered") if args.family == "all" else (args.family,)
    manifests = []
    with MPRester(
        api_key,
        use_document_model=False,
        mute_progress_bars=True,
    ) as mpr:
        database_version = str(mpr.get_database_version())
        for family in families:
            if family == "spinel":
                candidates = discover_spinel(mpr)
                acquisition_rejections: list[dict[str, Any]] = []
            else:
                candidates, acquisition_rejections = discover_layered(mpr)
            if args.limit > 0:
                candidates = candidates[: args.limit]
            summaries = fetch_summaries(
                mpr, [str(row["material_id"]) for row in candidates if row.get("material_id")]
            )
            manifests.append(
                build_family(
                    family=family,
                    candidates=candidates,
                    acquisition_rejections=acquisition_rejections,
                    summaries=summaries,
                    output_root=args.output_root,
                    database_version=database_version,
                    skip_embeddings=args.skip_embeddings,
                )
            )
    write_json_atomic(args.output_root / "build_manifest.json", {"datasets": manifests})
    for manifest in manifests:
        print(manifest["dataset_id"], manifest["counts"], manifest["database_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
