from __future__ import annotations

import importlib
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from sok_llm_orchestrator.workflow.runner import (
    ProductionWorkflowStages,
    WorkflowConfig,
    WorkflowStageError,
    _request_spp_run_id,
    _solver_pair_guidance,
    _tree_hash,
)
from sok_llm_orchestrator.workflow.spp import (
    REQUEST_INSUFFICIENT,
    REQUEST_MISSING,
    REQUEST_USABLE,
    classify_request_pair_quality,
    compile_spp_components,
    guidance_mode_for_pair,
    request_support_status,
    score_spp_components,
)


def _pot(root: Path, pair: str, scale: float) -> None:
    folder = root / pair.upper()
    folder.mkdir(parents=True, exist_ok=True)
    rows = ["spline cubic reverse", f"{pair} 0.0 11.0"]
    rows.extend(f"{distance:.3f} {scale * distance:.8f}" for distance in np.linspace(0.0, 11.0, 221))
    (folder / f"{pair.upper()}.POT").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _atoms() -> Atoms:
    return Atoms("NaO", scaled_positions=[[0, 0, 0], [.25, 0, 0]], cell=np.eye(3) * 8, pbc=True)


def _fallback_collections(workdir: Path, request_present: bool):
    request = workdir / "request"; regulator = workdir / "regulator"
    request.mkdir(); regulator.mkdir()
    if request_present:
        _pot(request, "Na-O", 1.0)
    _pot(regulator, "Na-O", 3.0)
    return compile_spp_components(
        request_pot_root=request, regulator_pot_root=regulator,
        pairs=[("Na", "O")], allow_request_fallback=True,
    )


def _score(collections, status: str):
    request, regulator, _ = collections
    atoms = _atoms()
    return score_spp_components(
        symbols=atoms.get_chemical_symbols(), positions=atoms.positions, cell=np.asarray(atoms.cell),
        request=request, regulator=regulator, pairs=[("Na", "O")],
        request_pair_statuses={"Na-O": status},
    )


def test_request_pot_quality_is_evaluated_per_pair() -> None:
    quality = {"pairs": [{"pair": "Na-O", "pot_quality": "usable"}, {"pair": "O-O", "pot_quality": "capped"}]}
    assert classify_request_pair_quality(["Na-O", "O-O", "Na-Na"], quality, ["Na-Na"]) == {
        "Na-O": REQUEST_USABLE, "O-O": REQUEST_INSUFFICIENT, "Na-Na": REQUEST_MISSING,
    }


def test_usable_request_pair_combines_with_regulator(workdir: Path) -> None:
    result = _score(_fallback_collections(workdir, True), REQUEST_USABLE)
    assert result.request_spp_score != 0 and result.regulator_spp_score != 0
    assert result.pair_components[0]["guidance_mode"] == "REQUEST_PLUS_REGULATOR"


def test_unusable_request_pair_uses_regulator_only(workdir: Path) -> None:
    result = _score(_fallback_collections(workdir, False), REQUEST_INSUFFICIENT)
    assert result.request_spp_score == 0
    assert result.pair_components[0]["combined_pair_score"] == pytest.approx(20 * result.regulator_spp_score)


def test_missing_request_pair_uses_regulator_only(workdir: Path) -> None:
    result = _score(_fallback_collections(workdir, False), REQUEST_MISSING)
    assert result.pair_components[0]["guidance_mode"] == "REGULATOR_ONLY_LOCAL_MISSING"


def test_no_silent_zero_for_local_missing_pair(workdir: Path) -> None:
    result = _score(_fallback_collections(workdir, False), REQUEST_MISSING)
    assert result.solver_objective != 0
    assert result.number_regulator_fallback_pairs == 1


def test_missing_request_and_regulator_pair_fails_loudly() -> None:
    with pytest.raises(ValueError, match="GUIDANCE_PAIR_UNSUPPORTED"):
        guidance_mode_for_pair(REQUEST_MISSING, False)


def test_pairwise_components_sum_to_combined_objective(workdir: Path) -> None:
    result = _score(_fallback_collections(workdir, True), REQUEST_USABLE)
    assert sum(row["combined_pair_score"] for row in result.pair_components) == pytest.approx(result.solver_objective)


def test_independent_pairwise_recomputation_matches_solver(workdir: Path) -> None:
    request, regulator, combined = _fallback_collections(workdir, False)
    atoms = _atoms()
    result = score_spp_components(
        symbols=atoms.get_chemical_symbols(), positions=atoms.positions, cell=np.asarray(atoms.cell),
        request=request, regulator=regulator, pairs=[("Na", "O")], request_pair_statuses={"Na-O": REQUEST_MISSING},
    )
    assert 10 * combined.score(atoms.get_chemical_symbols(), atoms.positions, atoms.cell) == pytest.approx(result.solver_objective)


def test_partial_request_spp_reports_partial_support() -> None:
    assert request_support_status([REQUEST_USABLE, REQUEST_INSUFFICIENT]) == "PARTIAL_LOCAL_SUPPORT_WITH_REGULATOR_FALLBACK"


