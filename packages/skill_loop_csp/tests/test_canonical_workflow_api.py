from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from pymatgen.core import Lattice, Structure
import numpy as np
import pytest
from spp_maker.fit_hist import HistAccumulator, make_uniform_binning
from spp_maker.fit_phi import build_phi_from_hist

from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    run_csp_workflow,
)


class FakeStages:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []
        self.request_pot_root = root / "qlip-runtime" / "runs" / "mock-run" / "request_spp" / "supported_pairs"
        self.regulator_root = root / "qlip-data" / "regulators" / "mock-regulator"
        self.request_pot_root.mkdir(parents=True)
        self.regulator_root.mkdir(parents=True)
        self.evidence_cif = root / "retrieved.cif"
        Structure(Lattice.cubic(4), ["Ba", "Ti", "O", "O", "O"], [[0, 0, 0], [.5, .5, .5], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]]).to(filename=self.evidence_cif)

    def normalise(self, request):
        self.calls.append("normalise")
        return {"formula": "BaTiO3", "family": "perovskite", "prototype": "perovskite", "space_group": "Pm-3m"}

    def retrieve(self, request, task, config, run_root):
        self.calls.append("retrieve")
        digest = hashlib.sha256(b"db").hexdigest()
        return {"corpus": {"corpus_id": "general", "database": str(self.root / "general.db"), "hash": digest}, "backend": "crystal_db.retrieval.text_search", "config": {"model_name": "text-embedding-bge-m3"}, "selected": [{"structure_id": "mp-test", "rank": 1, "score": .9, "cif_export": {"status": "exported", "path": str(self.evidence_cif)}}]}

    def fit_request_spp(self, evidence, task, config, run_root):
        self.calls.append("fit_request_spp")
        self.evidence_ids = tuple(item.structure_id for item in evidence.selected)
        return {
            "pot_root": self.request_pot_root,
            "artifact": str(self.request_pot_root.parent),
            "request_spp_run_id": "mock-run",
            "request_spp_logical_id": "request_spp:mock-run",
            "request_spp_hashes": {},
            "regulator_id": "mock-regulator",
            "regulator_root": self.regulator_root,
            "regulator_hash": "reg-hash",
            "quality": {"status": "PASS"},
        }

    def solve(self, task, request_spp, config, run_root):
        self.calls.append("solve")
        cif = self.root / "generated.cif"
        cif.write_bytes(self.evidence_cif.read_bytes())
        components = SimpleNamespace(request_spp_score=1.25, regulator_spp_score=2.5, solver_objective=62.5)
        return {
            "scaffold_id": "canonical_perovskite",
            "status": "OPTIMAL",
            "solver_objective": 62.5,
            "components": components,
            "cif_path": cif,
            "regulator_root": self.regulator_root,
            "regulator_hash": "reg-hash",
            "qlip_allowed_roots": [str(self.request_pot_root.parents[3]), str(self.regulator_root.parents[1])],
            "pot_authorization_status": "PASS",
            "difference": 0.0,
        }

    def evaluate(self, cif_path, task):
        assert cif_path.is_file()
        assert "solve" in self.calls
        self.calls.append("evaluate")
        return {"parse_ok": True, "detected_space_group": "Pm-3m", "min_distance": 2.0}


def _run(workdir: Path):
    stages = FakeStages(workdir)
    result = run_csp_workflow("BaTiO3", WorkflowConfig(output_root=workdir / "run", stages=stages))
    return result, stages


def test_run_csp_workflow_uses_corpus_router(workdir: Path, monkeypatch) -> None:
    seen = {}
    database = workdir / "general.db"; database.write_bytes(b"db")
    monkeypatch.setattr("sok_llm_orchestrator.workflow.runner.route_corpus", lambda request, formula, registry_path=None: seen.setdefault("route", SimpleNamespace(corpus_id="general", database=database)))
    monkeypatch.setattr("crystal_db.retrieval.text_search", lambda **kwargs: {"status": "ok", "query": {}, "neighbors": []})
    ProductionWorkflowStages().retrieve("BaTiO3", {"formula": "BaTiO3"}, WorkflowConfig(output_root=workdir), workdir / "run")
    assert seen["route"].corpus_id == "general"


def test_run_csp_workflow_uses_crystaldb_text_search(workdir: Path, monkeypatch) -> None:
    database = workdir / "general.db"; database.write_bytes(b"db")
    monkeypatch.setattr("sok_llm_orchestrator.workflow.runner.route_corpus", lambda *args, **kwargs: SimpleNamespace(corpus_id="general", database=database))
    called = {}
    def fake_text_search(**kwargs):
        called["kwargs"] = kwargs
        return {"status": "ok", "query": {}, "neighbors": []}
    monkeypatch.setattr("crystal_db.retrieval.text_search", fake_text_search)
    result = ProductionWorkflowStages().retrieve("BaTiO3", {"formula": "BaTiO3"}, WorkflowConfig(output_root=workdir), workdir / "run")
    assert called["kwargs"]["db_path"] == str(database)
    assert result["backend"] == "crystal_db.retrieval.text_search"


def test_run_csp_workflow_retrieval_ids_feed_spp_evidence(workdir: Path) -> None:
    result, stages = _run(workdir)
    assert result.spp_evidence_ids == ("mp-test",)
    assert stages.evidence_ids == result.spp_evidence_ids


def test_run_csp_workflow_request_and_regulator_both_active(workdir: Path) -> None:
    result, _ = _run(workdir)
    assert result.request_component != 0
    assert result.regulator_component != 0
    assert result.combined_objective == 10.0 * (result.request_component + 2.0 * result.regulator_component)


