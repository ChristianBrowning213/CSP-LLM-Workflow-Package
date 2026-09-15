from __future__ import annotations

from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages, WorkflowConfig, WorkflowStageError


def _cif(root: Path, name: str, species: list[str]) -> Path:
    path = root / f"{name}.cif"
    coordinates = [[index / len(species)] * 3 for index in range(len(species))]
    Structure(Lattice.cubic(8), species, coordinates).to(filename=path)
    return path


def _record(structure_id: str, rank: int, path: Path) -> dict:
    return {
        "structure_id": structure_id,
        "rank": rank,
        "score": 1.0 / rank,
        "cif_export": {"status": "exported", "path": str(path)},
    }


def _retrieval(selected: list[dict], corpus_id: str = "fixture") -> dict:
    return {"corpus": {"corpus_id": corpus_id, "hash": "fixture-hash"}, "selected": selected}


def _regulator_with_na_o(root: Path) -> Path:
    regulator = root / "regulator"
    pair_dir = regulator / "NA-O"
    pair_dir.mkdir(parents=True)
    rows = ["spline cubic reverse", "NA-O 0.0 11.0"]
    rows.extend(f"{index * 0.05:.2f} {index * 0.01:.6f}" for index in range(221))
    (pair_dir / "NA-O.POT").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return regulator


def _mock_unusable_request_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        "spp_maker_qlip.required_pair_extraction.export_required_pair_spp_root",
        lambda **kwargs: {
            "required_pairs": ["Na-O"],
            "missing_pairs": [],
            "pair_stats": {"Na-O": {"count": 12, "min_distance": 2.0, "max_distance": 4.0}},
            "spp_pot_quality": {
                "spp_pot_quality_status": "unusable",
                "pairs": [{"pair": "Na-O", "pot_quality": "capped", "max_cap_fraction": 0.9}],
            },
        },
    )


def _mock_usable_request_generation(monkeypatch) -> None:
    def export(**kwargs):
        pair_dir = Path(kwargs["out_root"]) / "Na-O"
        pair_dir.mkdir(parents=True)
        rows = ["spline cubic reverse", "Na-O 0.0 11.0"]
        rows.extend(f"{index * 0.05:.2f} {index * 0.01:.6f}" for index in range(221))
        (pair_dir / "Na-O.POT").write_text("\n".join(rows) + "\n", encoding="utf-8")
        return {
            "required_pairs": ["Na-O"],
            "missing_pairs": [],
            "pair_stats": {"Na-O": {"count": 12, "min_distance": 2.0, "max_distance": 4.0}},
            "spp_pot_quality": {
                "spp_pot_quality_status": "usable",
                "pairs": [{"pair": "Na-O", "pot_quality": "usable", "max_cap_fraction": 0.1}],
            },
        }

    monkeypatch.setattr(
        "spp_maker_qlip.required_pair_extraction.export_required_pair_spp_root",
        export,
    )


def _mock_missing_request_generation(monkeypatch) -> None:
    monkeypatch.setattr(
        "spp_maker_qlip.required_pair_extraction.export_required_pair_spp_root",
        lambda **kwargs: {
            "required_pairs": ["Na-O"],
            "missing_pairs": ["Na-O"],
            "pair_stats": {},
            "spp_pot_quality": {
                "spp_pot_quality_status": "missing",
                "pairs": [],
            },
        },
    )


def _mock_common_contract_insufficient_with_global(monkeypatch) -> None:
    monkeypatch.setattr(
        "spp_maker.common_contract.build_local_supercell_artifact",
        lambda **kwargs: {"pair_observations": {"Na-O": 12}, "pairs": []},
    )

    def blend(**kwargs):
        out_root = Path(kwargs["out_root"])
        selected = out_root / "Na-O" / "Na-O.POT"
        global_pot = out_root.parent / "global_common_contract" / "Na-O" / "Na-O.POT"
        for path in (selected, global_pot):
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = ["spline cubic reverse", "Na-O 0.0 10.0"]
            rows.extend(f"{0.025 + index * 0.05:.3f} {index * 0.01:.6f}" for index in range(200))
            path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return {
            "pairs": [{
                "pair": "Na-O",
                "mode": "GLOBAL_ONLY_LOCAL_ABSENT_OR_INVALID",
                "local_valid": False,
                "global_valid": True,
                "output_pot": str(selected),
            }],
        }

    monkeypatch.setattr("spp_maker.common_contract.blend_contract_roots", blend)


def _mock_common_contract_without_any_valid_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "spp_maker.common_contract.build_local_supercell_artifact",
        lambda **kwargs: {"pair_observations": {"Na-O": 12}, "pairs": []},
    )
    monkeypatch.setattr(
        "spp_maker.common_contract.blend_contract_roots",
        lambda **kwargs: (_ for _ in ()).throw(
            ValueError("neither local nor global contract artifact is valid for Na-O")
        ),
    )


