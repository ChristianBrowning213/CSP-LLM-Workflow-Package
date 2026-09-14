"""Typed helpers for QLIP_Outputs index.json registry."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spp_maker.publish import load_json, write_json

SCHEMA_VERSION = "QLIPOutputsIndex.v1"

_ARTIFACT_BUCKET_TO_KIND = {
    "spp": "spp",
    "guidances": "guidance",
    "constraints": "constraint",
    "packages": "package",
}
_VALID_KINDS = {"spp", "guidance", "constraint", "package"}
_REQUIRED_RUN_FIELDS = {
    "run_id",
    "kind",
    "name",
    "timestamp_utc",
    "path",
    "source",
    "params",
    "checks",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_index() -> dict:
    """Return a new empty v1 index object."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _now_iso(),
        "artifacts": {
            "spp": {"latest": "", "runs": []},
            "guidances": {"latest": "", "runs": []},
            "constraints": {"latest": "", "runs": []},
            "packages": {"latest": "", "runs": []},
        },
    }


def _ensure_required_buckets(index_obj: dict) -> dict:
    out = dict(index_obj)
    artifacts_raw = out.get("artifacts")
    artifacts = dict(artifacts_raw) if isinstance(artifacts_raw, dict) else {}
    for bucket in _ARTIFACT_BUCKET_TO_KIND:
        entry_raw = artifacts.get(bucket)
        entry = dict(entry_raw) if isinstance(entry_raw, dict) else {}
        latest = entry.get("latest")
        runs = entry.get("runs")
        entry["latest"] = latest if isinstance(latest, str) else ""
        entry["runs"] = runs if isinstance(runs, list) else []
        artifacts[bucket] = entry
    out["artifacts"] = artifacts
    return out


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _migrate_legacy_spp_runs(legacy: dict) -> dict:
    runs = legacy.get("spp_runs", [])
    if not isinstance(runs, list):
        raise ValueError("Legacy index format invalid: 'spp_runs' must be a list.")

    migrated = empty_index()
    migrated_runs: list[dict] = []
    for idx, old in enumerate(runs):
        if not isinstance(old, dict):
            continue
        run_id = str(old.get("run_id") or f"legacy_{idx:04d}")
        timestamp = str(old.get("timestamp_utc") or "")
        path = str(old.get("path") or f"SPP/runs/{run_id}")
        source_path = str(old.get("source_spp_root") or old.get("source_path") or "")
        compat_failed = _to_int(old.get("compat_failed"), default=0)
        compat_strict = bool(old.get("compat_strict", False))
        run_record = {
            "run_id": run_id,
            "kind": "spp",
            "name": str(old.get("name") or run_id),
            "timestamp_utc": timestamp,
            "path": path,
            "source": {
                "source_path": source_path,
                "git_sha": old.get("git_sha"),
                "tool": "SPP_Maker",
                "tool_version": str(old.get("spp_maker_version") or "unknown"),
            },
            "params": {"legacy_record": old},
            "checks": {
                "compat": {
                    "strict": compat_strict,
                    "failed": compat_failed,
                }
            },
            "notes": "migrated_from_legacy_index",
            "manifest_path": str(old.get("manifest") or f"{path}/manifest.json"),
            "compat_report_path": str(old.get("compat_report") or f"{path}/compat_report.txt"),
        }
        migrated_runs.append(run_record)

    migrated_runs.sort(key=lambda item: (item.get("timestamp_utc", ""), item.get("run_id", "")))
    migrated["artifacts"]["spp"]["runs"] = migrated_runs
    if migrated_runs:
        migrated["artifacts"]["spp"]["latest"] = str(migrated_runs[-1]["path"])
    return migrated


def migrate_legacy_index(obj: dict) -> dict:
    """Migrate known legacy index shapes to v1."""
    if obj.get("schema_version") == SCHEMA_VERSION:
        return _ensure_required_buckets(obj)
    if "spp_runs" in obj:
        return _migrate_legacy_spp_runs(obj)
    raise ValueError(
        "Unsupported index.json format. Expected v1 schema or legacy 'spp_runs' format."
    )


