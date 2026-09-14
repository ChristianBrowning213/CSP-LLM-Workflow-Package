from crystal_db import __main__ as cli
from crystal_db.db import connect, init_db
from crystal_db.describe import describe_structure
from crystal_db.fingerprint import fingerprint_structure
from crystal_db.ingest import ingest_sample
from crystal_db.similarity import similar_structures


def _db_path(tmp_path):
    return str(tmp_path / "crystal.db")


def test_describe_deterministic_and_stored(tmp_path):
    db_path = _db_path(tmp_path)
    ingest_sample(db_path=db_path, count=25)

    first = describe_structure(structure_id="crystal-0001", db_path=db_path, store=True)
    second = describe_structure(structure_id="crystal-0001", db_path=db_path, store=True)

    assert first["descriptor_text"] == second["descriptor_text"]
    assert first["input_hash"] == second["input_hash"]

    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT descriptor_text, input_hash FROM structure_descriptors WHERE structure_id = ?",
        ("crystal-0001",),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["descriptor_text"] == first["descriptor_text"]
    assert row["input_hash"] == first["input_hash"]


def test_fingerprint_deterministic_and_stored(tmp_path):
    db_path = _db_path(tmp_path)
    ingest_sample(db_path=db_path, count=25)

    first = fingerprint_structure(structure_id="crystal-0001", db_path=db_path, store=True)
    second = fingerprint_structure(structure_id="crystal-0001", db_path=db_path, store=True)

    assert first["vector"] == second["vector"]
    assert first["input_hash"] == second["input_hash"]

    conn = connect(db_path)
    init_db(conn)
    row = conn.execute(
        "SELECT vector_json, input_hash FROM structure_fingerprints WHERE structure_id = ?",
        ("crystal-0001",),
    ).fetchone()
    conn.close()

    assert row is not None


def test_similar_returns_neighbors_and_deterministic(tmp_path):
    db_path = _db_path(tmp_path)
    ingest_sample(db_path=db_path, count=25)

    for i in range(1, 26):
        fingerprint_structure(structure_id=f"crystal-{i:04d}", db_path=db_path, store=True)

    first = similar_structures(structure_id="crystal-0001", db_path=db_path, k=5)
    second = similar_structures(structure_id="crystal-0001", db_path=db_path, k=5)

    assert len(first["neighbors"]) <= 5
    assert first["neighbors"] == second["neighbors"]


def test_backfill_commands_run(tmp_path):
    db_path = _db_path(tmp_path)
    ingest_sample(db_path=db_path, count=10)

    assert cli.main(["describe", "--db", db_path, "--all"]) == 0
    assert cli.main(["fingerprint", "--db", db_path, "--all"]) == 0
