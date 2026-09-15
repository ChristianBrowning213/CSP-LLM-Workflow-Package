from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from sok_llm_orchestrator.retrieval.corpus_router import route_corpus
from sok_llm_orchestrator.workflow.evidence import assemble_spp_evidence
from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages, WorkflowConfig, WorkflowStageError, run_csp_workflow


def _cif(path: Path, species: list[str]) -> Path:
    Structure(Lattice.cubic(8), species, [[i / len(species)] * 3 for i in range(len(species))]).to(filename=path)
    return path


def _record(path: Path, structure_id: str = "allowed") -> dict:
    return {"structure_id": structure_id, "rank": 1, "score": 1.0, "cif_export": {"status": "exported", "path": str(path)}}


def test_partial_local_evidence_records_missing_pair_without_exception() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        bundle = assemble_spp_evidence(
            retrieval={"corpus": {"corpus_id": "fixture", "hash": "h"}, "selected": [_record(_cif(root / "one.cif", ["Na"]))]},
            required_pairs=["Na-Na", "Na-O"], allow_partial_pair_coverage=True,
        )
        assert bundle.pair_structure_counts == {"Na-Na": 1, "Na-O": 0}
        assert bundle.pair_evidence_status["Na-O"]["local_evidence_present"] is False


def test_excluded_reference_does_not_reenter_partial_pair_expansion() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        held = _record(_cif(root / "held.cif", ["Na", "O"]), "held")
        retrieval = {"corpus": {"corpus_id": "fixture", "hash": "h"}, "selected": [], "pair_coverage_expansion": {"corpus_id": "fixture", "selected": [held]}}
        bundle = assemble_spp_evidence(retrieval=retrieval, required_pairs=["Na-O"], excluded_structure_ids=["held"], allow_partial_pair_coverage=True)
        assert bundle.selected == ()
        assert bundle.pair_structure_counts["Na-O"] == 0


@pytest.mark.parametrize("formula,roles", [
    ("BaTiO3", {"A": "Ba", "B": "Ti", "X": "O"}),
    ("CaTiO3", {"A": "Ca", "B": "Ti", "X": "O"}),
    ("CsPbBr3", {"A": "Cs", "B": "Pb", "X": "Br"}),
    ("CsPbCl3", {"A": "Cs", "B": "Pb", "X": "Cl"}),
    ("CsPbI3", {"A": "Cs", "B": "Pb", "X": "I"}),
    ("CsSnBr3", {"A": "Cs", "B": "Sn", "X": "Br"}),
    ("CsSnI3", {"A": "Cs", "B": "Sn", "X": "I"}),
])
def test_explicit_abx3_roles_drive_tight_and_loose_scaffolds(formula: str, roles: dict[str, str]) -> None:
    stages = ProductionWorkflowStages()
    task = stages.normalise(formula)
    assert task["roles"] == roles
    tight_id, tight, tight_orbits = stages._scaffold(task, WorkflowConfig(output_root=Path("."), scaffold_mode="tight"))
    loose_id, loose, loose_orbits = stages._scaffold(task, WorkflowConfig(output_root=Path("."), scaffold_mode="loose"))
    assert tight_id.endswith("_tight") and loose_id == "cubic_perovskite_variable_cation_v1"
    for structure, orbits in ((tight, tight_orbits), (loose, loose_orbits)):
        assert set(str(site.specie) for site in structure) == set(roles.values())
        assert all(roles["X"] in orbit["allowed_species"] for index, orbit in enumerate(orbits) if str(structure[index].specie) == roles["X"])
    assert all(len(orbit["allowed_species"]) == 1 for orbit in tight_orbits)
    assert sum(len(orbit["allowed_species"]) == 2 for orbit in loose_orbits) == 2


