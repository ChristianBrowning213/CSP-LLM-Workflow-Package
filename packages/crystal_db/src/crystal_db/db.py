import os
import sqlite3
from pathlib import Path
from typing import Optional

DATA_ROOT_ENV = "CRYSTAL_DB_DATA_ROOT"
DEFAULT_DB_FILENAME = "crystal_phase0.db"


def resolve_data_root() -> Path:
    """Resolve external runtime data without relying on a source checkout."""
    configured = os.getenv(DATA_ROOT_ENV)
    root = Path(configured).expanduser() if configured else Path.cwd() / ".crystal_db"
    return root.resolve()


def resolve_db_path(db_path: Optional[str] = None) -> str:
    if db_path:
        path_value = Path(db_path)
        if path_value.is_absolute():
            return str(path_value.resolve())
        return str((resolve_data_root() / path_value).resolve())
    env_path = os.getenv("CRYSTAL_DB_PATH") or os.getenv("CRYSTALDB_PATH")
    if env_path:
        path_value = Path(env_path)
        if path_value.is_absolute():
            return str(path_value.resolve())
        return str((resolve_data_root() / path_value).resolve())
    return str((resolve_data_root() / DEFAULT_DB_FILENAME).resolve())


def _to_file_uri(path: str) -> str:
    normalized = os.path.abspath(path).replace("\\", "/")
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return f"file:{normalized}"


def connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = resolve_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    uri = _to_file_uri(path) + "?mode=rwc&cache=shared"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = OFF;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS structures (
            structure_id TEXT PRIMARY KEY,
            cif_text TEXT,
            reduced_formula TEXT,
            nsites INTEGER,
            volume REAL,
            license_restricted INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS metadata (
            structure_id TEXT PRIMARY KEY,
            formula TEXT,
            elements_csv TEXT,
            space_group TEXT,
            band_gap_eV REAL,
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS provenance (
            structure_id TEXT PRIMARY KEY,
            source TEXT,
            source_id TEXT,
            retrieved_at TEXT,
            license_notes TEXT,
            policy_id TEXT,
            allow_cif_store INTEGER,
            allow_cif_return INTEGER,
            allow_derivatives INTEGER,
            allow_export INTEGER,
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS structure_descriptors (
            structure_id TEXT,
            descriptor_version TEXT,
            descriptor_text TEXT,
            key_features_json TEXT,
            input_hash TEXT,
            generated_at TEXT,
            PRIMARY KEY (structure_id, descriptor_version),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS structure_fingerprints (
            structure_id TEXT,
            fingerprint_method TEXT,
            fingerprint_version TEXT,
            vector_json TEXT,
            feature_names_json TEXT,
            input_hash TEXT,
            generated_at TEXT,
            PRIMARY KEY (structure_id, fingerprint_method, fingerprint_version),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            created_at TEXT,
            command TEXT,
            args_json TEXT,
            status TEXT,
            error_text TEXT,
            run_name TEXT,
            config_json TEXT
        );

        CREATE TABLE IF NOT EXISTS run_steps (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            tool_name TEXT,
            input_json TEXT,
            input_hash TEXT,
            output_json TEXT,
            output_hash TEXT,
            started_at TEXT,
            ended_at TEXT,
            status TEXT,
            error_text TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            run_id TEXT,
            step_id INTEGER,
            tool_name TEXT,
            input_json TEXT,
            input_hash TEXT,
            output_json TEXT,
            output_hash TEXT,
            started_at TEXT,
            ended_at TEXT,
            status TEXT,
            error_text TEXT,
            PRIMARY KEY (run_id, step_id),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS answer_evidence (
            run_id TEXT PRIMARY KEY,
            evidence_json TEXT,
            created_at TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS evidence_bundles (
            bundle_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            kind TEXT,
            payload_json TEXT,
            created_at TEXT,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS explored_structures (
            run_id TEXT,
            structure_id TEXT,
            reason TEXT,
            role TEXT,
            created_at TEXT,
            PRIMARY KEY (run_id, structure_id, role),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS proposed_structures (
            run_id TEXT,
            proposed_id TEXT,
            proposal_id TEXT,
            source TEXT,
            cif_path TEXT,
            structure_id TEXT,
            status TEXT,
            notes TEXT,
            cif_text_or_path TEXT,
            input_hash TEXT,
            created_at TEXT,
            PRIMARY KEY (run_id, proposed_id),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS novelty_results (
            run_id TEXT,
            proposed_id TEXT,
            is_novel INTEGER,
            best_match_structure_id TEXT,
            best_distance REAL,
            threshold REAL,
            neighbors_json TEXT,
            timings_json TEXT,
            created_at TEXT,
            PRIMARY KEY (run_id, proposed_id),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );


        CREATE TABLE IF NOT EXISTS structure_texts (
            structure_id TEXT,
            engine TEXT,
            version TEXT,
            text TEXT,
            input_hash TEXT,
            generated_at TEXT,
            PRIMARY KEY (structure_id, engine, version),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS text_docs (
            id INTEGER PRIMARY KEY,
            structure_id TEXT NOT NULL,
            engine TEXT NOT NULL,
            text_view TEXT NOT NULL DEFAULT 'robocrys',
            engine_version TEXT NOT NULL,
            text TEXT,
            text_sha256 TEXT,
            status TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (structure_id, engine, engine_version),
            UNIQUE (structure_id, engine, text_view),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS robocrys_condensed (
            structure_id TEXT NOT NULL,
            engine_version TEXT NOT NULL,
            condensed_json TEXT NOT NULL,
            condensed_sha256 TEXT NOT NULL,
            description_sha256 TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            PRIMARY KEY (structure_id, engine_version),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS text_embeddings (
            id INTEGER PRIMARY KEY,
            text_doc_id INTEGER NOT NULL,
            embed_engine TEXT NOT NULL,
            model TEXT NOT NULL,
            model_version TEXT NOT NULL,
            dim INTEGER,
            vector TEXT,
            status TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (text_doc_id, embed_engine, model, model_version),
            FOREIGN KEY(text_doc_id) REFERENCES text_docs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS query_embeddings (
            id INTEGER PRIMARY KEY,
            query_sha256 TEXT NOT NULL,
            query_text TEXT NOT NULL,
            embed_engine TEXT NOT NULL,
            model TEXT NOT NULL,
            model_version TEXT NOT NULL,
            dim INTEGER,
            vector TEXT,
            status TEXT NOT NULL,
            error_type TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (query_sha256, embed_engine, model, model_version)
        );

        CREATE TABLE IF NOT EXISTS structure_sequences (
            structure_id TEXT,
            format TEXT,
            seq_text TEXT,
            input_hash TEXT,
            generated_at TEXT,
            PRIMARY KEY (structure_id, format),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS structure_embeddings (
            structure_id TEXT,
            modality TEXT,
            model_name TEXT,
            model_version TEXT,
            vector_json TEXT,
            dim INTEGER,
            input_hash TEXT,
            generated_at TEXT,
            PRIMARY KEY (structure_id, modality, model_name, model_version),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );
        CREATE TABLE IF NOT EXISTS structure_crystalcards (
            structure_id TEXT,
            engine TEXT,
            version TEXT,
            card_json TEXT,
            input_hash TEXT,
            generated_at TEXT,
            PRIMARY KEY (structure_id, engine, version),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS structure_annotations (
            structure_id TEXT,
            corpus_id TEXT,
            topology_tier TEXT,
            family_assignment TEXT,
            family_assignment_method TEXT,
            family_assignment_evidence_json TEXT,
            source_version TEXT,
            chemical_system TEXT,
            crystal_system TEXT,
            number_of_sites INTEGER,
            cif_sha256 TEXT,
            exact_target_exclusion_status TEXT,
            near_duplicate_score REAL,
            created_at TEXT,
            PRIMARY KEY (structure_id, corpus_id),
            FOREIGN KEY(structure_id) REFERENCES structures(structure_id)
        );

        CREATE TABLE IF NOT EXISTS candidates (
            run_id TEXT,
            candidate_id TEXT,
            input_path TEXT,
            input_hash TEXT,
            source TEXT,
            created_at TEXT,
            meta_json TEXT,
            PRIMARY KEY (run_id, candidate_id),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE TABLE IF NOT EXISTS candidate_results (
            run_id TEXT,
            candidate_id TEXT,
            novelty_json TEXT,
            neighbors_json TEXT,
            property_comps_json TEXT,
            created_at TEXT,
            PRIMARY KEY (run_id, candidate_id),
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        );

        CREATE INDEX IF NOT EXISTS idx_metadata_formula ON metadata(formula);
        CREATE INDEX IF NOT EXISTS idx_metadata_space_group ON metadata(space_group);
        CREATE INDEX IF NOT EXISTS idx_metadata_band_gap ON metadata(band_gap_eV);
        CREATE INDEX IF NOT EXISTS idx_metadata_elements ON metadata(elements_csv);
        CREATE INDEX IF NOT EXISTS idx_desc_version ON structure_descriptors(descriptor_version);
        CREATE INDEX IF NOT EXISTS idx_fp_method_version ON structure_fingerprints(fingerprint_method, fingerprint_version);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prov_source_id ON provenance(source, source_id);
        CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id);
        CREATE INDEX IF NOT EXISTS idx_run_steps_run ON run_steps(run_id);
        CREATE INDEX IF NOT EXISTS idx_run_steps_tool ON run_steps(tool_name);
        CREATE INDEX IF NOT EXISTS idx_run_steps_status ON run_steps(status);
        CREATE INDEX IF NOT EXISTS idx_evidence_bundles_run ON evidence_bundles(run_id);
        CREATE INDEX IF NOT EXISTS idx_explored_run ON explored_structures(run_id);
        CREATE INDEX IF NOT EXISTS idx_proposed_run ON proposed_structures(run_id);
        CREATE INDEX IF NOT EXISTS idx_novelty_run ON novelty_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_crystalcards_structure ON structure_crystalcards(structure_id);
        CREATE INDEX IF NOT EXISTS idx_annotations_corpus ON structure_annotations(corpus_id, topology_tier);
        CREATE INDEX IF NOT EXISTS idx_annotations_family ON structure_annotations(family_assignment);
        CREATE INDEX IF NOT EXISTS idx_texts_engine ON structure_texts(engine, version);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_text_docs_unique ON text_docs(structure_id, engine, engine_version);
        CREATE INDEX IF NOT EXISTS idx_text_docs_status ON text_docs(status, engine);
        CREATE INDEX IF NOT EXISTS idx_text_docs_structure ON text_docs(structure_id);
        CREATE INDEX IF NOT EXISTS idx_robocrys_condensed_structure ON robocrys_condensed(structure_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_text_embeddings_unique ON text_embeddings(text_doc_id, embed_engine, model, model_version);
        CREATE INDEX IF NOT EXISTS idx_text_embeddings_status ON text_embeddings(status, embed_engine, model);
        CREATE INDEX IF NOT EXISTS idx_text_embeddings_doc ON text_embeddings(text_doc_id);
        CREATE INDEX IF NOT EXISTS idx_query_embeddings_space ON query_embeddings(embed_engine, model, model_version);
        CREATE INDEX IF NOT EXISTS idx_query_embeddings_sha ON query_embeddings(query_sha256);
        CREATE INDEX IF NOT EXISTS idx_sequences_format ON structure_sequences(format);
        CREATE INDEX IF NOT EXISTS idx_embeddings_modality ON structure_embeddings(modality, model_name, model_version);
        CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id);
        CREATE INDEX IF NOT EXISTS idx_candidate_results_run ON candidate_results(run_id);
        """
    )
    conn.commit()
    _ensure_columns(conn)


def _ensure_columns(conn: sqlite3.Connection) -> None:
    _ensure_table_columns(
        conn,
        "runs",
        {
            "command": "TEXT",
            "args_json": "TEXT",
            "status": "TEXT",
            "error_text": "TEXT",
            "run_name": "TEXT",
            "config_json": "TEXT",
        },
    )
    _ensure_table_columns(
        conn,
        "run_steps",
        {
            "run_id": "TEXT",
            "tool_name": "TEXT",
            "input_json": "TEXT",
            "input_hash": "TEXT",
            "output_json": "TEXT",
            "output_hash": "TEXT",
            "started_at": "TEXT",
            "ended_at": "TEXT",
            "status": "TEXT",
            "error_text": "TEXT",
        },
    )
    _ensure_table_columns(
        conn,
        "evidence_bundles",
        {
            "run_id": "TEXT",
            "kind": "TEXT",
            "payload_json": "TEXT",
            "created_at": "TEXT",
        },
    )
    _ensure_table_columns(
        conn,
        "explored_structures",
        {
            "reason": "TEXT",
            "role": "TEXT",
            "created_at": "TEXT",
        },
    )
    _ensure_table_columns(
        conn,
        "proposed_structures",
        {
            "proposal_id": "TEXT",
            "source": "TEXT",
            "cif_path": "TEXT",
            "structure_id": "TEXT",
            "status": "TEXT",
            "notes": "TEXT",
            "cif_text_or_path": "TEXT",
            "input_hash": "TEXT",
            "created_at": "TEXT",
        },
    )
    columns = _get_columns(conn, "provenance")
    missing = {
        "policy_id": "TEXT",
        "allow_cif_store": "INTEGER",
        "allow_cif_return": "INTEGER",
        "allow_derivatives": "INTEGER",
        "allow_export": "INTEGER",
    }
    for name, col_type in missing.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE provenance ADD COLUMN {name} {col_type}")
    novelty_columns = _get_columns(conn, "novelty_results")
    if "timings_json" not in novelty_columns:
        conn.execute("ALTER TABLE novelty_results ADD COLUMN timings_json TEXT")
    _ensure_table_columns(
        conn,
        "text_docs",
        {
            "text_view": "TEXT NOT NULL DEFAULT 'robocrys'",
            "text": "TEXT",
            "text_sha256": "TEXT",
            "status": "TEXT",
            "error_type": "TEXT",
            "error_message": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
    )
    _ensure_table_columns(
        conn,
        "text_embeddings",
        {
            "text_doc_id": "INTEGER",
            "embed_engine": "TEXT",
            "model": "TEXT",
            "model_version": "TEXT",
            "dim": "INTEGER",
            "vector": "TEXT",
            "status": "TEXT",
            "error_type": "TEXT",
            "error_message": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
    )
    _ensure_table_columns(
        conn,
        "query_embeddings",
        {
            "query_sha256": "TEXT",
            "query_text": "TEXT",
            "embed_engine": "TEXT",
            "model": "TEXT",
            "model_version": "TEXT",
            "dim": "INTEGER",
            "vector": "TEXT",
            "status": "TEXT",
            "error_type": "TEXT",
            "error_message": "TEXT",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        },
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_text_docs_unique ON text_docs(structure_id, engine, engine_version)")
    text_docs_index_rows = conn.execute("PRAGMA index_list(text_docs)").fetchall()
    text_docs_view_index = None
    for row in text_docs_index_rows:
        if row["name"] == "idx_text_docs_view_unique":
            text_docs_view_index = row
            break
    needs_view_index_rebuild = text_docs_view_index is None or int(text_docs_view_index["unique"]) != 1
    if needs_view_index_rebuild:
        conn.execute(
            "DELETE FROM text_docs "
            "WHERE id IN ("
            "SELECT old.id FROM text_docs old "
            "JOIN text_docs keep "
            "ON keep.structure_id = old.structure_id "
            "AND keep.engine = old.engine "
            "AND keep.text_view = old.text_view "
            "AND ("
            "COALESCE(keep.updated_at, keep.created_at, '') > COALESCE(old.updated_at, old.created_at, '') "
            "OR (COALESCE(keep.updated_at, keep.created_at, '') = COALESCE(old.updated_at, old.created_at, '') AND keep.id > old.id)"
            ")"
            ")"
        )
        conn.execute("DROP INDEX IF EXISTS idx_text_docs_view_unique")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_text_docs_view_unique ON text_docs(structure_id, engine, text_view)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_docs_status ON text_docs(status, engine)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_docs_structure ON text_docs(structure_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_text_embeddings_unique "
        "ON text_embeddings(text_doc_id, embed_engine, model, model_version)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_embeddings_status ON text_embeddings(status, embed_engine, model)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_text_embeddings_doc ON text_embeddings(text_doc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_query_embeddings_space ON query_embeddings(embed_engine, model, model_version)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_query_embeddings_sha ON query_embeddings(query_sha256)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_steps_run ON run_steps(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_steps_tool ON run_steps(tool_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_run_steps_status ON run_steps(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_bundles_run ON evidence_bundles(run_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_proposed_structures_proposal_id ON proposed_structures(proposal_id)")
    conn.commit()


def _get_columns(conn: sqlite3.Connection, table: str) -> set:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def _ensure_table_columns(conn: sqlite3.Connection, table: str, required: dict) -> None:
    existing = _get_columns(conn, table)
    if not existing:
        return
    for name, col_type in required.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def ensure_schema(db_path: Optional[str] = None) -> None:
    conn = connect(db_path)
    init_db(conn)
    conn.close()
