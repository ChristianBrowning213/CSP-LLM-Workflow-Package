"""Publishing helpers for QLIP_Outputs package and registry artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spp_maker import __version__ as spp_maker_version
from spp_maker.pot_compat import check_pot_root, render_compat_report
from spp_maker.publish import (
    ArtifactKind,
    build_run_id,
    copy_or_symlink_tree,
    ensure_qlip_outputs_layout,
    get_git_sha,
    kind_latest_file,
    kind_root_dirname,
    kind_runs_root,
    kind_to_bucket,
    python_version_short,
    to_posix_relative,
    write_json,
)
from spp_maker.qlip_outputs_index import load_index, write_index


@dataclass(frozen=True)
class PublishedArtifact:
    """Published registry run metadata."""

    kind: ArtifactKind
    run_id: str
    run_dir: Path
    run_rel: str
    checks: dict[str, Any]
    compat_text: str


def _default_hash_bytes(kind: ArtifactKind, artifact_root: Path) -> bytes:
    if kind == "spp" and (artifact_root / "manifest.json").is_file():
        return (artifact_root / "manifest.json").read_bytes()
    if kind == "package" and (artifact_root / "package.json").is_file():
        return (artifact_root / "package.json").read_bytes()
    if kind == "guidance" and (artifact_root / "guidance.json").is_file():
        return (artifact_root / "guidance.json").read_bytes()
    return str(artifact_root.resolve()).encode("utf-8")


def _compat_for_publish(
    *,
    kind: ArtifactKind,
    artifact_root: Path,
    strict_compat: bool,
) -> tuple[dict[str, Any], str, bool]:
    if kind != "spp":
        checks = {
            "compat": {
                "strict": bool(strict_compat),
                "skipped": True,
                "checked": 0,
                "passed": 0,
                "failed": 0,
            }
        }
        return checks, "Compatibility check skipped for non-SPP artifact kind.\n", True

    report = check_pot_root(artifact_root, strict=bool(strict_compat))
    text = render_compat_report(report) + "\n"
    checks = {
        "compat": {
            "strict": bool(strict_compat),
            "skipped": False,
            "checked": int(report.checked),
            "passed": int(report.passed),
            "failed": int(report.failed),
        }
    }
    return checks, text, bool(report.ok if strict_compat else True)


def publish_registry_artifact(
    *,
    kind: ArtifactKind,
    artifact_root: Path,
    qlip_outputs: Path,
    name: str,
    params: dict[str, Any],
    checks: dict[str, Any] | None = None,
    strict_compat: bool = True,
    copy_mode: str = "copy",
    set_latest: bool = True,
    overwrite: bool = False,
    hash_bytes: bytes | None = None,
    repo_root: Path | None = None,
) -> PublishedArtifact:
    """Publish one artifact run to QLIP_Outputs and update index/latest pointers."""
    artifact_root = artifact_root.resolve()
    if not artifact_root.is_dir():
        raise ValueError(f"artifact_root is not a directory: {artifact_root}")

    qlip_outputs = qlip_outputs.resolve()
    ensure_qlip_outputs_layout(qlip_outputs)
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()

    resolved_checks, compat_text, compat_ok = _compat_for_publish(
        kind=kind,
        artifact_root=artifact_root,
        strict_compat=bool(strict_compat),
    )
    if checks is not None:
        resolved_checks = checks
    if not compat_ok:
        raise RuntimeError(f"{kind} compatibility check failed.")

    now_utc = datetime.now(timezone.utc)
    run_id = build_run_id(
        name=name,
        manifest_bytes=(hash_bytes if hash_bytes is not None else _default_hash_bytes(kind, artifact_root)),
        now_utc=now_utc,
    )
    run_dir = kind_runs_root(qlip_outputs, kind) / run_id
    if run_dir.exists():
        if not overwrite:
            raise RuntimeError(f"Run folder already exists: {run_dir}")
        for child in sorted(run_dir.iterdir(), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            else:
                # Fallback: existing helpers default to copy mode, so this should be uncommon.
                import shutil  # local import to keep module load lightweight

                shutil.rmtree(child)
    run_dir.mkdir(parents=True, exist_ok=True)

    root_dirname = kind_root_dirname(kind)
    published_root = run_dir / root_dirname
    copy_or_symlink_tree(artifact_root, published_root, mode=copy_mode)

    if kind == "spp" and (artifact_root / "manifest.json").is_file():
        import shutil  # local import to keep module load lightweight

        shutil.copy2(artifact_root / "manifest.json", run_dir / "manifest.json")
    if kind == "package" and (artifact_root / "package.json").is_file():
        import shutil  # local import to keep module load lightweight

        shutil.copy2(artifact_root / "package.json", run_dir / "package.json")

    (run_dir / "compat_report.txt").write_text(compat_text, encoding="utf-8")
    git_sha = get_git_sha(repo_root)
    publish_meta = {
        "run_id": run_id,
        "kind": kind,
        "name": name,
        "timestamp_utc": now_utc.isoformat(),
        "source_artifact_root": str(artifact_root),
        "git_sha": git_sha,
        "tool": "SPP_Maker",
        "tool_version": spp_maker_version,
        "python_version": python_version_short(),
        "copy_mode": copy_mode,
        "checks": resolved_checks,
        "set_latest": bool(set_latest),
    }
    write_json(run_dir / "publish_meta.json", publish_meta)

    run_rel = to_posix_relative(run_dir, qlip_outputs)
    run_record: dict[str, Any] = {
        "run_id": run_id,
        "kind": kind,
        "name": name,
        "timestamp_utc": now_utc.isoformat(),
        "path": run_rel,
        "source": {
            "source_path": str(artifact_root),
            "git_sha": git_sha,
            "tool": "SPP_Maker",
            "tool_version": spp_maker_version,
        },
        "params": params,
        "checks": resolved_checks,
    }
    if kind == "spp":
        run_record["manifest_path"] = f"{run_rel}/manifest.json"
        run_record["compat_report_path"] = f"{run_rel}/compat_report.txt"
    if kind == "package":
        run_record["package_path"] = f"{run_rel}/package.json"

    index_path = qlip_outputs / "index.json"
    index_obj = load_index(index_path)
    bucket = kind_to_bucket(kind)
    bucket_obj = dict(index_obj["artifacts"][bucket])
    runs = [
        existing
        for existing in bucket_obj.get("runs", [])
        if not (isinstance(existing, dict) and existing.get("run_id") == run_id)
    ]
    runs.append(run_record)
    bucket_obj["runs"] = runs
    if set_latest:
        bucket_obj["latest"] = run_rel
    index_obj["artifacts"][bucket] = bucket_obj
    write_index(index_path, index_obj)

    if set_latest:
        kind_latest_file(qlip_outputs, kind).write_text(run_rel + "\n", encoding="utf-8")

    return PublishedArtifact(
        kind=kind,
        run_id=run_id,
        run_dir=run_dir,
        run_rel=run_rel,
        checks=resolved_checks,
        compat_text=compat_text,
    )