def validate_index(obj: dict) -> None:
    """Perform lightweight structural validation for index v1."""
    if not isinstance(obj, dict):
        raise ValueError("index object must be a JSON object.")
    if obj.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {SCHEMA_VERSION!r}, got {obj.get('schema_version')!r}."
        )
    if not isinstance(obj.get("generated_at_utc"), str):
        raise ValueError("generated_at_utc must be a string.")

    artifacts = obj.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("artifacts must be an object.")
    for bucket, expected_kind in _ARTIFACT_BUCKET_TO_KIND.items():
        entry = artifacts.get(bucket)
        if not isinstance(entry, dict):
            raise ValueError(f"artifacts.{bucket} must be an object.")
        if not isinstance(entry.get("latest"), str):
            raise ValueError(f"artifacts.{bucket}.latest must be a string.")
        runs = entry.get("runs")
        if not isinstance(runs, list):
            raise ValueError(f"artifacts.{bucket}.runs must be an array.")
        for run in runs:
            if not isinstance(run, dict):
                raise ValueError(f"artifacts.{bucket}.runs items must be objects.")
            missing = _REQUIRED_RUN_FIELDS - set(run)
            if missing:
                raise ValueError(
                    f"Run record in artifacts.{bucket}.runs missing fields: {sorted(missing)}"
                )
            if run.get("kind") not in _VALID_KINDS:
                raise ValueError(f"Invalid run kind: {run.get('kind')!r}")
            if run.get("kind") != expected_kind:
                raise ValueError(
                    f"Run kind mismatch in artifacts.{bucket}: expected {expected_kind!r}, "
                    f"got {run.get('kind')!r}."
                )
            for field in ("run_id", "name", "timestamp_utc", "path"):
                if not isinstance(run.get(field), str):
                    raise ValueError(f"Run field {field} must be a string.")
            if "\\" in str(run.get("path")):
                raise ValueError("Run path must use POSIX separators (no backslashes).")
            source = run.get("source")
            if not isinstance(source, dict):
                raise ValueError("Run source must be an object.")
            for field in ("source_path", "tool", "tool_version"):
                if not isinstance(source.get(field), str):
                    raise ValueError(f"Run source field {field} must be a string.")
            if source.get("git_sha") is not None and not isinstance(source.get("git_sha"), str):
                raise ValueError("Run source.git_sha must be string or null.")
            if not isinstance(run.get("params"), dict):
                raise ValueError("Run params must be an object.")
            if not isinstance(run.get("checks"), dict):
                raise ValueError("Run checks must be an object.")
            if run.get("notes") is not None and not isinstance(run.get("notes"), str):
                raise ValueError("Run notes must be string or null.")


def _sorted_copy(index_obj: dict) -> dict:
    out = dict(index_obj)
    artifacts = dict(out["artifacts"])
    out["artifacts"] = artifacts
    for bucket in _ARTIFACT_BUCKET_TO_KIND:
        entry = dict(artifacts[bucket])
        runs = list(entry.get("runs", []))
        runs.sort(key=lambda item: (item.get("timestamp_utc", ""), item.get("run_id", "")))
        entry["runs"] = runs
        artifacts[bucket] = entry
    return out


def load_index(path: Path) -> dict:
    """Load index.json, with migration for legacy formats."""
    if not path.is_file():
        return empty_index()
    data = load_json(path)
    migrated = migrate_legacy_index(data)
    validate_index(migrated)
    return _sorted_copy(migrated)


def write_index(path: Path, obj: dict) -> None:
    """Validate and write index.json deterministically."""
    out = _sorted_copy(obj)
    out["generated_at_utc"] = _now_iso()
    validate_index(out)
    write_json(path, out)
