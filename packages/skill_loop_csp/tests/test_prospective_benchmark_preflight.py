from __future__ import annotations

import json
import csv
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.bench.prospective import (
    FrozenReference,
    ProspectiveBenchmarkStages,
    assert_reference_safe_for_spp,
    audit_option1_pair_coverage,
    exclude_reference_equivalents,
)
from sok_llm_orchestrator.workflow.spp import REQUEST_MISSING, REQUEST_USABLE


TASKS = {
    "BaTiO3": {
        "formula": "BaTiO3",
        "family": "perovskite",
        "prototype": "perovskite",
        "space_group": "Pm-3m",
    },
    "CsPbCl3": {
        "formula": "CsPbCl3",
        "family": "halide perovskite",
        "prototype": "halide_perovskite_cspbcl3",
        "space_group": "Pm-3m",
    },
}


def _perovskite(*, shift: float = 0.0) -> Structure:
    return Structure(
        Lattice.cubic(4.0),
        ["Ba", "Ti", "O", "O", "O"],
        [[0, 0, 0], [.5, .5, .5], [.5 + shift, .5, 0], [.5, 0, .5], [0, .5, .5]],
    )


def _write(path: Path, structure: Structure) -> Path:
    structure.to(filename=path)
    return path


def _item(structure_id: str, rank: int, path: Path) -> dict:
    return {
        "structure_id": structure_id,
        "rank": rank,
        "score": 1.0 / rank,
        "cif_export": {"status": "exported", "path": str(path)},
    }


def _reference(root: Path) -> FrozenReference:
    path = _write(root / "reference.cif", _perovskite())
    return FrozenReference.from_cif(
        case_id="RDX-BATIO3",
        formula="BaTiO3",
        reference_id="reference-id",
        source_structure_id="mp-source",
        cif_path=path,
    )


def test_canonical_target_task_mappings_use_request_known_fields() -> None:
    mapping_path = Path(__file__).resolve().parents[1] / "artifacts" / "final_paper_benchmark_v2_preflight" / "CANONICAL_TARGET_TASKS.json"
    payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert set(payload["tasks"]) == {"BaTiO3", "CaTiO3", "SrTiO3", "CsPbBr3", "CsPbCl3", "CsPbI3", "CsSnBr3", "CsSnI3"}
    for formula, task in payload["tasks"].items():
        assert task["formula"] == formula
        assert set(task) == {"formula", "family", "prototype", "space_group"}
    stages = ProspectiveBenchmarkStages(tasks=payload["tasks"], reference=object())  # type: ignore[arg-type]
    task = stages.normalise("Generate CsPbCl3 as a halide perovskite")
    assert task == TASKS["CsPbCl3"]
    assert set(task) == {"formula", "family", "prototype", "space_group"}


def test_exact_reference_id_is_excluded_and_provenance_recorded() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        other = _write(root / "other.cif", _perovskite(shift=.18))
        result = exclude_reference_equivalents({"selected": [_item("reference-id", 7, other)]}, reference)
        assert result.retrieval["selected"] == []
        row = result.audit[0]
        assert row.reference_id_match and row.exclusion_checked
        assert row.retrieval_rank == 7 and row.exclusion_reason.startswith("reference_id_match")


def test_raw_duplicate_is_excluded() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        duplicate = root / "raw-copy.cif"
        duplicate.write_bytes(reference.cif_path.read_bytes())
        row = exclude_reference_equivalents({"selected": [_item("other-id", 1, duplicate)]}, reference).audit[0]
        assert row.raw_hash_match and not row.included_in_request_spp


def test_canonical_duplicate_is_excluded() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        duplicate = root / "canonical-copy.cif"
        duplicate.write_text("# reserialized\n" + reference.cif_path.read_text(encoding="utf-8"), encoding="utf-8")
        row = exclude_reference_equivalents({"selected": [_item("other-id", 1, duplicate)]}, reference).audit[0]
        assert not row.raw_hash_match
        assert row.canonical_hash_match


def test_structurematcher_equivalent_is_excluded() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        translated = _perovskite()
        translated.translate_sites(range(len(translated)), [0.123, 0.071, 0.037], frac_coords=True, to_unit_cell=True)
        path = _write(root / "translated.cif", translated)
        row = exclude_reference_equivalents({"selected": [_item("translated", 1, path)]}, reference).audit[0]
        assert not row.canonical_hash_match
        assert row.structurematcher_equivalent


