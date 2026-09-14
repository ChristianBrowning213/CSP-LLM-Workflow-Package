from __future__ import annotations

from pathlib import Path

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool
from spp_maker_qlip.corpus_quality import audit_corpus_for_formula
from spp_maker_qlip.pot_quality import audit_pot_root


def _fixture_cif_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cifs"


def _runtime(tmp_path: Path) -> RuntimeContext:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = _fixture_cif_dir().resolve()
    return RuntimeContext(
        config=MCPServerConfig(
            allowed_read_roots=[str(cif_root), str(tmp_path.resolve())],
            allowed_write_roots=[str(tmp_path.resolve())],
            max_cif_count=100,
            max_runtime_seconds=600,
            max_output_bytes=100_000_000,
        ),
        read_roots=(cif_root, tmp_path.resolve()),
        write_roots=(tmp_path.resolve(),),
        repo_root=repo_root.resolve(),
    )


def test_zns_corpus_without_target_elements_is_unsuitable() -> None:
    audit = audit_corpus_for_formula(_fixture_cif_dir(), "ZnS", cutoff=6.0)

    assert audit["corpus_quality_status"] == "unsuitable"
    assert audit["files_with_all_target_elements"] == []
    assert audit["files_with_target_cross_pairs"] == []
    assert audit["geometric_pair_counts"]["S-Zn"] == 0
    assert any(item["code"] == "target_cross_pair_absent" for item in audit["corpus_quality_errors"])


def test_nacl_corpus_distinguishes_cross_pair_from_self_pairs() -> None:
    audit = audit_corpus_for_formula(_fixture_cif_dir(), "NaCl", cutoff=6.0)

    assert audit["corpus_quality_status"] in {"weak", "suitable"}
    assert any(Path(path).name == "nacl.cif" for path in audit["files_with_all_target_elements"])
    assert any(Path(path).name == "nacl.cif" for path in audit["files_with_exact_or_reduced_formula_match"])
    assert any(Path(path).name == "nacl.cif" for path in audit["files_with_target_cross_pairs"])
    assert audit["geometric_pair_counts"]["Cl-Na"] > 0
    for pair in ("Cl-Cl", "Na-Na"):
        assert pair in audit["geometric_pair_counts"]


def test_formula_corpus_mismatch_is_unsuitable() -> None:
    audit = audit_corpus_for_formula(_fixture_cif_dir(), "LiCoO2", cutoff=6.0)

    assert audit["corpus_quality_status"] == "unsuitable"
    codes = {item["code"] for item in audit["corpus_quality_errors"]}
    assert "target_elements_absent" in codes
    assert "target_cross_pair_absent" in codes


def test_exact_formula_match_is_recorded_for_nacl() -> None:
    audit = audit_corpus_for_formula(_fixture_cif_dir(), "NaCl", cutoff=6.0)

    assert audit["files_with_exact_or_reduced_formula_match"]
    assert audit["recommendation"] in {
        "proceed_with_fresh_required_pair_spp",
        "prefer_exact_formula_corpus_or_increase_structural_coverage",
    }


def test_run_pipeline_output_contains_corpus_quality(tmp_path: Path) -> None:
    response = invoke_tool(
        "spp.run_pipeline",
        {
            "trace_id": "trace_zns_corpus_quality",
            "cif_dir": str(_fixture_cif_dir()),
            "out_dir": str(tmp_path / "out"),
            "name": "zns_corpus_quality",
            "material_system": "ZnS",
            "qlip_pair_mode": "required_pairs",
            "qlip_pair_cutoff": 6.0,
            "fit": {"fit_method": "neighbors"},
            "calibration": {"target": 5.0, "max_calib": 2, "bandpass": {"enabled": False}},
        },
        runtime=_runtime(tmp_path),
    )

    assert response["ok"] is True, response
    package = response["result"]["qlip_package"]
    assert package["status"] == "partial"
    assert package["request_ref"] is None
    quality = package["fresh_generation"]["corpus_quality"]
    assert quality["corpus_quality_status"] == "unsuitable"
    assert quality["geometric_pair_counts"]["S-Zn"] == 0
    codes = {item["code"] for item in package["errors"]}
    assert "corpus_unsuitable_for_spp" in codes
    assert "target_cross_pair_absent" in codes


def test_pair_level_evidence_summary_is_generated() -> None:
    audit = audit_corpus_for_formula(_fixture_cif_dir(), "NaCl", cutoff=6.0)

    summary = {item["required_pair"]: item for item in audit["pair_evidence_summary"]}
    assert summary["Cl-Na"]["direct_observation_count"] > 0
    assert summary["Cl-Na"]["pair_quality"] == "usable"
    assert "pair_evidence_summary" in audit


def test_high_max_cap_fraction_marks_pot_as_capped(tmp_path: Path) -> None:
    pot_dir = tmp_path / "spp_root" / "A-B"
    pot_dir.mkdir(parents=True)
    pot_path = pot_dir / "A-B.POT"
    pot_path.write_text(
        "\n".join(
            [
                "0.5 10.0",
                "1.0 10.0",
                "1.5 10.0",
                "2.0 10.0",
                "2.5 1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    audit = audit_pot_root(tmp_path / "spp_root", required_pairs=["A-B"], max_cap_fraction_threshold=0.5)

    assert audit["spp_pot_quality_status"] == "unusable"
    assert audit["pairs"][0]["pot_quality"] == "capped"
    assert audit["diagnostic_only"] is True
