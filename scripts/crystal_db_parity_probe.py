"""Emit a stable synthetic retrieval signature for source/package parity checks."""

import json
import tempfile
from pathlib import Path

from crystal_db.db import connect, init_db
from crystal_db.retrieval import text_search


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "parity.db"
        conn = connect(str(db_path))
        init_db(conn)
        for sid, formula, text, vector, allow_export in [
            ("synthetic-rutile", "TiO2", "rutile oxide", [1.0, 0.0], 1),
            ("synthetic-perovskite", "BaTiO3", "perovskite oxide", [0.0, 1.0], 1),
            ("synthetic-restricted", "XO", "restricted oxide", [0.5, 0.5], 0),
        ]:
            conn.execute(
                "INSERT INTO structures VALUES (?, ?, ?, ?, ?, ?)",
                (sid, f"data_{sid}\n_cell_length_a 4.0\n", formula, 1, 64.0, 0),
            )
            conn.execute(
                "INSERT INTO metadata VALUES (?, ?, ?, ?, ?)",
                (sid, formula, ",O,Ti,", "P1", 1.0),
            )
            conn.execute(
                "INSERT INTO provenance (structure_id, source, source_id, retrieved_at, allow_export) "
                "VALUES (?, ?, ?, ?, ?)",
                (sid, "synthetic-parity", sid, "2026-01-01T00:00:00Z", allow_export),
            )
            doc_id = conn.execute(
                "INSERT INTO text_docs (structure_id, engine, text_view, engine_version, text, text_sha256, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (sid, "caption", "caption", "v1", text, sid, "OK", "2026-01-01", "2026-01-01"),
            ).lastrowid
            conn.execute(
                "INSERT INTO text_embeddings (text_doc_id, embed_engine, model, model_version, dim, vector, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, "hash", "hash-embed", "v1", 2, json.dumps(vector), "OK", "2026-01-01", "2026-01-01"),
            )
        conn.commit()
        conn.close()

        result = text_search(
            query_text="rutile probe", db_path=str(db_path), k=3,
            embed_engine="hash", model_name="hash-embed", model_version="v1",
            text_engine="caption", text_view="caption", query_vector=[1.0, 0.0],
            export_dir=str(Path(temp_dir) / "exports"), export_top=3,
            redacted=True, demo_export=False,
        )
        conn = connect(str(db_path))
        records = [
            dict(row) for row in conn.execute(
                "SELECT m.structure_id, m.formula, p.source, p.source_id, p.allow_export "
                "FROM metadata m JOIN provenance p ON p.structure_id = m.structure_id "
                "ORDER BY m.structure_id"
            ).fetchall()
        ]
        conn.close()
        signature = {
            "status": result["status"],
            "neighbors": [
                {
                    "id": item["structure_id"],
                    "score": round(item["score"], 12),
                    "provenance": item["provenance"],
                    "redacted": item["redacted"],
                    "export": item["cif_export"]["status"],
                }
                for item in result["neighbors"]
            ],
            "records": records,
            "errors": result["errors"],
        }
        print(json.dumps(signature, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
