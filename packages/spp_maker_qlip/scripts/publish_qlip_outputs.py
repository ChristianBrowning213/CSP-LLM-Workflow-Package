"""Publish artifacts into canonical QLIP_Outputs registry layout."""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running this script without editable install.
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from spp_maker import __version__ as spp_maker_version
from spp_maker.pot_compat import check_pot_root, render_compat_report
from spp_maker.publish import (
    ArtifactKind,
    build_run_id,
    copy_or_symlink_tree,
    deep_merge,
    ensure_qlip_outputs_layout,
    get_git_sha,
    kind_latest_file,
    kind_root_dirname,
    kind_runs_root,
    kind_to_bucket,
    load_json,
    python_version_short,
    to_posix_relative,
    write_json,
)
from spp_maker.qlip_outputs_index import load_index, write_index


class UsageError(Exception):
    """Raised for usage/validation errors."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish SPP/guidance/constraint artifacts to QLIP_Outputs."
    )
    parser.add_argument(
        "--kind",
        choices=("spp", "guidance", "constraint", "package"),
        default="spp",
    )
    parser.add_argument("--artifact_root", type=Path, default=None)
    parser.add_argument("--spp_root", type=Path, default=None, help="Backward-compatible alias.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--qlip_outputs", type=Path, default=Path("QLIP_Outputs"))
    parser.add_argument("--copy_mode", choices=("copy", "symlink"), default="copy")
    parser.add_argument(
        "--strict_compat",
        dest="strict_compat",
        action="store_true",
        help="Run strict POT compatibility checks for SPP artifacts (default).",
    )
    parser.add_argument(
        "--no_strict_compat",
        dest="strict_compat",
        action="store_false",
        help="Disable strict POT checks for SPP artifacts.",
    )
    parser.set_defaults(strict_compat=True)
    parser.add_argument(
        "--set_latest",
        dest="set_latest",
        action="store_true",
        help="Update per-kind latest.txt pointer (default).",
    )
    parser.add_argument(
        "--no_set_latest",
        dest="set_latest",
        action="store_false",
        help="Do not update latest.txt pointer.",
    )
    parser.set_defaults(set_latest=True)
    parser.add_argument("--extra_json", type=Path, default=None)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def _resolve_artifact_root(args: argparse.Namespace) -> Path:
    if args.artifact_root is None and args.spp_root is None:
        raise UsageError("One of --artifact_root or --spp_root is required.")
    if args.artifact_root is not None and args.spp_root is not None:
        a = args.artifact_root.resolve()
        b = args.spp_root.resolve()
        if a != b:
            raise UsageError("--artifact_root and --spp_root point to different paths.")
        return a
    assert args.artifact_root is not None or args.spp_root is not None
    return (args.artifact_root or args.spp_root).resolve()


def _validate_args(args: argparse.Namespace, artifact_root: Path) -> None:
    if not artifact_root.is_dir():
        raise UsageError(f"artifact root is not a directory: {artifact_root}")
    if args.kind == "spp":
        manifest_path = artifact_root / "manifest.json"
        if not manifest_path.is_file():
            raise UsageError(f"SPP artifact root must contain manifest.json: {artifact_root}")
    if args.kind == "package":
        package_path = artifact_root / "package.json"
        if not package_path.is_file():
            raise UsageError(f"Package artifact root must contain package.json: {artifact_root}")
    if args.extra_json is not None and not args.extra_json.is_file():
        raise UsageError(f"--extra_json is not a file: {args.extra_json}")


def _compat_for_kind(
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
            "checked": report.checked,
            "passed": report.passed,
            "failed": report.failed,
        }
    }
    ok = report.ok if strict_compat else True
    return checks, text, ok


def main() -> int:
    args = _parse_args()
    kind: ArtifactKind = args.kind

    try:
        artifact_root = _resolve_artifact_root(args)
        _validate_args(args, artifact_root)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        checks, compat_text, compat_ok = _compat_for_kind(
            kind=kind,
            artifact_root=artifact_root,
            strict_compat=bool(args.strict_compat),
        )
        if not compat_ok:
            print("Compatibility check failed. Publish aborted.", file=sys.stderr)
            print(compat_text, file=sys.stderr)
            return 1

        qlip_outputs = args.qlip_outputs.resolve()
        ensure_qlip_outputs_layout(qlip_outputs)

        now_utc = datetime.now(timezone.utc)
        if kind == "spp":
            hash_bytes = (artifact_root / "manifest.json").read_bytes()
        elif kind == "package":
            hash_bytes = (artifact_root / "package.json").read_bytes()
        else:
            hash_bytes = str(artifact_root).encode("utf-8")
        run_id = build_run_id(name=args.name, manifest_bytes=hash_bytes, now_utc=now_utc)

        runs_root = kind_runs_root(qlip_outputs, kind)
        run_dir = runs_root / run_id
        if run_dir.exists():
            if not args.overwrite:
                raise UsageError(
                    f"Run folder already exists: {run_dir}. Use --overwrite to replace it."
                )
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=False)

        root_dirname = kind_root_dirname(kind)
        published_root = run_dir / root_dirname
        copy_or_symlink_tree(artifact_root, published_root, mode=args.copy_mode)

        if kind == "spp":
            shutil.copy2(artifact_root / "manifest.json", run_dir / "manifest.json")
        elif kind == "package":
            shutil.copy2(artifact_root / "package.json", run_dir / "package.json")
        (run_dir / "compat_report.txt").write_text(compat_text, encoding="utf-8")

        extra_payload: dict[str, Any] = {}
        if args.extra_json is not None:
            extra_payload = load_json(args.extra_json.resolve())

        script_repo_root = Path(__file__).resolve().parents[1]
        publish_meta: dict[str, Any] = {
            "run_id": run_id,
            "kind": kind,
            "name": args.name,
            "timestamp_utc": now_utc.isoformat(),
            "source_artifact_root": str(artifact_root),
            "git_sha": get_git_sha(script_repo_root),
            "tool": "SPP_Maker",
            "tool_version": spp_maker_version,
            "python_version": python_version_short(),
            "copy_mode": args.copy_mode,
            "checks": checks,
            "set_latest": bool(args.set_latest),
        }
        publish_meta = deep_merge(publish_meta, extra_payload)
        write_json(run_dir / "publish_meta.json", publish_meta)

        run_rel = to_posix_relative(run_dir, qlip_outputs)
        run_record: dict[str, Any] = {
            "run_id": run_id,
            "kind": kind,
            "name": args.name,
            "timestamp_utc": now_utc.isoformat(),
            "path": run_rel,
            "source": {
                "source_path": str(artifact_root),
                "git_sha": get_git_sha(script_repo_root),
                "tool": "SPP_Maker",
                "tool_version": spp_maker_version,
            },
            "params": {
                "copy_mode": args.copy_mode,
                "strict_compat": bool(args.strict_compat),
                "root_dirname": root_dirname,
            },
            "checks": checks,
        }
        if kind == "spp":
            run_record["manifest_path"] = f"{run_rel}/manifest.json"
            run_record["compat_report_path"] = f"{run_rel}/compat_report.txt"
        elif kind == "package":
            run_record["package_path"] = f"{run_rel}/package.json"

        index_path = qlip_outputs / "index.json"
        index_obj = load_index(index_path)
        bucket = kind_to_bucket(kind)
        bucket_obj = dict(index_obj["artifacts"][bucket])
        runs = [
            r
            for r in bucket_obj.get("runs", [])
            if not (isinstance(r, dict) and r.get("run_id") == run_id)
        ]
        runs.append(run_record)
        bucket_obj["runs"] = runs
        if args.set_latest:
            bucket_obj["latest"] = run_rel
        index_obj["artifacts"][bucket] = bucket_obj
        write_index(index_path, index_obj)

        if args.set_latest:
            latest_path = kind_latest_file(qlip_outputs, kind)
            latest_path.write_text(run_rel + "\n", encoding="utf-8")

        print(f"Published run_id: {run_id}")
        print(f"Kind: {kind}")
        print(f"Run folder: {run_dir}")
        print(f"Index: {index_path}")
        if args.set_latest:
            print(f"Latest pointer: {kind_latest_file(qlip_outputs, kind)}")
        return 0
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
