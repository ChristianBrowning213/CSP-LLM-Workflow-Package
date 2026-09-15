from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd
import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter

from sca.electronic_stack import PAPER_FORMULAS, validate_paper_manifest
from sca.backends import verify_optional_backends
from sca.evaluators.chgnet import ChgnetStaticBenchmarkEvaluator
from sca.evaluators.relaxation_intent_retention import RelaxationIntentRetentionEvaluator
from sca.structure_transition import analyse_structure_transition


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks" / "paper_advanced_validation" / "PAPER_16_MANIFEST.csv"


def test_paper16_manifest():
    frame = pd.read_csv(MANIFEST, keep_default_na=False)
    assert len(frame) == 16
    assert set(frame["formula"]) == set(PAPER_FORMULAS)
    assert not frame.astype(str).apply(lambda column: column.str.contains("NASICON|NZP", case=False)).any().any()
    assert frame["cif_sha256"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert frame["intent_source"].str.len().gt(0).all()


def test_raw_cif_hash_preserved():
    result = validate_paper_manifest(MANIFEST)
    assert result["valid"]
    for row in result["rows"]:
        assert len(row["actual_sha256"]) == 64


def test_mlip_readiness():
    rows = verify_optional_backends()
    assert {row["status"] for row in rows} <= {
        "READY", "SKIPPED_DEPENDENCY", "SKIPPED_MODEL", "FAILED_IMPORT", "FAILED_INITIALIZATION"
    }
    assert {"chgnet_static", "m3gnet_static", "mace_static", "sevennet_static", "alignn"} <= {
        row["backend"] for row in rows
    }


def test_mlip_static_structured_failure(monkeypatch):
    def unavailable():
        raise RuntimeError("fixture backend unavailable")

    monkeypatch.setattr("sca.evaluators.chgnet._load_chgnet_model", unavailable)
    result = ChgnetStaticBenchmarkEvaluator().evaluate_path(
        Path(__file__).parent / "fixtures" / "tiny_valid.cif"
    )
    assert result.skipped is True
    assert result.error_type == "RuntimeError"


def test_structure_transition_known_fixture(tmp_path):
    initial = Structure(Lattice.cubic(4), ["Li", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    final = initial.copy()
    final.translate_sites([0], [0.025, 0, 0], frac_coords=True)
    result = analyse_structure_transition(initial, final)
    assert result.mapping_succeeded
    assert result.atomic_max_displacement_A == pytest.approx(0.1)
    assert result.atomic_rms_displacement_A == pytest.approx((0.1**2 / 2) ** 0.5)


def test_relaxation_intent_retention(tmp_path):
    structure = Structure(Lattice.cubic(4), ["Li", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    initial = tmp_path / "initial.cif"
    relaxed = tmp_path / "relaxed.cif"
    CifWriter(structure).write_file(initial)
    CifWriter(structure).write_file(relaxed)
    result = RelaxationIntentRetentionEvaluator().evaluate_item(
        {"initial_cif_path": initial, "relaxed_cif_path": relaxed}
    )
    assert result.metrics["overall_relaxation_status"] == "ROBUST"
    assert result.metrics["composition_retained"] is True


def test_relaxed_cif_written_separately(tmp_path):
    source = tmp_path / "generated.cif"
    relaxed = tmp_path / "mlip_relaxed" / "chgnet" / "candidate.cif"
    relaxed.parent.mkdir(parents=True)
    source.write_text("raw", encoding="utf-8")
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    relaxed.write_text("relaxed", encoding="utf-8")
    assert source != relaxed
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original


def test_mlip_relax_raw_not_overwritten(tmp_path):
    test_relaxed_cif_written_separately(tmp_path)
