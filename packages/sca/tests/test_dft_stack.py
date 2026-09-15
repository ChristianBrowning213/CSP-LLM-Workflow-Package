from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from sca.dft.analysis.formation_energy import ElementalReference, calculate_formation_energy
from sca.dft.analysis.hull import DFTHullEntry, calculate_dft_hull
from sca.dft.analysis.transition import validate_post_dft_structure
from sca.dft.backends.castep import CastepBackend
from sca.dft.compatibility import compare_fingerprints
from sca.dft.schema import (
    CompatibilityStatus,
    DFTCalculationSpec,
    DFTCompatibilityFingerprint,
    DFTFailureType,
    DFTStatus,
)
from sca.dft.slurm.render import query_status, render_slurm_script, submit_calculation
from sca.dft.slurm.schema import SlurmConfig


FIXTURES = Path(__file__).parent / "fixtures"


def fingerprint(**changes):
    values = {
        "engine_family": "castep",
        "energy_convention": "periodic_dft_total_energy",
        "xc_functional": "PBE",
        "pseudopotential_family": "OTFG",
        "hubbard_u": {},
        "dispersion": None,
        "correction_scheme": "none",
    }
    values.update(changes)
    return DFTCompatibilityFingerprint(**values)


def make_spec(cif: Path, **changes):
    values = {
        "calculation_id": "test-relax-v1",
        "candidate_id": "test",
        "input_cif_path": str(cif),
        "input_cif_sha256": hashlib.sha256(cif.read_bytes()).hexdigest(),
        "engine": "castep",
        "calculation_type": "RELAX",
        "xc_functional": "PBE",
        "pseudopotential_family": "OTFG",
        "cutoff_energy": 700,
        "kpoint_spacing": 0.04,
        "spin_polarized": False,
        "energy_tolerance": 1e-6,
        "force_tolerance": 0.03,
        "stress_tolerance": 0.05,
        "max_steps": 200,
        "correction_scheme": "none",
    }
    values.update(changes)
    return DFTCalculationSpec(**values)


def prepare(tmp_path):
    cif = FIXTURES / "tiny_valid.cif"
    return CastepBackend().prepare(make_spec(cif), tmp_path)


def test_dft_schema_roundtrip():
    spec = make_spec(FIXTURES / "tiny_valid.cif")
    assert DFTCalculationSpec.model_validate_json(spec.model_dump_json()) == spec


def test_dft_prepare_does_not_modify_input_cif(tmp_path):
    cif = tmp_path / "source.cif"
    shutil.copyfile(FIXTURES / "tiny_valid.cif", cif)
    before = hashlib.sha256(cif.read_bytes()).hexdigest()
    root = CastepBackend().prepare(make_spec(cif), tmp_path / "prepared")
    assert hashlib.sha256(cif.read_bytes()).hexdigest() == before
    assert (root / "input.cif").is_file()
    assert (root / "settings_fingerprint.json").is_file()


