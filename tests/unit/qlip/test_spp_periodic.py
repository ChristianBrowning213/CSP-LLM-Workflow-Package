import numpy as np
import pyomo.environ as pyo
import pytest
from ase import Atoms
from ase.io import write

from qlip.allocation import Allocation
from qlip.interactions.spp import SPP, SPPCollection, periodic_spp_sum, soft_missing_pair_penalty
from qlip.plugins.registry import GuidanceRegistry
from tests.qlip_support.audit_spp_objective import audit as audit_spp_objective


class _ConstantSPP:
    def __call__(self, distance):
        return 1.0


class _RoundedDistanceSPP:
    def __call__(self, distance):
        return round(float(distance), 6)


class _ShortContactPenaltySPP:
    def __call__(self, distance):
        return 1000.0 if float(distance) < 1.2 else 1.0


class _ScaledDistanceSPP:
    def __init__(self, scale):
        self.scale = float(scale)

    def __call__(self, distance):
        return self.scale * round(float(distance), 6)


def reference_ipcsp_periodic_sum(frac_i, frac_j, cell, spp_func, cutoff=11.0):
    """
    Independent IPCSP-SPP-style periodic coefficient reference.

    This intentionally does not call QLIP's periodic_spp_sum. It enumerates
    integer lattice shifts, sums all images within cutoff, skips the central
    zero self-distance, and applies the unordered 0.5 multiplicity to the
    symmetric +/-T translations of a diagonal self pair.
    """
    frac_i = np.asarray(frac_i, dtype=float)
    frac_j = np.asarray(frac_j, dtype=float)
    cell = np.asarray(cell, dtype=float)
    norms = np.linalg.norm(cell, axis=1)
    depth = int(np.ceil(float(cutoff) / float(np.min(norms[norms > 1e-12]))) + 1)

    total = 0.0
    for sx in range(-depth, depth + 1):
        for sy in range(-depth, depth + 1):
            for sz in range(-depth, depth + 1):
                shift = np.array([sx, sy, sz], dtype=float)
                disp = (frac_j + shift - frac_i) @ cell
                distance = float(np.linalg.norm(disp))
                if distance <= 1e-12 or distance > cutoff:
                    continue
                total += float(spp_func(distance))
    if np.allclose(frac_i, frac_j, rtol=0.0, atol=1e-12):
        total *= 0.5
    return float(total)


def _manual_image_count(frac_i, frac_j, cell, cutoff):
    frac_i = np.asarray(frac_i, dtype=float)
    frac_j = np.asarray(frac_j, dtype=float)
    cell = np.asarray(cell, dtype=float)
    count = 0
    for sx in range(-5, 6):
        for sy in range(-5, 6):
            for sz in range(-5, 6):
                disp = (frac_j + np.array([sx, sy, sz], dtype=float) - frac_i) @ cell
                distance = float(np.linalg.norm(disp))
                if 1e-12 < distance <= cutoff:
                    count += 1
    return count


def _assign_only(allocation, occupied):
    occupied = set(occupied)
    for species in allocation.m.Types:
        for site in allocation.m.Pos:
            allocation.m.x[species, site].set_value(1 if (species, site) in occupied else 0)


def _write_regularisation_pot(root, pair: str, values=None):
    values = values or [(0.5, 4.0), (1.0, 3.0), (2.0, 1.0), (3.0, 0.5)]
    path = root / pair.upper() / f"{pair.upper()}.POT"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{r} {u}" for r, u in values) + "\n", encoding="utf-8")
    return path


def test_spp_interp_out_of_range_returns_zero():
    spp = SPP(
        np.array([1.0, 2.0, 3.0, 4.0]),
        np.array([2.0, 5.0, 3.0, 1.0]),
    )

    assert float(spp(0.5)) == 0.0
    assert float(spp(5.0)) == 0.0
    np.testing.assert_allclose(spp(np.array([0.5, 5.0])), np.array([0.0, 0.0]))


def test_periodic_spp_sum_includes_boundary_image():
    cell = np.diag([10.0, 10.0, 10.0])

    total = periodic_spp_sum(
        [0.95, 0.0, 0.0],
        [0.05, 0.0, 0.0],
        cell,
        _ConstantSPP(),
        cutoff=2.0,
    )

    assert total == 1.0


def test_periodic_spp_sum_sums_multiple_images_not_minimum_only():
    cell = np.diag([5.0, 5.0, 5.0])
    frac_i = [0.0, 0.0, 0.0]
    frac_j = [0.5, 0.0, 0.0]

    total = periodic_spp_sum(frac_i, frac_j, cell, _ConstantSPP(), cutoff=11.0)

    expected = _manual_image_count(frac_i, frac_j, cell, cutoff=11.0)
    assert total > 1.0
    assert total == float(expected)


