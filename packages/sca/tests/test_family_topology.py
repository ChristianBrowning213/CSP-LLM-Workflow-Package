from __future__ import annotations

import pytest
from pymatgen.core import Lattice, Structure

import sca.evaluators.topology as topology


CASES = {
    "ROCKSALT": ({"Na": 1, "Cl": 1}, {"Na": (6, {"Cl": 6}), "Cl": (6, {"Na": 6})}),
    "FLUORITE": ({"Ce": 1, "O": 2}, {"Ce": (8, {"O": 8}), "O": (4, {"Ce": 4})}),
    "PEROVSKITE_3D": ({"Ba": 1, "Ti": 1, "O": 3}, {"Ba": (12, {"O": 12}), "Ti": (6, {"O": 6}), "O": (2, {"Ti": 2})}),
    "HALIDE_PEROVSKITE_3D": ({"Cs": 1, "Pb": 1, "Br": 3}, {"Cs": (12, {"Br": 12}), "Pb": (6, {"Br": 6}), "Br": (2, {"Pb": 2})}),
    "SPINEL": ({"Zn": 1, "Fe": 2, "O": 4}, {"Zn": (4, {"O": 4}), "Fe": (6, {"O": 6}), "O": (4, {"Zn": 1, "Fe": 3})}),
    "OLIVINE": ({"Li": 1, "Fe": 1, "P": 1, "O": 4}, {"Li": (6, {"O": 6}), "Fe": (6, {"O": 6}), "P": (4, {"O": 4}), "O": (4, {})}),
    "LAYERED_OXIDE": ({"Li": 1, "Co": 1, "O": 2}, {"Li": (6, {"O": 6}), "Co": (6, {"O": 6}), "O": (6, {})}),
    "ARGYRODITE_ORDERED": ({"Li": 6, "P": 1, "S": 5, "Cl": 1}, {"Li": (4, {"S": 4}), "P": (4, {"S": 4}), "S": (4, {}), "Cl": (4, {})}),
    "NASICON_ORDERED": ({"Na": 3, "Zr": 2, "Si": 2, "P": 1, "O": 12}, {"Na": (6, {"O": 6}), "Zr": (6, {"O": 6}), "Si": (4, {"O": 4}), "P": (4, {"O": 4}), "O": (4, {})}),
}


def _structure(counts: dict[str, int]) -> Structure:
    species = [symbol for symbol, count in counts.items() for _ in range(count)]
    n = len(species)
    coords = [[((i * 3) % n) / n, ((i * 5) % n) / n, ((i * 7) % n) / n] for i in range(n)]
    return Structure(Lattice.cubic(max(8, n)), species, coords)


def _local(spec: dict[str, tuple[int, dict[str, int]]], counts: dict[str, int]):
    records = []
    summary = {}
    index = 0
    for symbol, count in counts.items():
        cn, neighbours = spec.get(symbol, (0, {}))
        summary[symbol] = {"site_count": count, "min": cn, "max": cn, "mean": cn, "median": cn}
        for _ in range(count):
            records.append({"site_index": index, "species": symbol, "coordination_number": cn, "neighbour_species": neighbours})
            index += 1
    return {
        "coordination_number_by_site": records,
        "coordination_summary_by_species": summary,
        "undercoordinated_site_count": 0,
        "overcoordinated_site_count": 0,
        "polyhedra_summary": {},
        "framework_dimensionality": 3,
        "warnings": [],
    }, {"coordination_records": records}


@pytest.mark.parametrize("policy", CASES)
def test_family_policy_positive_fixture_passes(policy: str, monkeypatch) -> None:
    counts, spec = CASES[policy]
    monkeypatch.setattr(topology, "local_environment_metrics", lambda structure: _local(spec, counts))

    metrics, _ = topology.family_topology_metrics(_structure(counts), policy)

    assert metrics["topology_status"] == "PASS"


@pytest.mark.parametrize("policy", CASES)
def test_family_policy_topology_wrong_but_formula_correct_does_not_pass(policy: str, monkeypatch) -> None:
    counts, _ = CASES[policy]
    wrong = {symbol: (0, {}) for symbol in counts}
    monkeypatch.setattr(topology, "local_environment_metrics", lambda structure: _local(wrong, counts))

    metrics, _ = topology.family_topology_metrics(_structure(counts), policy)

    assert metrics["topology_status"] != "PASS"


@pytest.mark.parametrize("policy", CASES)
def test_family_policy_wrong_formula_fixture_does_not_pass(policy: str, monkeypatch) -> None:
    counts = {"Si": 1}
    wrong = {"Si": (0, {})}
    monkeypatch.setattr(topology, "local_environment_metrics", lambda structure: _local(wrong, counts))

    metrics, _ = topology.family_topology_metrics(_structure(counts), policy)

    assert metrics["topology_status"] != "PASS"