def test_spp_evidence_does_not_stop_at_first_pair_complete_structure_when_statistical_support_is_insufficient(workdir: Path) -> None:
    records = [_record(f"s{rank}", rank, _cif(workdir, f"s{rank}", ["Na", "O"])) for rank in range(1, 4)]
    bundle = assemble_spp_evidence(retrieval=_retrieval(records), required_pairs=["Na-O"], max_ranked_structures=3)
    assert [item.structure_id for item in bundle.selected] == ["s1", "s2", "s3"]
    assert bundle.pair_structure_counts == {"Na-O": 3}


def test_spp_evidence_selection_is_deterministic(workdir: Path) -> None:
    records = [_record(f"s{rank}", rank, _cif(workdir, f"s{rank}", ["Na", "O"])) for rank in (3, 1, 2)]
    first = assemble_spp_evidence(retrieval=_retrieval(records), required_pairs=["Na-O"], max_ranked_structures=3)
    second = assemble_spp_evidence(retrieval=_retrieval(list(reversed(records))), required_pairs=["Na-O"], max_ranked_structures=3)
    assert first.to_dict() == second.to_dict()


def test_spp_evidence_selection_preserves_retrieval_rank(workdir: Path) -> None:
    records = [_record(f"s{rank}", rank, _cif(workdir, f"s{rank}", ["Na", "O"])) for rank in (4, 2, 1, 3)]
    bundle = assemble_spp_evidence(retrieval=_retrieval(records), required_pairs=["Na-O"], max_ranked_structures=4)
    assert [item.retrieval_rank for item in bundle.selected] == [1, 2, 3, 4]


def test_pair_coverage_expansion_uses_same_canonical_corpus(workdir: Path) -> None:
    primary = _record("primary", 1, _cif(workdir, "primary", ["Na"]))
    supplement = _record("supplement", 2, _cif(workdir, "supplement", ["Na", "O"]))
    retrieval = _retrieval([primary])
    retrieval["pair_coverage_expansion"] = {"corpus_id": "fixture", "selected": [supplement]}
    bundle = assemble_spp_evidence(retrieval=retrieval, required_pairs=["Na-O"])
    assert [item.structure_id for item in bundle.selected] == ["primary", "supplement"]
    assert bundle.selected[-1].inclusion_reason == "same_corpus_required_pair_coverage"

    retrieval["pair_coverage_expansion"]["corpus_id"] = "other"
    with pytest.raises(ValueError, match="must use the same corpus"):
        assemble_spp_evidence(retrieval=retrieval, required_pairs=["Na-O"])


def test_benchmark_exclusion_applied_before_spp_evidence_selection(workdir: Path) -> None:
    records = [
        _record("held-out", 1, _cif(workdir, "held-out", ["Na", "O"])),
        _record("allowed", 2, _cif(workdir, "allowed", ["Na", "O"])),
    ]
    bundle = assemble_spp_evidence(
        retrieval=_retrieval(records), required_pairs=["Na-O"], excluded_structure_ids=["held-out"], max_ranked_structures=1
    )
    assert [item.structure_id for item in bundle.selected] == ["allowed"]
    assert bundle.exclusion_audit[0]["structure_id"] == "held-out"


def test_unusable_request_pair_uses_regulator_fallback(workdir: Path, monkeypatch) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_unusable_request_generation(monkeypatch)
    result = ProductionWorkflowStages().fit_request_spp(
        bundle,
        {"formula": "NaO"},
        WorkflowConfig(output_root=workdir, regulator_root=_regulator_with_na_o(workdir)),
        workdir / "run",
    )
    pair = result["quality"]["request_pair_results"][0]
    assert pair["request_pair_status"] == "REQUEST_INSUFFICIENT_LOCAL_EVIDENCE"
    assert pair["request_pot_path"] is None
    assert pair["regulator_available"] is True
    assert pair["guidance_mode"] == "REGULATOR_ONLY_LOCAL_INSUFFICIENT"
    assert result["quality"]["unsupported_pair_count"] == 0
    assert result["quality"]["status"] == "NO_LOCAL_SUPPORT_REGULATOR_ONLY"


def test_unusable_request_pair_without_regulator_fails_loudly(workdir: Path, monkeypatch) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_unusable_request_generation(monkeypatch)
    empty_regulator = workdir / "empty-regulator"
    empty_regulator.mkdir()
    with pytest.raises(WorkflowStageError) as caught:
        ProductionWorkflowStages().fit_request_spp(
            bundle,
            {"formula": "NaO"},
            WorkflowConfig(output_root=workdir, regulator_root=empty_regulator),
            workdir / "run",
        )
    assert caught.value.stage == "guidance_pair_coverage"
    assert caught.value.code == "GUIDANCE_PAIR_UNSUPPORTED"
    assert caught.value.details["unsupported_pairs"] == ["Na-O"]