def test_non_equivalent_same_formula_polymorph_remains_eligible() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        polymorph = _write(root / "polymorph.cif", _perovskite(shift=.24))
        result = exclude_reference_equivalents({"selected": [_item("polymorph", 3, polymorph)]}, reference)
        assert [row["structure_id"] for row in result.retrieval["selected"]] == ["polymorph"]
        row = result.audit[0]
        assert row.included_in_request_spp and row.exclusion_reason == "eligible_non_equivalent"


def test_excluded_structure_cannot_reenter_pair_expansion() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        eligible = _write(root / "eligible.cif", _perovskite(shift=.24))
        duplicate = root / "expansion-copy.cif"
        duplicate.write_bytes(reference.cif_path.read_bytes())
        retrieval = {
            "selected": [_item("eligible", 1, eligible)],
            "pair_coverage_expansion": {"corpus_id": "general", "selected": [_item("reentry", 1, duplicate)]},
        }
        result = exclude_reference_equivalents(retrieval, reference)
        assert result.retrieval["pair_coverage_expansion"]["selected"] == []
        assert any(row.retrieval_source == "pair_coverage_expansion" and row.raw_hash_match for row in result.audit)


def test_reference_exclusion_is_asserted_before_request_spp_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        reference = _reference(root)
        stages = ProspectiveBenchmarkStages(tasks=TASKS, reference=reference)
        eligible = _write(root / "eligible.cif", _perovskite(shift=.24))
        stages.last_exclusion = exclude_reference_equivalents({"selected": [_item("eligible", 1, eligible)]}, reference)
        evidence = SimpleNamespace(selected=(SimpleNamespace(structure_id="eligible"),))
        called = []
        monkeypatch.setattr(
            "sok_llm_orchestrator.workflow.runner.ProductionWorkflowStages.fit_request_spp",
            lambda self, evidence, task, config, run_root: called.append("fit") or {"ok": True},
        )
        assert stages.fit_request_spp(evidence, TASKS["BaTiO3"], object(), root) == {"ok": True}
        assert called == ["fit"]

        excluded = stages.last_exclusion.audit[0]
        stages.last_exclusion = type(stages.last_exclusion)(
            stages.last_exclusion.retrieval,
            (type(excluded)(
                structure_id="eligible", retrieval_rank=1, retrieval_source="primary", exclusion_checked=True,
                reference_id_match=True, raw_hash_match=False, canonical_hash_match=False,
                structurematcher_equivalent=False, included_in_request_spp=False, exclusion_reason="reference_id_match",
            ),),
            0,
        )
        with pytest.raises(RuntimeError, match="reference-equivalent evidence"):
            stages.fit_request_spp(evidence, TASKS["BaTiO3"], object(), root)
        assert called == ["fit"]


def test_assertion_rejects_nonzero_equivalent_count() -> None:
    with TemporaryDirectory() as directory:
        reference = _reference(Path(directory))
        result = exclude_reference_equivalents({"selected": []}, reference)
        unsafe = type(result)(result.retrieval, result.audit, 1)
        with pytest.raises(RuntimeError, match="reference-equivalent evidence"):
            assert_reference_safe_for_spp(SimpleNamespace(selected=()), unsafe)


def _artifact_rows(name: str) -> list[dict[str, str]]:
    path = Path(__file__).resolve().parents[1] / "artifacts" / "final_paper_benchmark_v2_preflight" / name
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_scaffold_independence_metadata_is_complete() -> None:
    rows = _artifact_rows("SCAFFOLD_INDEPENDENCE_AUDIT.csv")
    assert len(rows) == 8
    assert all(row["classification"] in {"GENERIC_FAMILY_SCAFFOLD", "REGISTERED_NON_TARGET_SCAFFOLD"} for row in rows)
    assert all(row["target_derived"] == "NO" for row in rows)


