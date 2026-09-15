from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from qlip.paper_diversity.record_identity import (
    RecordIdentity,
    canonical_record_key,
    verify_embedding_record,
)


def _record(**changes) -> RecordIdentity:
    vector = changes.pop("embedding_vector", "[1.0,0.0]")
    values = {
        "raw_internal_id": "nasicon-mp1229309", "raw_source": "Materials Project", "raw_source_id": "mp-1229309",
        "description_sha256": "description", "embedding_sha256": hashlib.sha256(vector.encode()).hexdigest(),
        "embedding_dimension": 2, "embedding_model": "text-embedding-bge-m3", "embedding_vector": vector,
    }
    values.update(changes)
    return RecordIdentity(**values)


def test_observed_database_identifier_resolves_to_archived_mp_record() -> None:
    archive = _record()
    database = _record(raw_internal_id="materials_project-abcdef12", raw_source="materials_project", raw_source_id="nasicon-mp1229309.cif")
    result = verify_embedding_record(archive, [database])
    assert result.status == "PASS"
    assert result.resolution_method == "canonical_source_and_source_id"


def test_equivalent_mp_identifier_forms_share_one_canonical_key() -> None:
    expected = canonical_record_key("Materials Project", "mp-1229309")
    assert canonical_record_key("materials_project", "nasicon-mp1229309.cif") == expected
    assert canonical_record_key("materials-project", "mp1229309") == expected


def test_raw_identifiers_remain_in_provenance() -> None:
    record = _record(raw_internal_id="raw-i", raw_source="Materials Project", raw_source_id="nasicon-mp1229309.cif")
    assert record.provenance()["raw_internal_id"] == "raw-i"
    assert record.provenance()["raw_source_id"] == "nasicon-mp1229309.cif"


def test_different_sources_with_same_numeric_suffix_do_not_collide() -> None:
    assert canonical_record_key("Materials Project", "mp-1229309") != canonical_record_key("other_source", "mp-1229309")


def test_description_hash_mismatch_fails_even_when_identity_matches() -> None:
    result = verify_embedding_record(_record(), [_record(description_sha256="wrong")])
    assert result.status == "DESCRIPTION_HASH_MISMATCH"


def test_embedding_hash_mismatch_fails_even_when_identity_matches() -> None:
    result = verify_embedding_record(_record(), [_record(embedding_sha256="wrong")])
    assert result.status == "EMBEDDING_HASH_MISMATCH"


def test_ambiguous_canonical_mapping_fails_explicitly() -> None:
    first = _record(raw_internal_id="db-1", raw_source_id="nasicon-mp1229309.cif")
    second = _record(raw_internal_id="db-2", raw_source_id="mp-1229309")
    assert verify_embedding_record(_record(), [first, second]).status == "AMBIGUOUS_IDENTITY"


def test_all_320_repository_records_resolve_one_to_one() -> None:
    skill = Path(__file__).resolve().parents[2] / "Skill-Loop-CSP"
    corpus = skill / "data" / "corpora" / "nasicon_specialist_v3"
    art = skill / "artifacts" / "paper_diversity_v2" / "nasicon_corpus"
    manifest = {row["internal_id"]: row for row in (json.loads(line) for line in (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())}
    with (art / "NASICON_V3_EMBEDDING_AUDIT.csv").open(encoding="utf-8", newline="") as handle:
        audit = list(csv.DictReader(handle))
    db = sqlite3.connect(corpus / "crystaldb.sqlite"); db.row_factory = sqlite3.Row
    rows = db.execute("select s.structure_id,p.source,p.source_id,td.text_sha256,te.model,te.dim,te.vector from structures s join provenance p on p.structure_id=s.structure_id join text_docs td on td.structure_id=s.structure_id join text_embeddings te on te.text_doc_id=td.id where te.model='text-embedding-bge-m3'").fetchall()
    db.close()
    database = [RecordIdentity(raw_internal_id=row["structure_id"], raw_source=row["source"], raw_source_id=row["source_id"], description_sha256=row["text_sha256"], embedding_sha256=hashlib.sha256(str(row["vector"]).encode()).hexdigest(), embedding_dimension=int(row["dim"]), embedding_model=row["model"], embedding_vector=str(row["vector"])) for row in rows]
    results = []
    for row in audit:
        source = manifest[row["structure_id"]]
        archive = RecordIdentity(raw_internal_id=row["structure_id"], raw_source=source["source"], raw_source_id=source["source_id"], description_sha256=row["description_sha256"], embedding_sha256=row["embedding_sha256"], embedding_dimension=int(row["embedding_dimension"]), embedding_model=row["embedding_model"], archive_key=row["structure_id"])
        results.append(verify_embedding_record(archive, database))
    assert len(results) == 320
    assert all(result.status == "PASS" for result in results)
    assert len({result.database.raw_internal_id for result in results if result.database}) == 320
