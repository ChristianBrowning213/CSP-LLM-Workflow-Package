from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.bench.prospective import FrozenReference
from sok_llm_orchestrator.workflow.runner import WorkflowStageError


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_experiment_table.py"
SPEC = importlib.util.spec_from_file_location("_test_run_experiment_table_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def work_path() -> Path:
    parent = Path.cwd() / "test_workdir" / "experiment_table_runner"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as temporary:
        yield Path(temporary)


def write_table(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(MODULE.REQUIRED_COLUMNS + MODULE.OPTIONAL_COLUMNS)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def row(row_id: str = "test_001", **overrides: str) -> dict[str, str]:
    value = {
        "row_id": row_id, "formula": "BaTiO3",
        "request": "Find a plausible BaTiO3 perovskite structure",
        "scaffold_mode": "minimal", "request_spp_mode": "enabled",
        "experiment_block": "BREADTH", "family": "perovskite", "corpus": "",
        "reference_id": "", "repeat_group": "", "repeat_index": "", "run_sca": "yes",
        "run_chgnet": "yes", "enabled": "yes", "notes": "fixture",
    }
    value.update(overrides)
    return value


class FakeResult(SimpleNamespace):
    def to_dict(self):
        return dict(self.__dict__)


def fake_result(config, *, sca: dict | None = None) -> FakeResult:
    attempt = Path(config.output_root) / "attempts" / "attempt-001"
    attempt.mkdir(parents=True, exist_ok=True)
    structure = Structure(
        Lattice.cubic(4.0), ["Ba", "Ti", "O", "O", "O"],
        [(0, 0, 0), (0.5, 0.5, 0.5), (0.5, 0.5, 0), (0.5, 0, 0.5), (0, 0.5, 0.5)],
    )
    cif = attempt / "generated.cif"
    structure.to(filename=cif)
    (attempt / "workflow_trace.json").write_text('{"workflow_status":"PASS"}\n', encoding="utf-8")
    (attempt / "attempt_manifest.json").write_text('{"status":"COMPLETED"}\n', encoding="utf-8")
    sca_payload = sca or {
        "parse_ok": True, "pre_dft_valid": True, "geometry_ok": True,
        "geometry_warning_count": 0, "min_distance": 2.0, "min_distance_pair": "Ti-O",
        "num_bad_contacts": 0, "bond_lengths_reasonable": True, "bond_reasonableness_score": 1.0,
        "chemical_species_valid": True, "target_formula_match": True,
        "space_group_consistent": True, "multiplicity_checked": False,
        "multiplicity_consistent": None, "error_type": None, "error_message": None,
    }
    return FakeResult(
        run_id="run-001", attempt_id="attempt-001", attempt_workspace=str(attempt),
        generated_cif_path=str(cif), generated_cif_hash="cif-hash", feasible_state_count=20,
        corpus_id="mp_stable_10k_v1", corpus_hash="corpus-hash", retrieved_ids=("mp-one", "mp-two"),
        request_spp_quality={"request_pair_results": [
            {"species_pair": "Ba-O", "request_pair_status": "REQUEST_USABLE", "guidance_mode": "REQUEST_PLUS_REGULATOR"},
            {"species_pair": "O-O", "request_pair_status": "REQUEST_MISSING", "guidance_mode": "REGULATOR_ONLY_REQUEST_MISSING"},
        ]},
        solver_status="OPTIMAL", solver_objective=-12.0, independent_objective=-12.0,
        objective_difference=0.0, sca_result=sca_payload,
    )


def test_csv_row_parses_to_canonical_request_and_config(work_path: Path) -> None:
    table = work_path / "rows.csv"
    write_table(table, [row(retrieval_depth="12")])
    parsed = MODULE.parse_experiment_table(table)
    assert len(parsed) == 1 and parsed[0].errors == []
    config = MODULE.build_workflow_config(parsed[0], work_path / "out")
    assert parsed[0].formula == "BaTiO3"
    assert parsed[0].request.startswith("Find a plausible BaTiO3")
    assert config.retrieval_depth == 12
    assert parsed[0].resolved_corpus == "mp_stable_10k_v1"


@pytest.mark.parametrize("mode", ["tight", "loose", "minimal"])
def test_scaffold_mode_mapping(mode: str, work_path: Path) -> None:
    table = work_path / f"{mode}.csv"
    write_table(table, [row(scaffold_mode=mode)])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert MODULE.build_workflow_config(parsed, work_path / "out").scaffold_mode == mode


def test_cli_scaffold_selection_absent_is_native_and_directory_is_explicit(work_path: Path) -> None:
    table = work_path / "native.csv"
    write_table(table, [row(scaffold_mode="none")])
    parsed = MODULE.parse_experiment_table(table)[0]
    native = MODULE.build_workflow_config(parsed, work_path / "native-out", scaffolds=None)
    assert native.native_qlip is True
    assert native.scaffold_dir is None
    assert native.scaffold_mode == "none"
    hard_dir = Path(__file__).resolve().parents[1] / "experiments" / "scaffold_ablation" / "scaffolds" / "hard"
    hard = MODULE.build_workflow_config(parsed, work_path / "hard-out", scaffolds=hard_dir)
    assert hard.native_qlip is False
    assert hard.scaffold_dir == hard_dir.resolve()
    assert hard.scaffold_mode == "hard"


def test_cell_mode_defaults_to_native(work_path: Path) -> None:
    table = work_path / "cell_default.csv"
    write_table(table, [row(scaffold_mode="none")])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert parsed.cell_mode == "native"
    config = MODULE.build_workflow_config(parsed, work_path / "out", scaffolds=None)
    assert config.cell_mode == "native"
    assert config.cell_volume_per_atom is None


@pytest.mark.parametrize("mode", ["native", "composition_scaled", "retrieval_derived"])
def test_cell_mode_round_trips_into_workflow_config_for_native_qlip_rows(mode: str, work_path: Path) -> None:
    table = work_path / f"cell_{mode}.csv"
    write_table(table, [row(scaffold_mode="none", cell_mode=mode)])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert parsed.errors == []
    config = MODULE.build_workflow_config(parsed, work_path / "out", scaffolds=None)
    assert config.cell_mode == mode


def test_unknown_cell_mode_is_a_row_level_error_not_a_crash(work_path: Path) -> None:
    table = work_path / "cell_bad.csv"
    write_table(table, [row(scaffold_mode="none", cell_mode="reference_derived")])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert any("cell_mode" in error for error in parsed.errors)


def test_cell_volume_per_atom_override_rejected_for_native_cell_mode(work_path: Path) -> None:
    table = work_path / "cell_native_override.csv"
    write_table(table, [row(scaffold_mode="none", cell_mode="native", cell_volume_per_atom="15.0")])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert any("cell_volume_per_atom" in error for error in parsed.errors)


def test_cell_volume_per_atom_override_round_trips_for_composition_scaled(work_path: Path) -> None:
    table = work_path / "cell_override.csv"
    write_table(table, [row(scaffold_mode="none", cell_mode="composition_scaled", cell_volume_per_atom="15.0")])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert parsed.errors == []
    config = MODULE.build_workflow_config(parsed, work_path / "out", scaffolds=None)
    assert config.cell_volume_per_atom == 15.0


@pytest.mark.parametrize("mode", ["enabled", "disabled"])
def test_request_spp_mode_mapping(mode: str, work_path: Path) -> None:
    table = work_path / f"{mode}.csv"
    write_table(table, [row(request_spp_mode=mode)])
    parsed = MODULE.parse_experiment_table(table)[0]
    assert MODULE.build_workflow_config(parsed, work_path / "out").request_spp_mode == mode


def test_one_input_row_produces_one_result_row_and_calls_canonical_api(work_path: Path, monkeypatch) -> None:
    table = work_path / "one.csv"
    write_table(table, [row()])
    calls = []

    def canonical(request, config):
        calls.append((request, config))
        return fake_result(config)

    monkeypatch.setattr(MODULE, "run_csp_workflow", canonical)
    report = MODULE.execute_table(table, output_root=work_path / "results")
    assert len(calls) == 1
    assert len(report.result_rows) == 1
    results = list(csv.DictReader((report.output_root / "RESULTS.csv").open(encoding="utf-8")))
    assert len(results) == 1 and results[0]["row_id"] == "test_001"
    assert results[0]["experiment_block"] == "BREADTH"
    assert results[0]["family"] == "perovskite"
    assert results[0]["run_sca"] == "YES"
    assert results[0]["run_chgnet"] == "YES"
    assert results[0]["chgnet_status"] == "PENDING_EXTERNAL_QC"
    for name in ("input.json", "result.json", "result.txt", "generated.cif", "sca.json", "workflow_trace.json", "attempt_manifest.json"):
        assert (report.output_root / "rows" / "test_001" / name).is_file()


def test_controlled_workflow_failure_remains_a_result_row(work_path: Path) -> None:
    table = work_path / "failure.csv"
    write_table(table, [row()])

    def controlled(request, config):
        raise WorkflowStageError("representability", "NOT_REPRESENTABLE", "controlled fixture")

    report = MODULE.execute_table(table, output_root=work_path / "results", workflow_fn=controlled)
    assert len(report.result_rows) == 1
    assert report.result_rows[0]["workflow_status"] == "CONTROLLED_WORKFLOW_FAILURE"
    assert report.result_rows[0]["failure_stage"] == "representability"
    assert report.result_rows[0]["failure_code"] == "NOT_REPRESENTABLE"


def test_sca_fields_are_propagated_without_a_new_scalar_score(work_path: Path) -> None:
    table = work_path / "sca.csv"
    write_table(table, [row()])
    sca = {
        "parse_ok": True, "pre_dft_valid": False, "geometry_ok": False,
        "geometry_warning_count": 2, "min_distance": 0.8, "min_distance_pair": "Ti-O",
        "num_bad_contacts": 3, "bond_lengths_reasonable": False, "bond_reasonableness_score": 0.25,
        "chemical_species_valid": True, "target_formula_match": True,
        "space_group_consistent": False, "multiplicity_checked": True,
        "multiplicity_consistent": False, "error_type": None, "error_message": None,
    }
    report = MODULE.execute_table(table, output_root=work_path / "results", workflow_fn=lambda request, config: fake_result(config, sca=sca))
    result = report.result_rows[0]
    assert result["sca_status"] == "PARTIAL"
    assert result["sca_geometry_status"] == "FAIL"
    assert result["sca_min_distance"] == 0.8
    assert result["sca_num_bad_contacts"] == 3
    assert "geometry_ok" in result["sca_failed_check_names"]
    assert "sca_realism_score" not in result


def test_reference_fields_are_propagated(work_path: Path, monkeypatch) -> None:
    table = work_path / "reference.csv"
    write_table(table, [row(reference_id="reference-001")])
    reference_path = work_path / "heldout.cif"
    Structure(
        Lattice.cubic(4.0), ["Ba", "Ti", "O", "O", "O"],
        [(0, 0, 0), (0.5, 0.5, 0.5), (0.5, 0.5, 0), (0.5, 0, 0.5), (0, 0.5, 0.5)],
    ).to(filename=reference_path)
    reference = FrozenReference.from_cif(
        case_id="test_001", formula="BaTiO3", reference_id="reference-001",
        source_structure_id="source-001", cif_path=reference_path,
    )
    monkeypatch.setattr(MODULE, "resolve_reference", lambda experiment_row, row_dir: reference)
    report = MODULE.execute_table(table, output_root=work_path / "results", workflow_fn=lambda request, config: fake_result(config))
    result = report.result_rows[0]
    assert result["reference_id"] == "reference-001"
    assert result["reference_match"] == "YES"
    assert result["space_group_match"] == "YES"
    assert result["crystal_system_match"] == "YES"
    assert result["volume_error_percent"] == pytest.approx(0.0)


def test_dry_run_performs_no_solve_and_reports_resolved_scaffold(work_path: Path, monkeypatch) -> None:
    table = work_path / "dry.csv"
    write_table(table, [row(request_spp_mode="disabled")])
    monkeypatch.setattr(MODULE, "run_csp_workflow", lambda *args, **kwargs: pytest.fail("solve called during dry run"))
    report = MODULE.execute_table(table, output_root=work_path / "results", dry_run=True)
    result = report.result_rows[0]
    assert result["workflow_status"] == "DRY_RUN_READY"
    assert result["feasible_state_count"] == 20
    input_payload = json.loads((report.output_root / "rows" / "test_001" / "input.json").read_text(encoding="utf-8"))
    assert input_payload["row"]["resolved_scaffold"] == "abx3_five_site_minimal_assignment_v1"


def test_malformed_row_is_row_input_error_without_calling_workflow(work_path: Path) -> None:
    table = work_path / "bad.csv"
    write_table(table, [row(scaffold_mode="experiment_special_case")])
    report = MODULE.execute_table(
        table, output_root=work_path / "results",
        workflow_fn=lambda *args, **kwargs: pytest.fail("workflow called for malformed row"),
    )
    assert len(report.result_rows) == 1
    assert report.result_rows[0]["workflow_status"] == "ROW_INPUT_ERROR"


def test_failures_do_not_omit_later_rows(work_path: Path) -> None:
    table = work_path / "continue.csv"
    write_table(table, [row("fails"), row("continues")])
    calls = []

    def workflow(request, config):
        calls.append(request)
        if len(calls) == 1:
            raise RuntimeError("fixture software failure")
        return fake_result(config)

    report = MODULE.execute_table(table, output_root=work_path / "results", workflow_fn=workflow)
    assert [item["row_id"] for item in report.result_rows] == ["fails", "continues"]
    assert report.result_rows[0]["workflow_status"] == "SOFTWARE_FAILURE"
    assert report.result_rows[1]["workflow_status"] == "PASS"
    assert report.software_failure is True


def test_reuse_frozen_row_validates_one_source_record_without_calling_workflow(work_path: Path) -> None:
    source = work_path / "frozen.csv"
    source.write_text("source_id,status\nU-001,PASS\n", encoding="utf-8")
    table = work_path / "reuse.csv"
    write_table(table, [row(
        "breadth_001", formula="NiO",
        request="Generate a rocksalt nickel oxide structure using retrieved oxide evidence.",
        execution_mode="reuse_frozen", source_artifact=str(source),
        source_artifact_key="source_id=U-001",
    )])
    dry_report = MODULE.execute_table(table, output_root=work_path / "dry", dry_run=True)
    assert dry_report.result_rows[0]["workflow_status"] == "DRY_RUN_REUSE_READY"
    report = MODULE.execute_table(
        table, output_root=work_path / "results",
        workflow_fn=lambda *args, **kwargs: pytest.fail("canonical workflow called for frozen reuse"),
    )
    result = report.result_rows[0]
    assert result["workflow_status"] == "REUSED_FROZEN_RESULT"
    assert result["source_artifact_hash"]
    detail = json.loads((report.output_root / "rows" / "breadth_001" / "result.json").read_text(encoding="utf-8"))
    assert detail["selected_source_record"] == {"source_id": "U-001", "status": "PASS"}


def test_resume_retries_only_software_failures_and_rebuilds_all_rows(work_path: Path) -> None:
    table = work_path / "resume.csv"
    write_table(table, [row("failed"), row("complete")])
    calls = []

    def first_workflow(request, config):
        calls.append(request)
        if len(calls) == 1:
            raise RuntimeError("retry me")
        return fake_result(config)

    first = MODULE.execute_table(table, output_root=work_path / "results", workflow_fn=first_workflow)
    assert [item["workflow_status"] for item in first.result_rows] == ["SOFTWARE_FAILURE", "PASS"]
    retry_calls = []

    def retry_workflow(request, config):
        retry_calls.append(request)
        return fake_result(config)

    resumed = MODULE.execute_table(
        table, output_root=work_path / "results", resume=True, workflow_fn=retry_workflow,
    )
    assert len(retry_calls) == 1
    assert [item["row_id"] for item in resumed.result_rows] == ["failed", "complete"]
    assert [item["workflow_status"] for item in resumed.result_rows] == ["PASS", "PASS"]


def test_runner_contains_no_experiment_specific_scientific_branch() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "run_csp_workflow" in source
    for formula in ("BaTiO3", "CaTiO3", "CsPbBr3", "Na3Zr2Si2PO12"):
        assert formula not in source