def test_eligibility_preflight_is_internally_consistent() -> None:
    final = _artifact_rows("FINAL_TARGET_ELIGIBILITY.csv")
    dry = {row["formula"]: row for row in _artifact_rows("DRY_RUN_RETRIEVAL_READINESS.csv")}
    assert len(final) == 8
    assert sum(row["independent_reference"] == "YES" for row in final) == 7
    sr = next(row for row in final if row["formula"] == "SrTiO3")
    assert sr["benchmark_eligible"] == "NO"
    assert sr["blocking_reason"] == "NO_INDEPENDENT_REFERENCE"
    for row in final:
        if row["benchmark_eligible"] == "YES":
            assert dry[row["formula"]]["canonical_evidence_assembly_usable"] == "YES"
            assert dry[row["formula"]]["reference_equivalent_evidence_count"] == "0"


def test_benchmark_v1_protected_hashes_are_unchanged() -> None:
    root = Path(__file__).resolve().parents[1] / "artifacts" / "final_paper_benchmark"
    expected = {
        "BENCHMARK_PROTOCOL.md": "67e14c94153f56086e200c99ed10634a3f601ee56e7db638db373ef194a13fd6",
        "BENCHMARK_CONFIG.json": "abb5c78b9d59ce50cf323495a551e04945fc8e39a34b925d352e8e4827a265b9",
        "BENCHMARK_TARGETS.csv": "6ebb38e8aff1350bd6ba2ad3298a5a547cbbbe63967cfb8135e6f0e774e42602",
        "BENCHMARK_FREEZE.json": "bb6404202f7fe76ac677da6049f6d2e0b540cfeaf63432f97b6f79624fad26d0",
    }
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in expected}
    assert actual == expected


def test_missing_local_pair_with_regulator_is_guidance_eligible() -> None:
    regulator = Path(__file__).resolve().parents[2] / "qlip" / "data" / "spp" / "regulators" / "icsd_broad_regulator_v1"
    coverage = audit_option1_pair_coverage(
        required_pairs=["Br-Pb"], local_pair_statuses={"Br-Pb": REQUEST_MISSING}, regulator_root=regulator,
    )
    assert coverage.unsupported_pair_count == 0
    assert coverage.locally_supported_pair_count == 0
    assert coverage.regulator_fallback_pair_count == 1
    assert coverage.rows[0].preflight_pair_mode == "LOCAL_SUPPORT_MISSING_REGULATOR_AVAILABLE"


def test_missing_local_pair_without_regulator_is_ineligible() -> None:
    with TemporaryDirectory() as directory:
        coverage = audit_option1_pair_coverage(
            required_pairs=["Br-Pb"], local_pair_statuses={"Br-Pb": REQUEST_MISSING}, regulator_root=Path(directory),
        )
    assert coverage.unsupported_pair_count == 1
    assert not coverage.rows[0].guidance_available
    assert coverage.rows[0].preflight_pair_mode == "UNSUPPORTED_REQUIRED_PAIR"


def test_partial_request_support_is_preserved_and_fallback_is_not_local() -> None:
    regulator = Path(__file__).resolve().parents[2] / "qlip" / "data" / "spp" / "regulators" / "icsd_broad_regulator_v1"
    coverage = audit_option1_pair_coverage(
        required_pairs=["Br-Cs", "Br-Pb"],
        local_pair_statuses={"Br-Cs": REQUEST_USABLE, "Br-Pb": REQUEST_MISSING},
        regulator_root=regulator,
    )
    assert coverage.locally_supported_pair_count == 1
    assert coverage.regulator_fallback_pair_count == 1
    assert coverage.local_support_fraction == 0.5
    assert coverage.unsupported_pair_count == 0


def test_result2_eligibility_and_result3_informativeness_are_separate() -> None:
    final = {row["formula"]: row for row in _artifact_rows("FINAL_TARGET_ELIGIBILITY.csv")}
    result3 = {row["formula"]: row for row in _artifact_rows("RESULT_3_READINESS.csv")}
    assert final["CsPbBr3"]["benchmark_eligible"] == "YES"
    assert int(final["CsPbBr3"]["regulator_fallback_pair_count"]) > 0
    assert result3["CsPbBr3"]["RESULT_3_ELIGIBLE"] == "YES"
    assert result3["CsPbBr3"]["RESULT_3_INFORMATIVENESS"] in {"HIGH", "MEDIUM"}
