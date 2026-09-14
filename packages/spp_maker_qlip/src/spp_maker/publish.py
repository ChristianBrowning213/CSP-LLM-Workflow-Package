"""Helpers for publishing QLIP-facing output artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

ArtifactKind = Literal["spp", "guidance", "constraint", "package"]

_KIND_TO_DIR = {
    "spp": "SPP",
    "guidance": "GUIDANCES",
    "constraint": "CONSTRAINTS",
    "package": "PACKAGES",
}
_KIND_TO_BUCKET = {
    "spp": "spp",
    "guidance": "guidances",
    "constraint": "constraints",
    "package": "packages",
}
_KIND_TO_ROOT_DIRNAME = {
    "spp": "spp_root",
    "guidance": "artifact_root",
    "constraint": "artifact_root",
    "package": "artifact_root",
}


def sanitize_run_name(name: str) -> str:
    """Return a filesystem-safe run name token."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    token = token.strip("_")
    return token or "run"


def build_run_id(*, name: str, manifest_bytes: bytes, now_utc: datetime | None = None) -> str:
    """Build run id as `YYYYMMDD_HHMMSS_<name>_<hash8>`."""
    dt = now_utc or datetime.now(timezone.utc)
    ts = dt.strftime("%Y%m%d_%H%M%S")
    safe_name = sanitize_run_name(name)
    suffix = hashlib.sha1(manifest_bytes).hexdigest()[:8]
    return f"{ts}_{safe_name}_{suffix}"


def load_json(path: Path) -> dict:
    """Load JSON object from file."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return data


def write_json(path: Path, payload: dict) -> None:
    """Write deterministic pretty JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def deep_merge(base: dict, extra: dict) -> dict:
    """Deep-merge dictionaries, returning a new object."""
    merged: dict[str, Any] = dict(base)
    for key, value in extra.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def copy_or_symlink_tree(src: Path, dst: Path, *, mode: str) -> None:
    """Copy or symlink a directory tree into destination path."""
    if mode == "copy":
        shutil.copytree(src, dst)
        return
    if mode == "symlink":
        try:
            dst.symlink_to(src, target_is_directory=True)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to create symlink {dst} -> {src}. "
                "Symlink mode may not be supported on this system."
            ) from exc
        return
    raise ValueError(f"Unsupported copy mode: {mode}")


def get_git_sha(repo_root: Path) -> str | None:
    """Best-effort git SHA lookup."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_root,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def ensure_qlip_outputs_layout(qlip_outputs: Path) -> None:
    """Create required QLIP_Outputs folders if missing."""
    (qlip_outputs / "SPP" / "runs").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "SPP" / "latest.txt").touch(exist_ok=True)
    (qlip_outputs / "GUIDANCES").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "GUIDANCES" / "runs").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "GUIDANCES" / "latest.txt").touch(exist_ok=True)
    (qlip_outputs / "CONSTRAINTS").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "CONSTRAINTS" / "runs").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "CONSTRAINTS" / "latest.txt").touch(exist_ok=True)
    (qlip_outputs / "PACKAGES").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "PACKAGES" / "runs").mkdir(parents=True, exist_ok=True)
    (qlip_outputs / "PACKAGES" / "latest.txt").touch(exist_ok=True)
    (qlip_outputs / "schema").mkdir(parents=True, exist_ok=True)


def to_posix_relative(path: Path, base: Path) -> str:
    """Return POSIX-style relative path from base."""
    return path.relative_to(base).as_posix()


def python_version_short() -> str:
    """Return short Python version string."""
    return sys.version.split()[0]


def kind_to_dir(kind: ArtifactKind) -> str:
    """Return top-level directory name for a given artifact kind."""
    try:
        return _KIND_TO_DIR[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown artifact kind: {kind}") from exc


def kind_to_bucket(kind: ArtifactKind) -> str:
    """Return index bucket name for a given artifact kind."""
    try:
        return _KIND_TO_BUCKET[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown artifact kind: {kind}") from exc


def kind_root_dirname(kind: ArtifactKind) -> str:
    """Return run-local artifact root dirname for a given kind."""
    try:
        return _KIND_TO_ROOT_DIRNAME[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown artifact kind: {kind}") from exc


def kind_runs_root(qlip_outputs: Path, kind: ArtifactKind) -> Path:
    """Return runs root folder for a kind."""
    return qlip_outputs / kind_to_dir(kind) / "runs"


def kind_latest_file(qlip_outputs: Path, kind: ArtifactKind) -> Path:
    """Return latest pointer file for a kind."""
    return qlip_outputs / kind_to_dir(kind) / "latest.txt"