def test_periodic_all_image_parity_constant_spp_small_cubic_cell():
    cell = np.diag([3.0, 3.0, 3.0])
    frac_i = [0.1, 0.2, 0.3]
    frac_j = [0.8, 0.2, 0.3]
    spp = _ConstantSPP()

    qlip_total = periodic_spp_sum(frac_i, frac_j, cell, spp, cutoff=8.0)
    reference_total = reference_ipcsp_periodic_sum(frac_i, frac_j, cell, spp, cutoff=8.0)

    assert reference_total > 1.0
    assert qlip_total == reference_total


def test_periodic_spp_sum_applies_11a_cutoff():
    cell = np.diag([20.0, 20.0, 20.0])

    total = periodic_spp_sum(
        [0.0, 0.0, 0.0],
        [0.4, 0.0, 0.0],
        cell,
        _ConstantSPP(),
        cutoff=7.99,
    )

    assert total == 0.0


def test_periodic_spp_sum_excludes_zero_self_but_includes_translated_self_images():
    cell = np.diag([5.0, 5.0, 5.0])

    total = periodic_spp_sum(
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        cell,
        _ConstantSPP(),
        cutoff=6.0,
    )

    assert total == 3.0


def test_periodic_spp_sum_matches_ipcsp_reference_simple_cubic_boundary_pair():
    cell = np.diag([10.0, 10.0, 10.0])
    frac_i = [0.95, 0.0, 0.0]
    frac_j = [0.05, 0.0, 0.0]
    spp = _RoundedDistanceSPP()

    qlip_total = periodic_spp_sum(frac_i, frac_j, cell, spp, cutoff=2.0)
    reference_total = reference_ipcsp_periodic_sum(frac_i, frac_j, cell, spp, cutoff=2.0)

    assert reference_total == 1.0
    assert qlip_total == reference_total


def test_periodic_spp_sum_matches_ipcsp_reference_non_cubic_orthorhombic():
    cell = np.diag([4.0, 6.0, 8.0])
    frac_i = [0.1, 0.2, 0.3]
    frac_j = [0.9, 0.2, 0.3]
    spp = _RoundedDistanceSPP()

    qlip_total = periodic_spp_sum(frac_i, frac_j, cell, spp, cutoff=4.1)
    reference_total = reference_ipcsp_periodic_sum(frac_i, frac_j, cell, spp, cutoff=4.1)

    assert reference_total == 4.0
    assert qlip_total == reference_total


def test_periodic_spp_sum_matches_ipcsp_reference_self_pair_images():
    cell = np.diag([5.0, 5.0, 5.0])
    spp = _ConstantSPP()

    qlip_total = periodic_spp_sum([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], cell, spp, cutoff=5.1)
    reference_total = reference_ipcsp_periodic_sum(
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
        cell,
        spp,
        cutoff=5.1,
    )

    assert reference_total == 3.0
    assert qlip_total == reference_total


def test_periodic_spp_sum_matches_ipcsp_reference_cutoff_boundary():
    cell = np.diag([5.0, 5.0, 5.0])
    spp = _ConstantSPP()
    frac = [0.0, 0.0, 0.0]

    below = periodic_spp_sum(frac, frac, cell, spp, cutoff=4.999)
    below_reference = reference_ipcsp_periodic_sum(frac, frac, cell, spp, cutoff=4.999)
    above = periodic_spp_sum(frac, frac, cell, spp, cutoff=5.001)
    above_reference = reference_ipcsp_periodic_sum(frac, frac, cell, spp, cutoff=5.001)

    assert below_reference == 0.0
    assert below == below_reference
    assert above_reference == 3.0
    assert above == above_reference


def test_spp_objective_compile_uses_periodic_pair_cost_matrix():
    atoms = Atoms("H2")
    positions = Atoms("HH", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.95, 0.0, 0.0], [0.05, 0.0, 0.0]])

    class PeriodicCost:
        include_diagonal_pair_terms = True

        def __init__(self):
            self.called = False

        def pair_cost_matrix(self, pair, sites):
            self.called = True
            return np.array([[6.0, 1.0], [1.0, 6.0]])

        def __call__(self, pair, distances):
            raise AssertionError("minimum-image distance mapping should not be used")

    cost = PeriodicCost()
    allocation = Allocation(atoms, positions=positions, cost=cost)

    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(1)

    assert cost.called is True
    assert pyo.value(allocation.m.obj) == 13.0


