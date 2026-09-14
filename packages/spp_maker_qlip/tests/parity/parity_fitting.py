"""Direct fitting parity: run `spp-maker fit` on source and archive against
identical safe fixture CIFs, and compare required pairs, POT bytes, and
manifest content (Ticket 26 Part 39).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ARCHIVE_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(r"C:\Users\brown\.spp-source-frozen-3a2d557")

# Fields whose values are inherently environment-specific and must be
# excluded from equality comparison (Claude-specified exclusion list).
EXCLUDED_MANIFEST_FIELDS = {"source_cif_files", "git_sha", "cif_dir"}


def _run_cli(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")
    return subprocess.run(
        [sys.executable, "-m", "spp_maker.cli", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=root,
    )


def _fit(root: Path, out_root: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        root,
        "fit",
        "--cif_dir", "tests/fixtures/cifs",
        "--out_root", str(out_root),
        "--fit_method", "neighbors",
        "--r_cut", "4.0",
    )


def _strip_excluded(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in EXCLUDED_MANIFEST_FIELDS}


def _compare_pot_files(source_root: Path, archive_root: Path) -> dict:
    source_pots = sorted(source_root.rglob("*.POT"))
    archive_pots = sorted(archive_root.rglob("*.POT"))
    source_rel = {p.relative_to(source_root).as_posix() for p in source_pots}
    archive_rel = {p.relative_to(archive_root).as_posix() for p in archive_pots}

    result = {
        "source_pot_count": len(source_pots),
        "archive_pot_count": len(archive_pots),
        "relative_paths_match": source_rel == archive_rel,
        "missing_from_archive": sorted(source_rel - archive_rel),
        "extra_in_archive": sorted(archive_rel - source_rel),
        "byte_exact": {},
        "mismatches": [],
    }
    for rel in sorted(source_rel & archive_rel):
        a = (source_root / rel).read_bytes()
        b = (archive_root / rel).read_bytes()
        if a == b:
            result["byte_exact"][rel] = True
        else:
            result["byte_exact"][rel] = False
            result["mismatches"].append(rel)
    return result


def run() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_out = tmp_path / "source_out"
        archive_out = tmp_path / "archive_out"

        source_result = _fit(SOURCE_ROOT, source_out)
        archive_result = _fit(ARCHIVE_ROOT, archive_out)

        report: dict = {
            "source_returncode": source_result.returncode,
            "archive_returncode": archive_result.returncode,
            "source_stderr": source_result.stderr[-2000:] if source_result.returncode != 0 else "",
            "archive_stderr": archive_result.stderr[-2000:] if archive_result.returncode != 0 else "",
        }

        if source_result.returncode != 0 or archive_result.returncode != 0:
            report["status"] = "FIT_FAILED"
            return report

        source_manifest = json.loads((source_out / "manifest.json").read_text(encoding="utf-8"))
        archive_manifest = json.loads((archive_out / "manifest.json").read_text(encoding="utf-8"))

        report["required_pairs_match"] = sorted(source_manifest.get("pairs", [])) == sorted(
            archive_manifest.get("pairs", [])
        )
        report["manifest_match_excluding_env_fields"] = _strip_excluded(source_manifest) == _strip_excluded(
            archive_manifest
        )
        report["pot_comparison"] = _compare_pot_files(source_out, archive_out)
        report["status"] = "COMPARED"
        return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
