"""Scoring parity: fit a root then score the same CIF against it on both
source and archive, comparing scores exactly (Ticket 26 Part 40).
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


def run() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_out = tmp_path / "source_out"
        archive_out = tmp_path / "archive_out"

        fit_source = _run_cli(
            SOURCE_ROOT, "fit", "--cif_dir", "tests/fixtures/cifs",
            "--out_root", str(source_out), "--fit_method", "neighbors", "--r_cut", "4.0",
        )
        fit_archive = _run_cli(
            ARCHIVE_ROOT, "fit", "--cif_dir", "tests/fixtures/cifs",
            "--out_root", str(archive_out), "--fit_method", "neighbors", "--r_cut", "4.0",
        )
        if fit_source.returncode != 0 or fit_archive.returncode != 0:
            return {
                "status": "FIT_FAILED",
                "source_stderr": fit_source.stderr[-2000:],
                "archive_stderr": fit_archive.stderr[-2000:],
            }

        score_source = _run_cli(
            SOURCE_ROOT, "score", "--spp_root", str(source_out),
            "--cif_dir", "tests/fixtures/cifs", "--r_cut", "4.0", "--json",
        )
        score_archive = _run_cli(
            ARCHIVE_ROOT, "score", "--spp_root", str(archive_out),
            "--cif_dir", "tests/fixtures/cifs", "--r_cut", "4.0", "--json",
        )

        report: dict = {
            "source_returncode": score_source.returncode,
            "archive_returncode": score_archive.returncode,
        }
        if score_source.returncode != 0 or score_archive.returncode != 0:
            report["status"] = "SCORE_FAILED"
            report["source_stderr"] = score_source.stderr[-2000:]
            report["archive_stderr"] = score_archive.stderr[-2000:]
            return report

        def _parse_json_lines(stdout: str) -> list[dict]:
            rows = []
            for line in stdout.strip().splitlines():
                line = line.strip()
                if line.startswith("{"):
                    rows.append(json.loads(line))
            return rows

        source_rows = _parse_json_lines(score_source.stdout)
        archive_rows = _parse_json_lines(score_archive.stdout)

        # Per-structure rows have type == "structure" with a "cif" key and a
        # "total" score field (confirmed via direct CLI invocation: real
        # --json output is {"by_pair": ..., "cif": ..., "total": ..., "type":
        # "structure"} per structure, plus one {"type": "aggregate"} summary
        # row — there is no "score" field at all).
        source_scores = {
            row["cif"]: row["total"] for row in source_rows if row.get("type") == "structure"
        }
        archive_scores = {
            row["cif"]: row["total"] for row in archive_rows if row.get("type") == "structure"
        }
        # Normalize the "cif" key (an OS-relative path) to just its basename
        # so source/archive paths compare equal despite differing roots.
        source_scores = {Path(k).name: v for k, v in source_scores.items()}
        archive_scores = {Path(k).name: v for k, v in archive_scores.items()}

        exact_match = source_scores == archive_scores
        report["source_scores"] = source_scores
        report["archive_scores"] = archive_scores
        report["exact_match"] = exact_match
        if not exact_match:
            tolerance_matches = {}
            for key in set(source_scores) & set(archive_scores):
                s, a = source_scores[key], archive_scores[key]
                try:
                    tolerance_matches[key] = abs(s - a) <= 1e-12 + 1e-9 * abs(a)
                except TypeError:
                    tolerance_matches[key] = False
            report["tolerance_matches_rtol_1e-9_atol_1e-12"] = tolerance_matches
        report["status"] = "COMPARED"
        return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
