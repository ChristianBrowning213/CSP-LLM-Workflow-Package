"""QLIP packaging parity: run the full `run` pipeline with --publish_to on
both source and archive against identical fixture CIFs, and compare the
produced directory structure, filenames, and POT hashes (Ticket 26 Part 41).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ARCHIVE_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(r"C:\Users\brown\.spp-source-frozen-3a2d557")


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


def _run_pipeline(root: Path, out_dir: Path, qlip_outputs: Path) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        root, "run",
        "--name", "parity_pkg_test",
        "--cif_dir", "tests/fixtures/cifs",
        "--out_dir", str(out_dir),
        "--fit_method", "neighbors",
        "--calib_score_method", "neighbors",
        "--target", "5.0",
        "--max_calib", "2",
        "--no_bandpass",
        "--publish_to", str(qlip_outputs),
    )


def _tree_hashes(root: Path) -> dict:
    """Relative-path -> sha256 for every file under root (excluding this
    run's own timestamped/run-id directory NAME, which legitimately
    differs between the two invocations — compared as sorted structure
    instead, see caller)."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def run() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_out, source_qlip = tmp_path / "source_out", tmp_path / "source_qlip"
        archive_out, archive_qlip = tmp_path / "archive_out", tmp_path / "archive_qlip"

        source_result = _run_pipeline(SOURCE_ROOT, source_out, source_qlip)
        archive_result = _run_pipeline(ARCHIVE_ROOT, archive_out, archive_qlip)

        report: dict = {
            "source_returncode": source_result.returncode,
            "archive_returncode": archive_result.returncode,
        }
        if source_result.returncode != 0 or archive_result.returncode != 0:
            report["status"] = "RUN_FAILED"
            report["source_stderr"] = source_result.stderr[-2000:]
            report["archive_stderr"] = archive_result.stderr[-2000:]
            return report

        source_final = source_out / "Final_QLIP_output"
        archive_final = archive_out / "Final_QLIP_output"
        source_files = sorted(p.name for p in source_final.rglob("*") if p.is_file())
        archive_files = sorted(p.name for p in archive_final.rglob("*") if p.is_file())

        source_pot_hashes = sorted(
            hashlib.sha256(p.read_bytes()).hexdigest() for p in source_final.rglob("*.POT")
        )
        archive_pot_hashes = sorted(
            hashlib.sha256(p.read_bytes()).hexdigest() for p in archive_final.rglob("*.POT")
        )

        report["final_output_filenames_match"] = source_files == archive_files
        report["source_final_filenames"] = source_files
        report["archive_final_filenames"] = archive_files
        report["pot_hashes_match"] = source_pot_hashes == archive_pot_hashes
        report["source_pot_hashes"] = source_pot_hashes
        report["archive_pot_hashes"] = archive_pot_hashes

        # QLIP_Outputs registry: compare category subdirectory names (SPP,
        # GUIDANCES, PACKAGES) — not the timestamped run-id names, which
        # legitimately differ between the two independent invocations.
        source_categories = sorted(p.name for p in source_qlip.iterdir() if p.is_dir())
        archive_categories = sorted(p.name for p in archive_qlip.iterdir() if p.is_dir())
        report["qlip_outputs_categories_match"] = source_categories == archive_categories
        report["source_qlip_categories"] = source_categories
        report["archive_qlip_categories"] = archive_categories

        report["status"] = "COMPARED"
        return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
