from __future__ import annotations

from ase.build import bulk
from ase.io import write
from pymatgen.io.ase import AseAtomsAdaptor
import pytest

from llm_csp.validation import validate_cif, validate_family_topology

pytest.importorskip("sca", reason="SCA is an excluded optional backend")

from sca.evaluators.topology import family_topology_metrics
from sca.pipelines import evaluate_one_cif


def _nacl_cif(tmp_path):
    path = tmp_path / "synthetic_nacl.cif"
    write(path, bulk("NaCl", "rocksalt", a=5.64))
    return path


def test_valid_cif_normalization_and_direct_sca_parity(tmp_path) -> None:
    path = _nacl_cif(tmp_path)
    direct, structure = evaluate_one_cif(path, target_formula="NaCl", run_id="parity")
    adapted = validate_cif(path, target_formula="NaCl", run_id="parity")

    assert structure is not None
    assert adapted.status == "evaluated"
    assert adapted.parseable is True
    assert adapted.composition["target_formula_match"] is True
    assert adapted.backend.version == "0.1.0"
    assert adapted.details["sca_record"] == direct.model_dump(mode="python")
    assert adapted.general_metrics["bond_reasonableness_score"] == direct.bond_reasonableness_score
    assert adapted.general_metrics["pre_dft_rank_score"] == direct.pre_dft_rank_score


def test_malformed_cif_is_a_structured_parse_failure(tmp_path) -> None:
    path = tmp_path / "malformed.cif"
    path.write_text("this is not a CIF", encoding="utf-8")

    result = validate_cif(path, run_id="malformed")

    assert result.status == "parse_failure"
    assert result.parseable is False
    assert result.valid is False
    assert result.errors
    assert result.details["sca_record"]["parse_ok"] is False


def test_validation_does_not_mutate_input_or_write_artifacts(tmp_path) -> None:
    path = _nacl_cif(tmp_path)
    before_bytes = path.read_bytes()
    before_names = sorted(item.name for item in tmp_path.iterdir())

    result = validate_cif(path, run_id="no-artifacts")

    assert result.parseable is True
    assert path.read_bytes() == before_bytes
    assert sorted(item.name for item in tmp_path.iterdir()) == before_names


def test_family_topology_matches_direct_sca_values(tmp_path) -> None:
    path = _nacl_cif(tmp_path)
    atoms = bulk("NaCl", "rocksalt", a=5.64)
    structure = AseAtomsAdaptor.get_structure(atoms)
    direct_metrics, direct_details = family_topology_metrics(structure, "ROCKSALT")

    adapted = validate_family_topology(structure, "ROCKSALT")

    assert adapted.status == "evaluated"
    assert adapted.available is True
    assert adapted.topology_status == direct_metrics["topology_status"]
    assert adapted.metrics == direct_metrics
    assert adapted.details == direct_details
    assert adapted.matches is (direct_metrics["topology_status"] == "PASS")