def test_usable_request_pair_remains_primary_with_regulator_available(workdir: Path, monkeypatch) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_usable_request_generation(monkeypatch)
    result = ProductionWorkflowStages().fit_request_spp(
        bundle,
        {"formula": "NaO"},
        WorkflowConfig(output_root=workdir, regulator_root=_regulator_with_na_o(workdir)),
        workdir / "run",
    )
    pair = result["quality"]["request_pair_results"][0]
    assert pair["request_pair_status"] == "REQUEST_USABLE"
    assert pair["request_pot_path"] is not None
    assert pair["regulator_available"] is True
    assert pair["guidance_mode"] == "REQUEST_PLUS_REGULATOR"
    assert result["quality"]["request_supported_pair_count"] == 1
    assert result["quality"]["regulator_fallback_pair_count"] == 0


def test_missing_request_pair_uses_distinct_regulator_fallback(workdir: Path, monkeypatch) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_missing_request_generation(monkeypatch)
    result = ProductionWorkflowStages().fit_request_spp(
        bundle,
        {"formula": "NaO"},
        WorkflowConfig(output_root=workdir, regulator_root=_regulator_with_na_o(workdir)),
        workdir / "run",
    )
    pair = result["quality"]["request_pair_results"][0]
    assert pair["request_pair_status"] == "REQUEST_MISSING"
    assert pair["request_pot_path"] is None
    assert pair["regulator_available"] is True
    assert pair["regulator_pot_path"] is not None
    assert pair["guidance_mode"] == "REGULATOR_ONLY_LOCAL_MISSING"
    assert result["quality"]["regulator_fallback_pair_count"] == 1


def test_missing_request_pair_without_regulator_fails_loudly(workdir: Path, monkeypatch) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_missing_request_generation(monkeypatch)
    empty_regulator = workdir / "empty-regulator"
    empty_regulator.mkdir()
    with pytest.raises(WorkflowStageError) as caught:
        ProductionWorkflowStages().fit_request_spp(
            bundle,
            {"formula": "NaO"},
            WorkflowConfig(output_root=workdir, regulator_root=empty_regulator),
            workdir / "run",
        )
    assert caught.value.stage == "guidance_pair_coverage"
    assert caught.value.code == "GUIDANCE_PAIR_UNSUPPORTED"
    assert caught.value.details["unsupported_pairs"] == ["Na-O"]
    pair = caught.value.details["pair_results"][0]
    assert pair["request_pair_status"] == "REQUEST_MISSING"
    assert pair["guidance_mode"] == "UNSUPPORTED_REQUIRED_PAIR"


def test_common_contract_keeps_insufficient_request_status_separate_from_selected_global(
    workdir: Path, monkeypatch,
) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_common_contract_insufficient_with_global(monkeypatch)
    regulator = workdir / "common-regulator"
    regulator.mkdir()
    result = ProductionWorkflowStages().fit_request_spp(
        bundle,
        {"formula": "NaO"},
        WorkflowConfig(
            output_root=workdir,
            regulator_root=regulator,
            spp_artifact_contract="dmytro_gr_v1",
        ),
        workdir / "run",
    )
    pair = result["quality"]["request_pair_results"][0]
    assert pair["request_pair_status"] == "REQUEST_INSUFFICIENT_LOCAL_EVIDENCE"
    assert pair["request_pot_path"] is None
    assert pair["regulator_available"] is True
    assert pair["guidance_mode"] == "REGULATOR_ONLY_LOCAL_INSUFFICIENT"
    assert pair["selected_pot_source"] == "GLOBAL_ONLY_LOCAL_ABSENT_OR_INVALID"
    assert pair["selected_pot_path"] is not None
    assert result["quality"]["request_supported_pair_count"] == 0
    assert result["quality"]["regulator_fallback_pair_count"] == 1


def test_common_contract_without_local_or_global_fails_loudly(workdir: Path, monkeypatch) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-O"])
    _mock_common_contract_without_any_valid_source(monkeypatch)
    regulator = workdir / "common-regulator"
    regulator.mkdir()
    with pytest.raises(WorkflowStageError) as caught:
        ProductionWorkflowStages().fit_request_spp(
            bundle,
            {"formula": "NaO"},
            WorkflowConfig(
                output_root=workdir,
                regulator_root=regulator,
                spp_artifact_contract="dmytro_gr_v1",
            ),
            workdir / "run",
        )
    assert caught.value.stage == "guidance_pair_coverage"
    assert caught.value.code == "GUIDANCE_PAIR_UNSUPPORTED"
    assert caught.value.details["unsupported_pairs"] == ["Na-O"]


def test_evidence_bundle_records_structure_pair_contributions(workdir: Path) -> None:
    record = _record("s1", 1, _cif(workdir, "s1", ["Na", "O"]))
    bundle = assemble_spp_evidence(retrieval=_retrieval([record]), required_pairs=["Na-Na", "Na-O", "O-O"])
    assert bundle.selected[0].species_pairs_contributed == ("Na-Na", "Na-O", "O-O")
    assert bundle.pair_structure_counts == {"Na-Na": 1, "Na-O": 1, "O-O": 1}
