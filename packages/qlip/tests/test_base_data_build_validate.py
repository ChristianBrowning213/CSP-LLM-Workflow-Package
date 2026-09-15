from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.validate_base_data import validate


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "base"


def test_build_script_writes_all_base_data_files():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_base_data.py")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    for name in (
        "elements.json",
        "radii.json",
        "ionic_radii.json",
        "radius_policy.json",
        "pair_distance_policy.json",
        "provenance.json",
    ):
        assert (DATA_DIR / name).exists()


def test_validate_script_passes_on_generated_data():
    validate()


def test_generated_data_has_expected_coverage_and_provenance():
    elements = json.loads((DATA_DIR / "elements.json").read_text(encoding="utf-8"))
    radii = json.loads((DATA_DIR / "radii.json").read_text(encoding="utf-8"))
    ionic = json.loads((DATA_DIR / "ionic_radii.json").read_text(encoding="utf-8"))
    provenance = json.loads((DATA_DIR / "provenance.json").read_text(encoding="utf-8"))

    assert len(elements["records"]) == 118
    assert len(radii["records"]) == 118
    assert sum(len(record["ionic_radii"]) for record in ionic["records"].values()) > 0
    for package in ("ase", "mendeleev", "pymatgen", "smact"):
        assert provenance["package_versions"][package]