def test_spp_objective_value_matches_reported_score_for_fixed_assignment():
    positions = Atoms("HH", cell=np.diag([5.0, 5.0, 5.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])

    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 5.1
    collection.spps = {("H", "H"): _ConstantSPP()}

    allocation = Allocation(Atoms("H2"), positions=positions, cost=collection)
    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(1)

    objective_value = float(pyo.value(allocation.m.obj))
    score = collection.score(
        ["H", "H"],
        positions.get_positions(),
        positions.cell,
        pbc=True,
    )
    matrix = collection.pair_cost_matrix(("H", "H"), positions)
    expected_from_coefficients = matrix[0, 0] + matrix[1, 1] + matrix[0, 1]

    assert matrix[0, 0] == 3.0
    assert matrix[1, 1] == 3.0
    assert matrix[0, 1] == 2.0
    assert objective_value == expected_from_coefficients
    assert objective_value == score


def test_spp_objective_counts_distinct_species_off_diagonal_once():
    positions = Atoms("HH", cell=np.diag([5.0, 5.0, 5.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])

    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 5.1
    collection.spps = {("H", "He"): _ConstantSPP()}

    allocation = Allocation(Atoms("HHe"), positions=positions, cost=collection)
    allocation.pairs = [("H", "He")]
    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(0)
    allocation.m.x["He", 0].set_value(0)
    allocation.m.x["He", 1].set_value(1)

    score = collection.score(
        ["H", "He"],
        positions.get_positions(),
        positions.cell,
        pbc=True,
    )
    matrix = collection.pair_cost_matrix(("H", "He"), positions)

    assert matrix[0, 1] == 2.0
    assert float(pyo.value(allocation.m.obj)) == matrix[0, 1]
    assert float(pyo.value(allocation.m.obj)) == score


def test_spp_objective_counts_same_species_off_diagonal_once_without_diagonal_terms():
    positions = Atoms("HH", cell=np.diag([5.0, 5.0, 5.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])

    class NoDiagonalSPPCollection:
        include_diagonal_pair_terms = False

        def pair_cost_matrix(self, pair, sites):
            return np.array([[6.0, 2.0], [2.0, 6.0]])

    allocation = Allocation(Atoms("H2"), positions=positions, cost=NoDiagonalSPPCollection())
    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(1)

    assert float(pyo.value(allocation.m.obj)) == 2.0


def test_spp_objective_counts_diagonal_self_image_once_per_occupied_site():
    positions = Atoms("HH", cell=np.diag([5.0, 5.0, 5.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])

    class DiagonalSPPCollection:
        include_diagonal_pair_terms = True

        def pair_cost_matrix(self, pair, sites):
            return np.array([[6.0, 2.0], [2.0, 6.0]])

    allocation = Allocation(Atoms("H2"), positions=positions, cost=DiagonalSPPCollection())
    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(1)

    assert float(pyo.value(allocation.m.obj)) == 14.0


def test_short_contact_inside_cutoff_is_included_in_objective():
    positions = Atoms("HH", cell=np.diag([4.6, 4.6, 4.6]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.25, 0.0, 0.0]])

    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {("H", "H"): _ShortContactPenaltySPP()}

    matrix = collection.pair_cost_matrix(("H", "H"), positions)
    allocation = Allocation(Atoms("H2"), positions=positions, cost=collection)
    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(1)

    assert matrix[0, 1] >= 1000.0
    assert float(pyo.value(allocation.m.obj)) >= 1000.0


def test_spp_guidance_weight_scales_objective_coefficients():
    positions = Atoms("HH", cell=np.diag([5.0, 5.0, 5.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]])

    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 5.1
    collection.spps = {("H", "H"): _ConstantSPP()}

    allocation_base = Allocation(Atoms("H2"), positions=positions, cost=collection)
    allocation_base.encode()
    allocation_base.m.x["H", 0].set_value(1)
    allocation_base.m.x["H", 1].set_value(1)
    base_value = float(pyo.value(allocation_base.m.obj))

    allocation_scaled = Allocation(Atoms("H2"), positions=positions, cost=collection)
    allocation_scaled.encode()
    plugin = GuidanceRegistry.get("objective.energy_spp")
    plugin.apply(allocation_scaled, {"weight": 10.0, "params": {}}, "weighted_sum")
    allocation_scaled.m.x["H", 0].set_value(1)
    allocation_scaled.m.x["H", 1].set_value(1)

    assert float(pyo.value(allocation_scaled.m.obj)) == 10.0 * base_value


def test_spp_pair_cost_matrix_matches_ipcsp_reference_coefficients():
    positions = Atoms("HHH", cell=np.diag([5.0, 5.0, 5.0]), pbc=True)
    positions.set_scaled_positions(
        [
            [0.0, 0.0, 0.0],
            [0.5, 0.0, 0.0],
            [0.0, 0.5, 0.0],
        ]
    )
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 5.1
    collection.spps = {("H", "He"): _RoundedDistanceSPP()}

    matrix = collection.pair_cost_matrix(("H", "He"), positions)
    frac = positions.get_scaled_positions()

    for i in range(len(frac)):
        for j in range(len(frac)):
            expected = reference_ipcsp_periodic_sum(
                frac[i],
                frac[j],
                positions.cell,
                _RoundedDistanceSPP(),
                cutoff=5.1,
            )
            assert matrix[i, j] == expected


def test_spp_collection_score_includes_translated_self_images():
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 6.0
    collection.spps = {("H", "H"): _ConstantSPP()}

    score = collection.score(
        ["H"],
        np.array([[0.0, 0.0, 0.0]]),
        np.diag([5.0, 5.0, 5.0]),
        pbc=True,
    )

    assert score == 3.0


def test_cubic_lattice_pair_cost_matrix_distance_consistency_and_score_parity():
    positions = Atoms("HHe", cell=np.diag([4.6, 4.6, 4.6]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.25, 0.0, 0.0]])

    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {("H", "He"): _RoundedDistanceSPP()}

    matrix = collection.pair_cost_matrix(("H", "He"), positions)
    allocation = Allocation(Atoms("HHe"), positions=positions, cost=collection)
    allocation.pairs = [("H", "He")]
    allocation.encode()
    allocation.m.x["H", 0].set_value(1)
    allocation.m.x["H", 1].set_value(0)
    allocation.m.x["He", 0].set_value(0)
    allocation.m.x["He", 1].set_value(1)

    assert matrix[0, 1] == 1.15
    assert float(pyo.value(allocation.m.obj)) == matrix[0, 1]
    assert float(pyo.value(allocation.m.obj)) == collection.score(
        ["H", "He"],
        positions.get_positions(),
        positions.cell,
        pbc=True,
    )


def test_missing_pair_neutral_score_contribution_is_zero():
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {}
    collection.missing_pair_policy = "neutral"

    score = collection.score(
        ["H", "He"],
        np.array([[0.0, 0.0, 0.0], [1.15, 0.0, 0.0]]),
        np.diag([10.0, 10.0, 10.0]),
        pbc=True,
    )

    assert score == 0.0


def test_missing_pair_soft_repulsive_short_contact_contributes():
    positions = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {}
    collection.missing_pair_policy = "soft_repulsive"

    matrix = collection.pair_cost_matrix(("H", "He"), positions)

    assert matrix[0, 1] > 0.0
    assert matrix[0, 1] == pytest.approx(soft_missing_pair_penalty(1.15))


def test_missing_pair_soft_repulsive_decays_with_distance():
    short = soft_missing_pair_penalty(1.15)
    long = soft_missing_pair_penalty(8.0)

    assert short > long
    assert long < 0.001


def test_missing_pair_soft_repulsive_objective_and_score_parity():
    positions = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {}
    collection.missing_pair_policy = "soft_repulsive"

    allocation = Allocation(Atoms("HHe"), positions=positions, cost=collection)
    allocation.pairs = [("H", "He")]
    allocation.encode()
    _assign_only(allocation, {("H", 0), ("He", 1)})

    objective = float(pyo.value(allocation.m.obj))
    score = collection.score(["H", "He"], positions.get_positions(), positions.cell, pbc=True)

    assert objective > 0.0
    assert objective == score


def test_missing_pair_soft_repulsive_weight_scaling():
    positions = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {}
    collection.missing_pair_policy = "soft_repulsive"

    allocation_base = Allocation(Atoms("HHe"), positions=positions, cost=collection)
    allocation_base.pairs = [("H", "He")]
    allocation_base.encode()
    _assign_only(allocation_base, {("H", 0), ("He", 1)})
    base = float(pyo.value(allocation_base.m.obj))

    allocation_scaled = Allocation(Atoms("HHe"), positions=positions, cost=collection)
    allocation_scaled.pairs = [("H", "He")]
    allocation_scaled.encode()
    plugin = GuidanceRegistry.get("objective.energy_spp")
    plugin.apply(allocation_scaled, {"weight": 10.0, "params": {}}, "weighted_sum")
    _assign_only(allocation_scaled, {("H", 0), ("He", 1)})

    assert float(pyo.value(allocation_scaled.m.obj)) == 10.0 * base


def test_spp_objective_audit_labels_soft_missing_pair_fallback(tmp_path):
    pot_root = tmp_path / "empty_pots"
    pot_root.mkdir()
    cif_path = tmp_path / "toy.cif"
    atoms = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    atoms.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    write(cif_path, atoms)

    payload = audit_spp_objective(
        cif_path,
        pot_root,
        cutoff=2.0,
        missing_pair_policy="soft_repulsive",
        guidance_weight=3.0,
        top_k=5,
    )

    fallback = [row for row in payload["contributions"] if row["source"] == "missing_pair_fallback"]
    assert fallback
    assert payload["summary"]["missing_pair_fallback_contribution_count"] == len(fallback)
    assert fallback[0]["raw_contribution"] > 0.0
    assert fallback[0]["weighted_contribution"] == 3.0 * fallback[0]["raw_contribution"]


def test_regularisation_pots_load_recursively_with_canonical_pair_alias(tmp_path):
    root = tmp_path / "global_spp"
    _write_regularisation_pot(root, "AL-GD")

    collection = SPPCollection(
        tmp_path,
        cutoff=3.0,
        regularisation_spp_dir=root,
        regularisation_weight=1.0,
    )

    assert ("Al", "Gd") in collection.regularisation_spps
    positions = Atoms("AlGd", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0]])
    assert collection.pair_cost_matrix(("Gd", "Al"), positions)[0, 1] > 0.0


