import hashlib
import json
import uuid
from typing import Any, Dict, Optional

from .db import connect, init_db
from .utils import now_iso_utc


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _json_sha256(payload: Any) -> str:
    data = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class RunLogger:
    def __init__(self, db_path: Optional[str]):
        self.db_path = db_path
        self.run_id: Optional[str] = None

    def start_run(self, command: str, args: Dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        ts = now_iso_utc()
        conn = connect(self.db_path)
        init_db(conn)
        conn.execute(
            "INSERT INTO runs (run_id, created_at, command, args_json, status, error_text, run_name, config_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                ts,
                command,
                _canonical_json(args),
                "ok",
                None,
                args.get("run_name"),
                _canonical_json(args),
            ),
        )
        conn.commit()
        conn.close()
        self.run_id = run_id
        return run_id

    def finalize_run(self, *, status: str, error_text: Optional[str] = None) -> None:
        if not self.run_id:
            return
        conn = connect(self.db_path)
        init_db(conn)
        conn.execute(
            "UPDATE runs SET status = ?, error_text = ? WHERE run_id = ?",
            (status, error_text, self.run_id),
        )
        conn.commit()
        conn.close()

    def log_step(
        self,
        tool_name: str,
        input_dict: Dict[str, Any],
        output_dict: Any,
        status: str,
        error_text: Optional[str] = None,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
    ) -> None:
        if not self.run_id:
            raise RuntimeError("run_not_started")
        started = started_at or now_iso_utc()
        ended = ended_at or now_iso_utc()
        conn = connect(self.db_path)
        init_db(conn)
        conn.execute(
            "INSERT INTO run_steps "
            "(run_id, tool_name, input_json, input_hash, output_json, output_hash, started_at, ended_at, status, error_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                tool_name,
                _canonical_json(input_dict),
                _json_sha256(input_dict),
                _canonical_json(output_dict),
                _json_sha256(output_dict),
                started,
                ended,
                status,
                error_text,
            ),
        )
        conn.commit()
        conn.close()

    def add_evidence(self, kind: str, payload_dict: Dict[str, Any]) -> None:
        if not self.run_id:
            raise RuntimeError("run_not_started")
        conn = connect(self.db_path)
        init_db(conn)
        conn.execute(
            "INSERT INTO evidence_bundles (run_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (self.run_id, kind, _canonical_json(payload_dict), now_iso_utc()),
        )
        conn.commit()
        conn.close()

    def add_explored(self, structure_id: str, reason: str) -> None:
        if not self.run_id:
            raise RuntimeError("run_not_started")
        ts = now_iso_utc()
        conn = connect(self.db_path)
        init_db(conn)
        conn.execute(
            "INSERT OR REPLACE INTO explored_structures (run_id, structure_id, reason, role, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.run_id, structure_id, reason, reason, ts),
        )
        conn.commit()
        conn.close()

    def add_proposal(
        self,
        *,
        source: str,
        cif_path: Optional[str] = None,
        structure_id: Optional[str] = None,
        status: str = "draft",
        notes: Optional[str] = None,
        proposal_id: Optional[str] = None,
    ) -> str:
        if not self.run_id:
            raise RuntimeError("run_not_started")
        proposal = proposal_id or str(uuid.uuid4())
        ts = now_iso_utc()
        cif_text_or_path = cif_path or ""
        input_hash = _json_sha256({"cif_path": cif_path, "structure_id": structure_id, "source": source})
        conn = connect(self.db_path)
        init_db(conn)
        conn.execute(
            "INSERT OR REPLACE INTO proposed_structures "
            "(run_id, proposed_id, proposal_id, source, cif_path, structure_id, status, notes, "
            "cif_text_or_path, input_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                proposal,
                proposal,
                source,
                cif_path,
                structure_id,
                status,
                notes,
                cif_text_or_path,
                input_hash,
                ts,
            ),
        )
        conn.commit()
        conn.close()
        return proposal


def fetch_run_report(run_id: str, db_path: Optional[str]) -> Dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)
    run = conn.execute(
        "SELECT run_id, created_at, command, args_json, status, error_text FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        conn.close()
        return {"error": "run_not_found", "run_id": run_id}

    steps = conn.execute(
        "SELECT step_id, tool_name, input_json, input_hash, output_json, output_hash, started_at, ended_at, status, error_text "
        "FROM run_steps WHERE run_id = ? ORDER BY step_id",
        (run_id,),
    ).fetchall()
    evidence = conn.execute(
        "SELECT bundle_id, kind, payload_json, created_at FROM evidence_bundles WHERE run_id = ? ORDER BY bundle_id",
        (run_id,),
    ).fetchall()
    explored = conn.execute(
        "SELECT structure_id, reason, role, created_at FROM explored_structures WHERE run_id = ? ORDER BY structure_id",
        (run_id,),
    ).fetchall()
    proposed = conn.execute(
        "SELECT proposal_id, source, cif_path, structure_id, status, notes, created_at "
        "FROM proposed_structures WHERE run_id = ? ORDER BY created_at, proposal_id",
        (run_id,),
    ).fetchall()
    conn.close()

    return {
        "run": {
            "run_id": run["run_id"],
            "created_at": run["created_at"],
            "command": run["command"],
            "args": json.loads(run["args_json"]) if run["args_json"] else {},
            "status": run["status"],
            "error_text": run["error_text"],
        },
        "run_steps": [
            {
                "step_id": row["step_id"],
                "tool_name": row["tool_name"],
                "input_json": json.loads(row["input_json"]) if row["input_json"] else {},
                "input_hash": row["input_hash"],
                "output_json": json.loads(row["output_json"]) if row["output_json"] else {},
                "output_hash": row["output_hash"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "status": row["status"],
                "error_text": row["error_text"],
            }
            for row in steps
        ],
        "evidence_bundles": [
            {
                "bundle_id": row["bundle_id"],
                "kind": row["kind"],
                "payload": json.loads(row["payload_json"]) if row["payload_json"] else {},
                "created_at": row["created_at"],
            }
            for row in evidence
        ],
        "explored_structures": [
            {
                "structure_id": row["structure_id"],
                "reason": row["reason"] or row["role"],
                "created_at": row["created_at"],
            }
            for row in explored
        ],
        "proposed_structures": [
            {
                "proposal_id": row["proposal_id"],
                "source": row["source"],
                "cif_path": row["cif_path"],
                "structure_id": row["structure_id"],
                "status": row["status"],
                "notes": row["notes"],
                "created_at": row["created_at"],
            }
            for row in proposed
        ],
    }