def test_fresh_request_spp_regenerated_each_run(workdir: Path) -> None:
    first = _request_spp_run_id("bundle-hash", workdir / "run-one")
    second = _request_spp_run_id("bundle-hash", workdir / "run-two")
    assert first != second
    assert first == _request_spp_run_id("bundle-hash", workdir / "run-one")


def test_regulator_artifact_is_reused_not_regenerated(workdir: Path) -> None:
    regulator = workdir / "regulator"; _pot(regulator, "Na-O", 3.0)
    config = WorkflowConfig(output_root=workdir, regulator_root=regulator)
    first = ProductionWorkflowStages._regulator_root(config)
    first_hash = _tree_hash(first)
    second = ProductionWorkflowStages._regulator_root(config)
    assert first == second == regulator.resolve()
    assert _tree_hash(second) == first_hash


def test_solve_supported_pair_sets_come_from_canonical_guidance_modes() -> None:
    required = ["Na-O", "O-O", "Na-Na"]
    rows = [
        {"species_pair": "Na-O", "request_pair_status": REQUEST_USABLE, "guidance_mode": "REQUEST_PLUS_REGULATOR"},
        {"species_pair": "O-O", "request_pair_status": REQUEST_INSUFFICIENT, "guidance_mode": "REGULATOR_ONLY_LOCAL_INSUFFICIENT"},
        {"species_pair": "Na-Na", "request_pair_status": REQUEST_MISSING, "guidance_mode": "REGULATOR_ONLY_LOCAL_MISSING"},
    ]
    guidance = _solver_pair_guidance(required, rows)
    assert guidance["solver_supported_pairs"] == required
    assert guidance["request_supported_pairs"] == ["Na-O"]
    assert guidance["regulator_fallback_pairs"] == ["O-O", "Na-Na"]
    assert guidance["unsupported_pairs"] == []


def test_unsupported_required_pair_fails_before_solver_invocation(workdir: Path, monkeypatch) -> None:
    stages = ProductionWorkflowStages()
    config = WorkflowConfig(output_root=workdir)
    task = stages.normalise("BaTiO3")
    required = stages.required_pairs(task, config)
    rows = [
        {
            "species_pair": pair,
            "request_pair_status": REQUEST_MISSING,
            "guidance_mode": "GUIDANCE_PAIR_UNSUPPORTED" if pair == required[0] else "REGULATOR_ONLY_LOCAL_MISSING",
        }
        for pair in required
    ]
    invoked = False

    def forbidden_solver(request):
        nonlocal invoked
        invoked = True
        raise AssertionError("solver must not be invoked")

    solve_module = importlib.import_module("qlip.core.solve")
    monkeypatch.setattr(solve_module, "solve", forbidden_solver)
    with pytest.raises(WorkflowStageError) as caught:
        stages.solve(task, {"quality": {"request_pair_results": rows}}, config, workdir / "run")
    assert caught.value.code == "GUIDANCE_PAIR_UNSUPPORTED"
    assert caught.value.details["unsupported_pairs"] == [required[0]]
    assert invoked is False


def test_all_supported_pair_modes_reach_solver_without_omission(workdir: Path, monkeypatch) -> None:
    stages = ProductionWorkflowStages()
    regulator = workdir / "regulator"
    request_root = workdir / "request-pots"
    config = WorkflowConfig(output_root=workdir, regulator_root=regulator)
    task = stages.normalise("BaTiO3")
    required = stages.required_pairs(task, config)
    request_pair = required[0]
    _pot(request_root, request_pair, 1.0)
    for pair in required:
        _pot(regulator, pair, 2.0)
    rows = [
        {
            "species_pair": pair,
            "request_pair_status": REQUEST_USABLE if pair == request_pair else REQUEST_INSUFFICIENT,
            "guidance_mode": "REQUEST_PLUS_REGULATOR" if pair == request_pair else "REGULATOR_ONLY_LOCAL_INSUFFICIENT",
        }
        for pair in required
    ]
    captured = {}

    def capture_solver(request):
        captured["request"] = request
        raise RuntimeError("solver invoked after complete guidance validation")

    solve_module = importlib.import_module("qlip.core.solve")
    monkeypatch.setattr(solve_module, "solve", capture_solver)
    with pytest.raises(RuntimeError, match="solver invoked after complete guidance validation"):
        stages.solve(
            task,
            {
                "pot_root": str(request_root),
                "regulator_root": str(regulator),
                "quality": {"request_pair_results": rows},
            },
            config,
            workdir / "run",
        )
    params = captured["request"]["guidance"][0]["params"]
    assert params["supported_pairs"] == [request_pair]
    assert params["missing_pairs"] == required[1:]
    assert set(params["supported_pairs"]) | set(params["missing_pairs"]) == set(required)
    assert params["missing_pair_policy"] == "fallback"
    assert params["regularisation_weight"] == 2.0
    assert (request_root / request_pair.upper() / f"{request_pair.upper()}.POT").is_file()
    assert all((regulator / pair.upper() / f"{pair.upper()}.POT").is_file() for pair in required)