class _FactorialStages:
    def __init__(self, root: Path):
        self.root = root
        self.source = _cif(root / "source.cif", ["Ba", "Ti", "O", "O", "O"])
        self.production = ProductionWorkflowStages()

    def normalise(self, request): return self.production.normalise(request)
    def required_pairs(self, task, config): return ["Ba-O"]
    def retrieve(self, request, task, config, run_root):
        return {"corpus": {"corpus_id": "fixture", "database": str(self.source), "hash": hashlib.sha256(self.source.read_bytes()).hexdigest()}, "backend": "fixture", "config": {}, "selected": [_record(self.source)]}
    def fit_request_spp(self, evidence, task, config, run_root):
        status = "REQUEST_DISABLED" if config.request_spp_mode == "disabled" else "REQUEST_USABLE"
        mode = "REGULATOR_ONLY_REQUEST_DISABLED" if config.request_spp_mode == "disabled" else "REQUEST_PLUS_REGULATOR"
        pot = self.root / "pot"; reg = self.root / "reg"; pot.mkdir(exist_ok=True); reg.mkdir(exist_ok=True)
        return {"pot_root": pot, "artifact": pot, "request_spp_run_id": run_root.name, "request_spp_hashes": {}, "regulator_root": reg, "regulator_id": "fixture", "regulator_hash": "r", "quality": {"status": "PASS", "request_pair_results": [{"species_pair": "Ba-O", "request_pair_status": status, "guidance_mode": mode}], "request_supported_pair_count": int(config.request_spp_mode == "enabled"), "regulator_fallback_pair_count": int(config.request_spp_mode == "disabled"), "unsupported_pair_count": 0}}
    def solve(self, task, request_spp, config, run_root):
        scaffold_id, _, _ = self.production._scaffold(task, config)
        cif = run_root / "generated.cif"; cif.write_bytes(self.source.read_bytes())
        request_score = 1.0 if config.request_spp_mode == "enabled" else 0.0
        components = SimpleNamespace(request_spp_score=request_score, regulator_spp_score=2.0, solver_objective=10 * (request_score + 4.0), pair_components=())
        return {"scaffold_id": scaffold_id, "feasible_state_count": 1 if config.scaffold_mode == "tight" else 2, "status": "OPTIMAL", "solver_objective": components.solver_objective, "components": components, "cif_path": cif, "regulator_root": request_spp["regulator_root"], "regulator_hash": "r", "qlip_allowed_roots": [], "pot_authorization_status": "PASS", "difference": 0.0}
    def evaluate(self, cif_path, task): return {"parse_ok": True}


@pytest.mark.parametrize("scaffold_mode,request_spp_mode,states", [("tight", "disabled", 1), ("tight", "enabled", 1), ("loose", "disabled", 2), ("loose", "enabled", 2)])
def test_all_factorial_controls_execute_through_canonical_entrypoint(scaffold_mode: str, request_spp_mode: str, states: int) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory); stages = _FactorialStages(root)
        result = run_csp_workflow("BaTiO3", WorkflowConfig(output_root=root / f"{scaffold_mode}-{request_spp_mode}", scaffold_mode=scaffold_mode, request_spp_mode=request_spp_mode, stages=stages))
        assert result.scaffold_mode == scaffold_mode and result.feasible_state_count == states
        assert (result.request_component == 0) is (request_spp_mode == "disabled")


def test_all_six_nasicon_cases_normalise_and_route_specialist() -> None:
    requests = [
        "RDX-E4-A2 Na3Zr2Si2PO12 C2", "RDX-E4-C2 Na3Ti2(PO4)3 R-3", "RDX-E4-F1 LiZr2(PO4)3 R-3c",
        "RDX-NEG-E4-A1 Na3Zr2Si2PO12 R-3c", "RDX-NEG-E4-A3 Na3Ti2Si2PO12 R-3", "RDX-NEG-E4-A4 Na3Hf2Si2PO12 R-3",
    ]
    stages = ProductionWorkflowStages()
    for request in requests:
        task = stages.normalise(request)
        route = route_corpus(request, formula=task["formula"])
        assert route.corpus_id == "nasicon_specialist_v3"
    for request in requests[:3]:
        task = stages.normalise(request)
        stages._scaffold(task, WorkflowConfig(output_root=Path(".")))
    for request in requests[3:]:
        task = stages.normalise(request)
        with pytest.raises(WorkflowStageError) as caught:
            stages._scaffold(task, WorkflowConfig(output_root=Path(".")))
        assert caught.value.stage == "representability"
