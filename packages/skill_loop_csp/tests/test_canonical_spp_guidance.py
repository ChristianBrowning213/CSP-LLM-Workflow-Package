from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pytest
from ase import Atoms

from sok_llm_orchestrator.contracts.spp_regularisation import apply_regularised_partial_spp_guidance
from sok_llm_orchestrator.workflow.spp import compile_spp_components, score_spp_components


def _pot(root: Path, pair: str, scale: float) -> None:
    folder = root / pair.upper()
    folder.mkdir(parents=True, exist_ok=True)
    rows = ["spline cubic reverse", f"{pair} 0.0 11.0"]
    rows.extend(f"{distance:.3f} {scale * distance:.8f}" for distance in np.linspace(0.0, 11.0, 221))
    (folder / f"{pair.upper()}.POT").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _collections(workdir: Path):
    request_root, regulator_root = workdir / "request", workdir / "regulator"
    _pot(request_root, "Na-O", 1.0)
    _pot(regulator_root, "Na-O", 3.0)
    return compile_spp_components(
        request_pot_root=request_root,
        regulator_pot_root=regulator_root,
        pairs=[("Na", "O")],
    )


def _atoms() -> Atoms:
    return Atoms("NaO", scaled_positions=[[0.0, 0.0, 0.0], [0.25, 0.0, 0.0]], cell=np.eye(3) * 8.0, pbc=True)


def _independent_periodic_pair_sum(atoms: Atoms, potential, cutoff: float = 11.0) -> float:
    """Brute-force reference independent of QLIP coefficient compilation."""
    frac = atoms.get_scaled_positions()
    cell = np.asarray(atoms.cell)
    shortest_cell_vector = min(float(np.linalg.norm(vector)) for vector in cell)
    image_bound = int(np.ceil(cutoff / shortest_cell_vector)) + 1
    total = 0.0
    for shift in itertools.product(range(-image_bound, image_bound + 1), repeat=3):
        delta = frac[1] + np.asarray(shift, dtype=float) - frac[0]
        distance = float(np.linalg.norm(delta @ cell))
        if 1e-12 < distance <= cutoff:
            total += float(potential(distance))
    return total


def test_request_spp_pair_coefficients_match_reference_calculation(workdir: Path) -> None:
    request, _, _ = _collections(workdir)
    atoms = _atoms()
    matrix = request.pair_cost_matrix(("Na", "O"), atoms)
    expected = _independent_periodic_pair_sum(atoms, request.get("Na", "O"))
    assert matrix[0, 1] == pytest.approx(expected)


def test_regulator_spp_pair_coefficients_match_reference_calculation(workdir: Path) -> None:
    _, regulator, _ = _collections(workdir)
    atoms = _atoms()
    matrix = regulator.pair_cost_matrix(("Na", "O"), atoms)
    expected = _independent_periodic_pair_sum(atoms, regulator.get("Na", "O"))
    assert matrix[0, 1] == pytest.approx(expected)


def test_combined_spp_equals_weighted_components(workdir: Path) -> None:
    request, regulator, combined = _collections(workdir)
    atoms = _atoms()
    request_matrix = request.pair_cost_matrix(("Na", "O"), atoms)
    regulator_matrix = regulator.pair_cost_matrix(("Na", "O"), atoms)
    combined_objective_matrix = 10.0 * combined.pair_cost_matrix(("Na", "O"), atoms)

    # QLIP compiles the inner request + 2*regulator coefficients first, then
    # objective.energy_spp applies the archived outer guidance weight of 10.
    expected_matrix = 10.0 * (request_matrix + 2.0 * regulator_matrix)
    assert combined_objective_matrix == pytest.approx(expected_matrix)

    # Independently validate the selected physical off-diagonal interaction.
    # Diagonal translated-self terms are already covered elementwise above and
    # are intentionally not compared with this off-diagonal scalar reference.
    request_reference = _independent_periodic_pair_sum(atoms, request.get("Na", "O"))
    regulator_reference = _independent_periodic_pair_sum(atoms, regulator.get("Na", "O"))
    expected_off_diagonal = 10.0 * (request_reference + 2.0 * regulator_reference)
    assert combined_objective_matrix[0, 1] == pytest.approx(expected_off_diagonal)
    assert combined_objective_matrix[1, 0] == pytest.approx(expected_off_diagonal)