def test_run_csp_workflow_solver_objective_parity(workdir: Path) -> None:
    result, _ = _run(workdir)
    assert result.solver_objective == result.independent_objective
    assert result.objective_difference == 0.0


def test_run_csp_workflow_sca_is_post_generation(workdir: Path) -> None:
    _, stages = _run(workdir)
    assert stages.calls.index("evaluate") > stages.calls.index("solve")


def test_installed_sca_validates_generated_cif(workdir: Path) -> None:
    cif = workdir / "generated.cif"
    Structure(Lattice.cubic(4), ["Ba", "Ti", "O", "O", "O"], [[0, 0, 0], [.5, .5, .5], [.5, .5, 0], [.5, 0, .5], [0, .5, .5]]).to(filename=cif)

    result = ProductionWorkflowStages().evaluate(
        cif,
        {"formula": "BaTiO3", "space_group": "Pm-3m"},
    )

    assert result["parse_ok"] is True
    assert result["target_formula_match"] is True
    assert result["detected_space_group"] == "Pm-3m"
    assert result["geometry_ok"] is True


def test_run_csp_workflow_returns_provenance(workdir: Path) -> None:
    result, _ = _run(workdir)
    assert result.provenance_manifest["api"].endswith("run_csp_workflow")
    assert result.provenance_manifest["sca_post_generation"] is True
    assert result.sca_result["parse_ok"] is True
    assert result.sca_result["detected_space_group"] == "Pm-3m"


def test_sca_failure_preserves_completed_solver_objective_and_cif_provenance(workdir: Path) -> None:
    class FailingSCAStages(FakeStages):
        def evaluate(self, cif_path, task):
            assert cif_path.is_file()
            self.calls.append("evaluate")
            raise RuntimeError("deliberate SCA failure")

    stages = FailingSCAStages(workdir)
    trace_path = workdir / "failed_sca_trace.json"
    with pytest.raises(RuntimeError, match="deliberate SCA failure"):
        run_csp_workflow(
            "BaTiO3",
            WorkflowConfig(output_root=workdir / "run", trace_path=trace_path, stages=stages),
        )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace["workflow_status"] == "FAILED_CONTROLLED"
    assert trace["failure_stage"] == "sca"
    assert trace["failure_code"] == "RuntimeError"
    assert trace["failure_message"] == "deliberate SCA failure"
    assert trace["solver_status"] == "OPTIMAL"
    assert trace["solver_objective"] == 62.5
    assert trace["independent_objective"] == 62.5
    assert trace["objective_difference"] == 0.0
    assert trace["objective_parity"] == "PASS"
    assert trace["CIF_generated"] is True
    assert Path(trace["CIF_path"]).is_file()
    assert trace["CIF_hash"]
    assert trace["SCA_status"] == "NOT_REACHED"


def test_successful_solve_trace_exposes_required_path_provenance(workdir: Path) -> None:
    stages = FakeStages(workdir)
    trace_path = workdir / "trace.json"
    run_csp_workflow(
        "BaTiO3",
        WorkflowConfig(output_root=workdir / "run", trace_path=trace_path, stages=stages),
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8"))

    assert trace["qlip_allowed_roots"] == [
        str(stages.request_pot_root.parents[3]),
        str(stages.regulator_root.parents[1]),
    ]
    assert trace["request_spp_root"] == str(stages.request_pot_root)
    assert trace["regulator_root"] == str(stages.regulator_root)
    assert trace["pot_authorization_status"] == "PASS"
    assert "C:\\Users\\brown" not in json.dumps(trace["qlip_allowed_roots"])


def test_canonical_spp_convention_is_supported_and_preferred_distance_is_lower() -> None:
    config = WorkflowConfig(output_root=Path("unused"))
    assert config.request_spp_convention == "reward"
    assert config.request_spp_convention in {"reward", "penalty"}
    hist = HistAccumulator(binning=make_uniform_binning(d_min=0.0, d_max=3.0, bin_width=1.0), counts={}, total_pairs_seen=0, total_weighted_pairs_seen=0.0)
    hist.add_sample("Ba", "O", 1.5, 9.0)
    hist.add_sample("Ba", "O", 2.5, 1.0)
    phi = build_phi_from_hist(hist, alpha=1e-3, shifted=True)
    assert np.argmin(phi.phi[0]) == 1
    assert phi.phi[0, 1] < phi.phi[0, 2]


def test_workflow_config_defaults_to_native_cell_mode() -> None:
    config = WorkflowConfig(output_root=Path("unused"))
    assert config.cell_mode == "native"
    assert config.cell_volume_per_atom is None


def test_workflow_config_rejects_unknown_cell_mode() -> None:
    with pytest.raises(ValueError, match="cell_mode"):
        WorkflowConfig(output_root=Path("unused"), native_qlip=True, scaffold_mode="none", cell_mode="reference_derived")


def test_workflow_config_non_native_cell_mode_requires_native_qlip() -> None:
    with pytest.raises(ValueError, match="native_qlip"):
        WorkflowConfig(output_root=Path("unused"), native_qlip=False, cell_mode="composition_scaled")


def test_workflow_config_native_cell_mode_rejects_vpa_override() -> None:
    with pytest.raises(ValueError, match="cell_volume_per_atom"):
        WorkflowConfig(output_root=Path("unused"), native_qlip=True, scaffold_mode="none", cell_mode="native", cell_volume_per_atom=15.0)


def test_workflow_config_composition_scaled_accepts_explicit_vpa_override() -> None:
    config = WorkflowConfig(
        output_root=Path("unused"), native_qlip=True, scaffold_mode="none",
        cell_mode="composition_scaled", cell_volume_per_atom=15.0,
    )
    assert config.cell_volume_per_atom == 15.0