def test_regularisation_only_pair_contributes_without_local_pot():
    positions = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {}
    collection.regularisation_spps = {("H", "He"): _ScaledDistanceSPP(2.0)}
    collection.regularisation_weight = 3.0
    collection.missing_pair_policy = "neutral"

    matrix = collection.pair_cost_matrix(("He", "H"), positions)

    assert matrix[0, 1] == pytest.approx(3.0 * 2.0 * 1.15)


def test_explicit_spp_and_regularisation_are_additive():
    positions = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {("H", "He"): _ScaledDistanceSPP(1.0)}
    collection.regularisation_spps = {("H", "He"): _ScaledDistanceSPP(2.0)}
    collection.regularisation_weight = 4.0
    collection.missing_pair_policy = "soft_repulsive"

    matrix = collection.pair_cost_matrix(("H", "He"), positions)

    assert matrix[0, 1] == pytest.approx(1.15 + 4.0 * 2.0 * 1.15)


def test_regularisation_does_not_disable_soft_missing_pair_fallback():
    positions = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    positions.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    collection = SPPCollection.__new__(SPPCollection)
    collection.cutoff = 2.0
    collection.spps = {}
    collection.regularisation_spps = {}
    collection.regularisation_weight = 10.0
    collection.missing_pair_policy = "soft_repulsive"

    matrix = collection.pair_cost_matrix(("H", "He"), positions)

    assert matrix[0, 1] == pytest.approx(soft_missing_pair_penalty(1.15))


