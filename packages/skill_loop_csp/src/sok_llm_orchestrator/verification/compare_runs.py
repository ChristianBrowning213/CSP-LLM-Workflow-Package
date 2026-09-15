from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_manifest(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))


def _load_objective(run_dir: Path) -> float | None:
    path = run_dir / "artifacts" / "qlip_solve.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    result = payload.get("result", payload).get("result", {})
    summary = result.get("summary", {})
    value = summary.get("objective_value")
    return float(value) if isinstance(value, (float, int)) else None


def compare_runs(left_run_dir: Path, right_run_dir: Path) -> dict[str, Any]:
    left_manifest = _load_manifest(left_run_dir)
    right_manifest = _load_manifest(right_run_dir)
    left_obj = _load_objective(left_run_dir)
    right_obj = _load_objective(right_run_dir)
    improved = None
    if left_obj is not None and right_obj is not None:
        improved = right_obj < left_obj
    return {
        "schema_version": "compare_runs.v1",
        "left_run_id": left_manifest["run_id"],
        "right_run_id": right_manifest["run_id"],
        "left_status": left_manifest["status"],
        "right_status": right_manifest["status"],
        "left_objective": left_obj,
        "right_objective": right_obj,
        "improved": improved,
        "delta_summary": {
            "status_changed": left_manifest["status"] != right_manifest["status"],
            "objective_delta": (right_obj - left_obj) if (left_obj is not None and right_obj is not None) else None,
        },
    }
