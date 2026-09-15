from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from sok_llm_orchestrator.workflow.evidence import EvidenceItem, SPPEvidenceBundle
from sok_llm_orchestrator.workflow.spp_only_benchmark import benchmark_run_scope
from sok_llm_orchestrator.workflow.spp_package_audit import (
    assert_family_database_provenance,
    audit_cif_hash_chain,
    audit_spp_package,
    canonical_pair_key,
)


def test_benchmark_run_scope_is_stable_and_output_root_specific() -> None:
    with tempfile.TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        first_root = temporary_root / "result_a"
        second_root = temporary_root / "result_b"
        first = benchmark_run_scope(first_root)

        assert first == benchmark_run_scope(first_root)
        assert first == hashlib.sha256(
            str(first_root.resolve()).encode("utf-8")
        ).hexdigest()[:12]
        assert first != benchmark_run_scope(second_root)
        assert len(first) == 12


def _pot(root: Path, pair: str, *, capped: bool = False) -> Path:
    folder = root / pair.upper()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pair.upper()}.POT"
    values = np.ones(222) if capped else np.linspace(10.0, -2.0, 222)
    rows = ["spline cubic reverse", f"{pair} 0.0 11.0"]
    rows.extend(f"{distance:.5f} {value:.8f}" for distance, value in zip(np.linspace(0, 11, 222), values, strict=True))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _request(root: Path, pair: str, status: str, *, observations: int = 10) -> dict:
    return {
        "pot_root": root,
        "quality": {"request_pair_results": [{
            "species_pair": pair,
            "request_pair_status": status,
            "observations": observations,
            "structures_contributing": 2 if observations else 0,
            "guidance_mode": "REQUEST_PLUS_REGULATOR" if status == "REQUEST_USABLE" else "REGULATOR_ONLY_LOCAL_MISSING",
        }]},
    }


def test_valid_local_and_global_make_regulated_final_pair() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); request = root / "request"; regulator = root / "regulator"
        _pot(request, "Na-Cl"); _pot(regulator, "CL-NA")
        audit = audit_spp_package(
            required_pairs=["Cl-Na"], request_spp=_request(request, "NA-CL", "REQUEST_USABLE"),
            regulator_root=regulator,
        )
        assert audit["SPP_READY"] is True
        row = audit["pair_diagnostics"][0]
        assert row["intended_final_source"] == "request_plus_global_regulator"
        assert row["local_curve_valid"] is True
        assert row["request_curve_hash"]
        assert row["global_curve_hash"]
        assert row["final_curve_hash"]
        assert row["final_curve_hash_kind"] == "weighted_component_manifest"


def test_missing_local_with_real_global_is_spp_ready() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); regulator = root / "regulator"; request = root / "request"
        request.mkdir(); _pot(regulator, "Na-Cl")
        audit = audit_spp_package(
            required_pairs=["Cl-Na"], request_spp=_request(request, "Cl-Na", "REQUEST_MISSING", observations=0),
            regulator_root=regulator,
        )
        assert audit["SPP_READY"] is True
        row = audit["pair_diagnostics"][0]
        assert row["intended_final_source"] == "global_regulator"
        assert row["final_curve_hash"] == row["global_curve_hash"]
        assert row["final_curve_hash_kind"] == "pot_artifact"


def test_capped_local_with_real_global_uses_global_without_weakening_quality_gate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); request = root / "request"; regulator = root / "regulator"
        _pot(request, "Na-Cl", capped=True); _pot(regulator, "Na-Cl")
        audit = audit_spp_package(
            required_pairs=["Cl-Na"], request_spp=_request(request, "Cl-Na", "REQUEST_INSUFFICIENT"),
            regulator_root=regulator,
        )
        row = audit["pair_diagnostics"][0]
        assert row["local_curve_quality"] == "capped"
        assert row["intended_final_source"] == "global_regulator"
        assert audit["SPP_READY"] is True


def test_missing_local_and_global_never_creates_fake_fallback() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); request = root / "request"; regulator = root / "regulator"
        request.mkdir(); regulator.mkdir()
        audit = audit_spp_package(
            required_pairs=["Cl-Na"], request_spp=_request(request, "Cl-Na", "REQUEST_MISSING", observations=0),
            regulator_root=regulator,
        )
        assert audit["SPP_READY"] is False
        assert audit["unsupported_pairs"] == ["Cl-Na"]
        assert audit["uses_synthetic_fallback"] is False


def test_pair_matching_is_case_and_order_insensitive_only() -> None:
    assert canonical_pair_key("Cl-Na") == canonical_pair_key("CL-NA") == canonical_pair_key("Na-Cl")
    assert canonical_pair_key("Cl-Na") != canonical_pair_key("Cl-K")


def test_family_database_assertion_accepts_exact_spinel_database_and_rejects_wrong_one() -> None:
    with tempfile.TemporaryDirectory() as directory:
        crystal = Path(directory)
        database = crystal / "artifacts" / "mp_oxide_families_v1" / "MP_SPINEL_OXIDES_V1" / "MP_SPINEL_OXIDES_V1.db"
        database.parent.mkdir(parents=True); database.write_bytes(b"spinel-db")
        digest = hashlib.sha256(database.read_bytes()).hexdigest()
        target = {"family": "spinel", "dataset_id": "MP_SPINEL_OXIDES_V1"}
        retrieval = {"corpus": {"corpus_id": "mp_spinel_oxides_v1", "database": str(database), "hash": digest}}
        assert assert_family_database_provenance(target=target, retrieval=retrieval, crystal_root=crystal)["EXPECTED_FAMILY_DB_EQUALS_ACTUAL_FAMILY_DB"]
        retrieval["corpus"]["corpus_id"] = "mp_layered_battery_oxides_v1"
        with pytest.raises(RuntimeError, match="family database provenance mismatch"):
            assert_family_database_provenance(target=target, retrieval=retrieval, crystal_root=crystal)


def test_selected_cif_hashes_equal_actual_spp_input_hashes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); source = root / "source.cif"; input_dir = root / "input"; input_dir.mkdir()
        source.write_bytes(b"real-cif-bytes")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        shutil.copy2(source, input_dir / "structure-1.cif")
        evidence = SPPEvidenceBundle(
            corpus_id="spinel", corpus_hash="a" * 64, selection_policy="test", required_pairs=("Na-Cl",),
            pair_structure_counts={"Na-Cl": 1}, pair_evidence_status={},
            selected=(EvidenceItem("structure-1", 1, 1.0, str(source), digest, "semantic_core", ("Na-Cl",), "mp-1", "spinel"),),
            exclusion_audit=(), bundle_hash="b" * 64,
        )
        audit = audit_cif_hash_chain(evidence=evidence, input_dir=input_dir)
        assert audit["SELECTED_CORPUS_HASHES_EQUAL_SPP_INPUT_HASHES"] is True
        (input_dir / "stale.cif").write_bytes(b"stale")
        assert audit_cif_hash_chain(evidence=evidence, input_dir=input_dir)["SELECTED_CORPUS_HASHES_EQUAL_SPP_INPUT_HASHES"] is False