def test_backend_missing_executable_structured_failure(monkeypatch):
    monkeypatch.delenv("CASTEP_COMMAND", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert CastepBackend().executable_available() is False


def test_slurm_script_generation():
    config = SlurmConfig(
        partition="compute", walltime="01:00:00", ntasks=8, memory="16G", executable="castep.mpi"
    )
    script = render_slurm_script(config, "calc-1", "calc-1")
    assert "#SBATCH --partition=compute" in script
    assert "srun castep.mpi calc-1" in script


def test_dft_result_parser_success(tmp_path):
    root = prepare(tmp_path)
    shutil.copyfile(FIXTURES / "dft" / "success.castep", root / "test.castep")
    result = CastepBackend().parse(root)
    assert result.status == DFTStatus.COMPLETED
    assert result.converged is True
    assert result.total_energy_eV == pytest.approx(-12.5)


def test_dft_result_parser_not_converged(tmp_path):
    root = prepare(tmp_path)
    shutil.copyfile(FIXTURES / "dft" / "not_converged.castep", root / "test.castep")
    result = CastepBackend().parse(root)
    assert result.status == DFTStatus.NOT_CONVERGED
    assert result.failure_type == DFTFailureType.SCF_NOT_CONVERGED


def test_dft_result_parser_timeout(tmp_path):
    root = prepare(tmp_path)
    shutil.copyfile(FIXTURES / "dft" / "timeout.castep", root / "test.castep")
    result = CastepBackend().parse(root)
    assert result.status == DFTStatus.TIMEOUT
    assert result.failure_type == DFTFailureType.WALLTIME


def test_post_dft_intent_retention():
    cif = FIXTURES / "tiny_valid.cif"
    result = validate_post_dft_structure(cif, cif, converged=True)
    assert result["dft_relaxation_status"] == "DFT_ROBUST"


def test_dft_compatibility_match():
    assert compare_fingerprints(fingerprint(), fingerprint()).status == CompatibilityStatus.COMPATIBLE


def test_dft_compatibility_rejects_functional_mismatch():
    assert compare_fingerprints(fingerprint(), fingerprint(xc_functional="LDA")).status == CompatibilityStatus.INCOMPATIBLE


def test_dft_compatibility_rejects_pseudopotential_mismatch():
    other = fingerprint(pseudopotential_family="PAW")
    assert compare_fingerprints(fingerprint(), other).status == CompatibilityStatus.INCOMPATIBLE


def test_dft_compatibility_rejects_u_mismatch():
    assert compare_fingerprints(fingerprint(), fingerprint(hubbard_u={"Fe": 4.0})).status == CompatibilityStatus.INCOMPATIBLE


def test_incompatible_energy_settings_rejected():
    assert compare_fingerprints(fingerprint(), fingerprint(dispersion="D3")).status == CompatibilityStatus.INCOMPATIBLE


def test_formation_energy_known_fixture():
    refs = [
        ElementalReference(element="Mg", reference_phase="hcp", reference_energy_eV_per_atom=-1, compatibility_fingerprint=fingerprint(), source="fixture"),
        ElementalReference(element="O", reference_phase="O2", reference_energy_eV_per_atom=-2, compatibility_fingerprint=fingerprint(), source="fixture"),
    ]
    result = calculate_formation_energy("MgO", -10, fingerprint(), refs)
    assert result.status == "COMPUTABLE"
    assert result.formation_energy_eV_atom == pytest.approx(-3.5)


def hull_entry(material_id, formula, energy, fp=None):
    return DFTHullEntry(
        chemical_system="Li-O", material_id=material_id, formula=formula, total_energy_eV=energy,
        compatibility_fingerprint=fp or fingerprint(), source="fixture"
    )


def test_phase_diagram_known_fixture():
    candidate = hull_entry("candidate", "Li2O", -6)
    refs = [hull_entry("Li", "Li", 0), hull_entry("O", "O", 0)]
    result = calculate_dft_hull(candidate, refs)
    assert result.hull_status == "COMPUTABLE"
    assert result.is_on_hull is True


def test_ehull_known_fixture():
    candidate = hull_entry("candidate", "Li2O", -5)
    refs = [hull_entry("Li", "Li", 0), hull_entry("O", "O", 0), hull_entry("lower", "Li2O", -6)]
    result = calculate_dft_hull(candidate, refs)
    assert result.energy_above_hull_eV_atom == pytest.approx(1 / 3)


def test_missing_hull_entries_not_computable():
    result = calculate_dft_hull(hull_entry("candidate", "Li2O", -5), [hull_entry("Li", "Li", 0)])
    assert result.hull_status == "NOT_COMPUTABLE"


def test_incompatible_hull_entries_not_computable():
    refs = [hull_entry("Li", "Li", 0), hull_entry("O", "O", 0, fingerprint(xc_functional="LDA"))]
    result = calculate_dft_hull(hull_entry("candidate", "Li2O", -5), refs)
    assert result.hull_status == "NOT_COMPUTABLE_INCOMPATIBLE_REFERENCES"


def test_slurm_submit_captures_real_mock_id(tmp_path, monkeypatch):
    root = prepare(tmp_path)
    (root / "submit.slurm").write_text("#!/bin/bash\n", encoding="utf-8")
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "Submitted batch job 12345\n", "")

    record = submit_calculation(root, runner=runner)
    assert record.slurm_job_id == "12345"


def test_slurm_status_normalization():
    from sca.dft.schema import DFTExecutionRecord

    record = DFTExecutionRecord(calculation_id="x", calculation_dir=".", slurm_job_id="123")
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "RUNNING|\n", "")

    assert query_status(record, runner=runner).status == DFTStatus.RUNNING
