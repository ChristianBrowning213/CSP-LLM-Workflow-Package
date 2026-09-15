from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("pymatgen")

from pymatgen.core import Lattice, Structure  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "classify_paper1_family_recovery.py"
SPEC = importlib.util.spec_from_file_location("paper1_family_recovery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def _cscl(a: float = 3.6) -> Structure:
    return Structure(Lattice.cubic(a), ["Cs", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]])


def _rocksalt(a: float = 5.6) -> Structure:
    lattice = Lattice.cubic(a)
    species = ["Na", "Cl", "Na", "Cl", "Na", "Cl", "Na", "Cl"]
    coords = [
        [0, 0, 0], [0.5, 0, 0], [0, 0.5, 0.5], [0.5, 0.5, 0.5],
        [0.5, 0.5, 0], [0, 0.5, 0], [0.5, 0, 0.5], [0, 0, 0.5],
    ]
    return Structure(lattice, species, coords)


def test_symmetry_consistency_signature() -> None:
    assert mod._symmetry_consistent("cscl_b2", 221, "AB") is True
    assert mod._symmetry_consistent("rocksalt_b1", 221, "AB") is False
    assert mod._symmetry_consistent("rocksalt_b1", 225, "AB") is True
    assert mod._symmetry_consistent("cscl_b2", None, None) is False


def test_classify_candidate_family_pass() -> None:
    from pymatgen.analysis.prototypes import AflowPrototypeMatcher

    with tempfile.TemporaryDirectory() as directory:
        cif = Path(directory) / "cscl.cif"
        _cscl().to(filename=str(cif))
        row = mod.classify_candidate(
            condition="C_RETRIEVAL_CONDITIONED", row_id="cscl_b2_001_cscl", requested_family="cscl_b2",
            formula="CsCl", candidate=cif, matcher=AflowPrototypeMatcher(),
        )
    assert row["verdict"] == "FAMILY_PASS"
    assert row["detected_family"] == "cscl_b2"
    assert row["detected_space_group_number"] == 221


def test_classify_candidate_family_fail_when_wrong_prototype() -> None:
    from pymatgen.analysis.prototypes import AflowPrototypeMatcher

    # A CsCl structure requested as rocksalt must be a FAMILY_FAIL, not a pass.
    with tempfile.TemporaryDirectory() as directory:
        cif = Path(directory) / "cscl.cif"
        _cscl().to(filename=str(cif))
        row = mod.classify_candidate(
            condition="C_RETRIEVAL_CONDITIONED", row_id="rocksalt_b1_001_cscl", requested_family="rocksalt_b1",
            formula="CsCl", candidate=cif, matcher=AflowPrototypeMatcher(),
        )
    assert row["verdict"] == "FAMILY_FAIL"
    assert row["detected_family"] == "cscl_b2"


def test_classify_candidate_no_candidate() -> None:
    from pymatgen.analysis.prototypes import AflowPrototypeMatcher

    row = mod.classify_candidate(
        condition="B_GLOBAL_REGULATOR_ONLY", row_id="rocksalt_b1_009_missing", requested_family="rocksalt_b1",
        formula="NaCl", candidate=Path("does") / "not" / "exist.cif", matcher=AflowPrototypeMatcher(),
    )
    assert row["verdict"] == "NO_CANDIDATE"


def test_summarize_recovery_rate() -> None:
    rows = [
        {"condition": "C_RETRIEVAL_CONDITIONED", "requested_family": "cscl_b2", "verdict": "FAMILY_PASS"},
        {"condition": "C_RETRIEVAL_CONDITIONED", "requested_family": "cscl_b2", "verdict": "FAMILY_FAIL"},
        {"condition": "C_RETRIEVAL_CONDITIONED", "requested_family": "cscl_b2", "verdict": "NO_CANDIDATE"},
    ]
    summary = {(s["condition"], s["family"]): s for s in mod._summarize(rows)}
    cscl = summary[("C_RETRIEVAL_CONDITIONED", "cscl_b2")]
    assert cscl["family_pass"] == 1
    assert cscl["candidates"] == 2
    assert cscl["recovery_rate"] == 0.5
