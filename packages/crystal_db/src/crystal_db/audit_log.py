import json
import uuid
from typing import Any, Dict, Optional, Tuple

from .db import connect, init_db
from .utils import now_iso_utc, stable_hash


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return stable_hash({"payload": payload})


def _redact_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        redacted = {}
        for key, value in payload.items():
            if key == "cif_text":
                redacted["cif_text"] = None
                redacted["cif_text_hash"] = _hash_payload(value) if value is not None else None
            elif key in ("vector", "feature_names"):
                redacted[key] = None
                redacted[f"{key}_hash"] = _hash_payload(value) if value is not None else None
                if isinstance(value, list):
                    redacted[f"{key}_len"] = len(value)
            elif key == "cif_text_or_path":
                redacted[key] = value
            else:
                redacted[key] = _redact_payload(value)
        return redacted
    if isinstance(payload, list):
        return [_redact_payload(item) for item in payload]
    return payload


class AuditLogger:
    def __init__(
        self,
        db_path: Optional[str],
        run_name: Optional[str],
        config: Dict[str, Any],
        defer_init: bool = False,
        run_id: Optional[str] = None,
        create_run: bool = True,
    ):
        self.db_path = db_path
        self.run_id = run_id or str(uuid.uuid4())
        self.step_id = 0
        self._conn: Optional[Tuple[Any, bool]] = None
        self._create_run = create_run
        self._pending_init = defer_init and create_run
        self._run_name = run_name
        self._config = config
        if not defer_init and create_run:
            self._init_run(run_name, config)
        if run_id is not None and not create_run:
            self._seed_step_id()

    def _seed_step_id(self) -> None:
        conn = connect(self.db_path)
        init_db(conn)
        row = conn.execute(
            "SELECT MAX(step_id) AS max_step FROM tool_calls WHERE run_id = ?",
            (self.run_id,),
        ).fetchone()
        conn.close()
        max_step = row["max_step"] if row is not None else None
        self.step_id = int(max_step) if max_step is not None else 0

    def _init_run(self, run_name: Optional[str], config: Dict[str, Any], conn: Any = None, should_close: bool = True) -> None:
        if not self._create_run:
            return
        owns_conn = False
        if conn is None:
            conn = connect(self.db_path)
            init_db(conn)
            owns_conn = True
        conn.execute(
            "INSERT INTO runs (run_id, created_at, run_name, config_json) VALUES (?, ?, ?, ?)",
            (self.run_id, now_iso_utc(), run_name, _json_dumps(config)),
        )
        if owns_conn and should_close:
            conn.commit()
            conn.close()

    def begin_batch(self) -> None:
        if self._conn is None:
            conn = connect(self.db_path)
            init_db(conn)
            conn.execute("PRAGMA synchronous = OFF;")
            self._conn = (conn, True)
        if self._pending_init:
            self._init_run(self._run_name, self._config, conn=self._conn[0], should_close=False)
            self._pending_init = False

    def end_batch(self) -> None:
        if self._conn is None:
            return
        conn, should_close = self._conn
        if should_close:
            conn.commit()
            conn.close()
        self._conn = None

    def _get_conn(self):
        if self._conn is not None:
            if self._pending_init:
                self._init_run(self._run_name, self._config, conn=self._conn[0], should_close=False)
                self._pending_init = False
            return self._conn[0], False
        conn = connect(self.db_path)
        init_db(conn)
        if self._pending_init:
            self._init_run(self._run_name, self._config, conn=conn, should_close=False)
            self._pending_init = False
            conn.commit()
        return conn, True

    def log_tool_call(
        self,
        tool_name: str,
        input_payload: Any,
        output_payload: Any,
        started_at: str,
        ended_at: str,
        status: str,
        error_text: Optional[str] = None,
    ) -> None:
        redacted_input = _redact_payload(input_payload)
        redacted_output = _redact_payload(output_payload)

        input_json = _json_dumps(redacted_input)
        output_json = _json_dumps(redacted_output)
        conn, should_close = self._get_conn()
        if not self._create_run:
            row = conn.execute(
                "SELECT MAX(step_id) AS max_step FROM tool_calls WHERE run_id = ?",
                (self.run_id,),
            ).fetchone()
            max_step = row["max_step"] if row is not None else None
            self.step_id = int(max_step) if max_step is not None else 0
        self.step_id += 1
        conn.execute(
            "INSERT INTO tool_calls "
            "(run_id, step_id, tool_name, input_json, input_hash, output_json, output_hash, "
            "started_at, ended_at, status, error_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                self.step_id,
                tool_name,
                input_json,
                _hash_payload(redacted_input),
                output_json,
                _hash_payload(redacted_output),
                started_at,
                ended_at,
                status,
                error_text,
            ),
        )
        if should_close:
            conn.commit()
            conn.close()

    def save_evidence(self, evidence: Dict[str, Any]) -> None:
        conn, should_close = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO answer_evidence (run_id, evidence_json, created_at) VALUES (?, ?, ?)",
            (self.run_id, _json_dumps(_redact_payload(evidence)), now_iso_utc()),
        )
        if should_close:
            conn.commit()
            conn.close()

    def add_explored(self, structure_id: str, role: str) -> None:
        conn, should_close = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO explored_structures (run_id, structure_id, role, created_at) VALUES (?, ?, ?, ?)",
            (self.run_id, structure_id, role, now_iso_utc()),
        )
        if should_close:
            conn.commit()
            conn.close()

    def add_explored_many(self, structure_ids, role: str) -> None:
        if not structure_ids:
            return
        conn, should_close = self._get_conn()
        conn.executemany(
            "INSERT OR REPLACE INTO explored_structures (run_id, structure_id, role, created_at) VALUES (?, ?, ?, ?)",
            [(self.run_id, structure_id, role, now_iso_utc()) for structure_id in structure_ids],
        )
        if should_close:
            conn.commit()
            conn.close()

    def add_proposed(self, proposed_id: str, cif_text_or_path: str, input_hash: str) -> None:
        conn, should_close = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO proposed_structures (run_id, proposed_id, cif_text_or_path, input_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.run_id, proposed_id, cif_text_or_path, input_hash, now_iso_utc()),
        )
        if should_close:
            conn.commit()
            conn.close()

    def add_novelty_result(
        self,
        proposed_id: str,
        is_novel: bool,
        best_match_structure_id: Optional[str],
        best_distance: Optional[float],
        threshold: float,
        neighbors: Any,
        timings: Optional[Dict[str, Any]] = None,
    ) -> None:
        conn, should_close = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO novelty_results "
            "(run_id, proposed_id, is_novel, best_match_structure_id, best_distance, threshold, neighbors_json, timings_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                self.run_id,
                proposed_id,
                1 if is_novel else 0,
                best_match_structure_id,
                best_distance,
                threshold,
                _json_dumps(_redact_payload(neighbors)),
                _json_dumps(timings) if timings is not None else None,
                now_iso_utc(),
            ),
        )
        if should_close:
            conn.commit()
            conn.close()

    def update_novelty_timings(self, proposed_id: str, timings: Dict[str, Any]) -> None:
        conn, should_close = self._get_conn()
        conn.execute(
            "UPDATE novelty_results SET timings_json = ? WHERE run_id = ? AND proposed_id = ?",
            (_json_dumps(timings), self.run_id, proposed_id),
        )
        if should_close:
            conn.commit()
            conn.close()