def test_periodic_11A_interactions_match_bruteforce_small_fixture(workdir: Path) -> None:
    request, _, _ = _collections(workdir)
    atoms = _atoms()
    brute = _independent_periodic_pair_sum(atoms, request.get("Na", "O"))
    assert request.pair_cost_matrix(("Na", "O"), atoms)[0, 1] == pytest.approx(brute)


def test_solver_objective_matches_independent_recomputation(workdir: Path) -> None:
    request, regulator, combined = _collections(workdir)
    atoms = _atoms()
    components = score_spp_components(
        symbols=atoms.get_chemical_symbols(),
        positions=atoms.positions,
        cell=np.asarray(atoms.cell),
        request=request,
        regulator=regulator,
    )
    independent = 10.0 * (
        _independent_periodic_pair_sum(atoms, request.get("Na", "O"))
        + 2.0 * _independent_periodic_pair_sum(atoms, regulator.get("Na", "O"))
    )
    solver_compiled = 10.0 * combined.score(
        atoms.get_chemical_symbols(), atoms.positions, atoms.cell
    )
    assert solver_compiled == pytest.approx(independent)
    assert components.solver_objective == pytest.approx(independent)


def test_no_request_regulator_and_combined_conditions_decompose_independently(workdir: Path) -> None:
    request, regulator, _ = _collections(workdir)
    atoms = _atoms()
    common = {
        "symbols": atoms.get_chemical_symbols(),
        "positions": atoms.positions,
        "cell": np.asarray(atoms.cell),
    }
    no_spp = score_spp_components(**common, request=None, regulator=None)
    request_only = score_spp_components(**common, request=request, regulator=None)
    regulator_only = score_spp_components(**common, request=None, regulator=regulator)
    combined = score_spp_components(**common, request=request, regulator=regulator)

    assert no_spp.request_spp_score == 0.0
    assert no_spp.regulator_spp_score == 0.0
    assert request_only.request_spp_score != 0.0
    assert request_only.regulator_spp_score == 0.0
    assert regulator_only.request_spp_score == 0.0
    assert regulator_only.regulator_spp_score != 0.0
    assert combined.request_spp_score == pytest.approx(request_only.request_spp_score)
    assert combined.regulator_spp_score == pytest.approx(regulator_only.regulator_spp_score)
    assert combined.solver_objective == pytest.approx(
        10.0 * (combined.request_spp_score + 2.0 * combined.regulator_spp_score)
    )


def test_missing_required_pair_fails_loudly(workdir: Path) -> None:
    request_root, regulator_root = workdir / "request", workdir / "regulator"
    request_root.mkdir(); regulator_root.mkdir()
    with pytest.raises(RuntimeError, match="POT file not found"):
        compile_spp_components(request_pot_root=request_root, regulator_pot_root=regulator_root, pairs=[("Na", "O")])


def test_regulator_augmentation_preserves_request_specific_pot_root(workdir: Path) -> None:
    request_root, regulator_root = workdir / "request", workdir / "regulator"
    request_root.mkdir(); regulator_root.mkdir()
    request = {
        "problem": {"objective": {"type": "spp_energy"}},
        "context": {"pot_root": str(request_root)},
        "guidance": [{"id": "objective.energy_spp", "params": {"spp_package_path": "bundle"}}],
    }
    patched = apply_regularised_partial_spp_guidance(
        request,
        formula="NaO",
        overrides={"spp_regularisation_dir": str(regulator_root), "spp_regularisation_weight": 2.0, "spp_guidance_weight": 10.0},
    )
    assert patched["context"]["pot_root"] == str(request_root)
    params = patched["guidance"][0]["params"]
    assert params["spp_package_path"] == "bundle"
    assert params["regularisation_spp_dir"] == str(regulator_root)
    assert params["regularisation_weight"] == 2.0
    assert "mode" not in params
