"""Failure parity: run the same invalid invocations on source and archive
and compare exit code + exception class name (not raw message text, since
messages legitimately embed different absolute paths) (Ticket 26 Part 43).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ARCHIVE_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(r"C:\Users\brown\.spp-source-frozen-3a2d557")

SCENARIOS = {
    "missing_cif_corpus": ["fit", "--cif_dir", "tests/fixtures/does_not_exist", "--out_root", "out_missing"],
    "missing_required_arg": ["fit"],  # --cif_dir/--out_root are required
    "invalid_fit_method": [
        "fit", "--cif_dir", "tests/fixtures/cifs", "--out_root", "out_bad_method",
        "--fit_method", "not_a_real_method",
    ],
    "score_missing_spp_root": ["score", "--cif_dir", "tests/fixtures/cifs"],
    "score_nonexistent_spp_root": [
        "score", "--spp_root", "tests/fixtures/does_not_exist", "--cif_dir", "tests/fixtures/cifs",
    ],
}


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


def _exception_class(stderr: str) -> str | None:
    match = re.search(r"^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):", stderr, re.MULTILINE)
    if match:
        return match.group(1)
    match = re.search(r"argparse\.ArgumentError|error: the following arguments are required", stderr)
    if match:
        return "ArgumentParserError"
    return None


def run() -> dict:
    report = {}
    for name, args in SCENARIOS.items():
        source_result = _run_cli(SOURCE_ROOT, *args)
        archive_result = _run_cli(ARCHIVE_ROOT, *args)
        report[name] = {
            "source_returncode": source_result.returncode,
            "archive_returncode": archive_result.returncode,
            "returncode_match": source_result.returncode == archive_result.returncode,
            "source_exception": _exception_class(source_result.stderr),
            "archive_exception": _exception_class(archive_result.stderr),
        }
        report[name]["exception_class_match"] = (
            report[name]["source_exception"] == report[name]["archive_exception"]
        )
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