def fetch_audit_bundle(run_id: str, db_path: Optional[str]) -> Dict[str, Any]:
    conn = connect(db_path)
    init_db(conn)

    run = conn.execute(
        "SELECT run_id, created_at, run_name, config_json FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        conn.close()
        return {"error": "run_not_found", "run_id": run_id}

    tool_calls = conn.execute(
        "SELECT step_id, tool_name, input_json, input_hash, output_json, output_hash, started_at, ended_at, status, error_text "
        "FROM tool_calls WHERE run_id = ? ORDER BY step_id",
        (run_id,),
    ).fetchall()

    evidence = conn.execute(
        "SELECT evidence_json, created_at FROM answer_evidence WHERE run_id = ?",
        (run_id,),
    ).fetchone()

    explored = conn.execute(
        "SELECT structure_id, role, created_at FROM explored_structures WHERE run_id = ? ORDER BY structure_id",
        (run_id,),
    ).fetchall()

    proposed = conn.execute(
        "SELECT proposed_id, cif_text_or_path, input_hash, created_at FROM proposed_structures WHERE run_id = ?",
        (run_id,),
    ).fetchall()

    novelty = conn.execute(
        "SELECT proposed_id, is_novel, best_match_structure_id, best_distance, threshold, neighbors_json, timings_json, created_at "
        "FROM novelty_results WHERE run_id = ?",
        (run_id,),
    ).fetchall()

    conn.close()

    return {
        "run": {
            "run_id": run["run_id"],
            "created_at": run["created_at"],
            "run_name": run["run_name"],
            "config": json.loads(run["config_json"]),
        },
        "tool_calls": [
            {
                "step_id": row["step_id"],
                "tool_name": row["tool_name"],
                "input_json": json.loads(row["input_json"]),
                "input_hash": row["input_hash"],
                "output_json": json.loads(row["output_json"]),
                "output_hash": row["output_hash"],
                "started_at": row["started_at"],
                "ended_at": row["ended_at"],
                "status": row["status"],
                "error_text": row["error_text"],
            }
            for row in tool_calls
        ],
        "evidence": None
        if evidence is None
        else {"evidence": json.loads(evidence["evidence_json"]), "created_at": evidence["created_at"]},
        "explored_structures": [
            {"structure_id": row["structure_id"], "role": row["role"], "created_at": row["created_at"]}
            for row in explored
        ],
        "proposed_structures": [
            {
                "proposed_id": row["proposed_id"],
                "cif_text_or_path": row["cif_text_or_path"],
                "input_hash": row["input_hash"],
                "created_at": row["created_at"],
            }
            for row in proposed
        ],
        "novelty_results": [
            {
                "proposed_id": row["proposed_id"],
                "is_novel": bool(row["is_novel"]),
                "best_match_structure_id": row["best_match_structure_id"],
                "best_distance": row["best_distance"],
                "threshold": row["threshold"],
                "neighbors": json.loads(row["neighbors_json"]),
                "timings_ms": json.loads(row["timings_json"]) if row["timings_json"] else None,
                "created_at": row["created_at"],
            }
            for row in novelty
        ],
    }