def test_spp_objective_audit_reports_regularisation_contributions(tmp_path):
    pot_root = tmp_path / "empty_pots"
    pot_root.mkdir()
    regularisation_root = tmp_path / "global_pots"
    _write_regularisation_pot(regularisation_root, "H-HE")
    cif_path = tmp_path / "toy.cif"
    atoms = Atoms("HHe", cell=np.diag([10.0, 10.0, 10.0]), pbc=True)
    atoms.set_scaled_positions([[0.0, 0.0, 0.0], [0.115, 0.0, 0.0]])
    write(cif_path, atoms)

    payload = audit_spp_objective(
        cif_path,
        pot_root,
        cutoff=2.0,
        missing_pair_policy="soft_repulsive",
        guidance_weight=2.0,
        regularisation_spp_dir=regularisation_root,
        regularisation_weight=3.0,
        top_k=5,
    )

    regularised = [row for row in payload["contributions"] if row["source"] == "regularisation_only"]
    assert regularised
    assert payload["summary"]["regularisation_pairs_loaded"] == 1
    assert payload["summary"]["regularisation_contribution_count"] == len(regularised)
    assert regularised[0]["local_spp_supported"] is False
    assert regularised[0]["regularisation_supported"] is True
    assert regularised[0]["missing_pair_fallback_used"] is False
    assert regularised[0]["total_weighted_contribution"] == pytest.approx(
        regularised[0]["total_raw_contribution"] * 2.0
    )
