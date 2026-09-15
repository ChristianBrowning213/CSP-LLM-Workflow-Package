from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from ase import Atoms
from jsonschema import Draft202012Validator

from qlip.allocation import Allocation
from qlip.scaffolds import get_scaffold
from qlip.scaffolds.multi import run_scaffold_hypotheses
from qlip.scaffolds.topk import _assignment, enumerate_top_k


class _ZeroCost:
    include_diagonal_pair_terms = False

    def pair_cost_matrix(self, pair, positions):
        return np.zeros((len(positions), len(positions)), dtype=float)


def _allocation() -> Allocation:
    allocation = Allocation(Atoms("LiNa"))
    allocation.positions = Atoms("H2", cell=[4.0, 4.0, 4.0], pbc=True)
    allocation.positions.set_scaled_positions([[0, 0, 0], [0.25, 0.25, 0.25]])
    allocation.cost = _ZeroCost()
    allocation.ordered_orbits = [
        {"orbit_id": "a", "site_indices": [0], "allowed_species": ["Li", "Na"], "required_occupancy": True},
        {"orbit_id": "b", "site_indices": [1], "allowed_species": ["Li", "Na"], "required_occupancy": True},
    ]
    allocation.encode()
    return allocation


def test_requested_k_and_policy_parse_in_solve_request_schema() -> None:
    schema = json.loads((Path(__file__).resolve().parents[1] / "docs" / "mcp" / "MCP_SCHEMA.json").read_text(encoding="utf-8"))["solve_request"]
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "LiNa"},
            "design_space": {
                "template": {"lattice": {"a": 4, "b": 4, "c": 4, "alpha": 90, "beta": 90, "gamma": 90}},
                "sites": {"mode": "explicit_fractional_sites", "explicit_fractional_sites": [[0, 0, 0], [0.25, 0.25, 0.25]]},
            },
            "objective": {"type": "none"},
        },
        "constraints": [], "guidance": [], "solver": {"name": "gurobi"},
        "search": {"requested_k": 2, "distinctness_policy": "STRUCTURE_DISTINCT", "scaffold_ids": ["a", "b"]},
    }
    assert list(Draft202012Validator(schema).iter_errors(request)) == []


def test_no_good_decoder_hash_and_result_serialization_are_stable() -> None:
    allocation = _allocation()
    result = enumerate_top_k(allocation, 2, distinctness_policy="ASSIGNMENT_DISTINCT")
    assert len(allocation.m.top_k_no_good_cuts) == 2
    assert result.no_good_cuts_added == 2
    assert result.assignment_unique_count == 2
    assert len({candidate["assignment_sha256"] for candidate in result.selected_candidates}) == 2
    assert len({candidate["cif_sha256"] for candidate in result.selected_candidates}) == 2
    payload = result.to_dict()
    serialized = json.dumps(payload, sort_keys=True)
    assert '"distinctness_policy": "ASSIGNMENT_DISTINCT"' in serialized
    assert '"canonical_hash_unique_count": 2' in serialized


def test_candidate_decoder_returns_exact_site_vector_after_real_solve() -> None:
    allocation = _allocation()
    result = enumerate_top_k(allocation, 1, distinctness_policy="ASSIGNMENT_DISTINCT")
    decoded = tuple(result.selected_candidates[0]["assignment"])
    assert decoded in {("Li", "Na"), ("Na", "Li")}
    assert len(decoded) == len(allocation.positions)


def test_multi_scaffold_attempts_preserve_separate_top_k_artifacts() -> None:
    base = get_scaffold("nzp_nazr2po43_r3c")
    records = {name: replace(base, scaffold_id=name) for name in ("a", "b")}

    def solve_attempt(scaffold, occupation):
        top_k = enumerate_top_k(_allocation(), 2, distinctness_policy="ASSIGNMENT_DISTINCT")
        return {
            "solve_status": "OPTIMAL", "validation_passed": True,
            "objective": 0.0, "validation_rank": 1,
            "certificate": {"top_k": top_k.to_dict()},
            "artifacts": {"candidate_hashes": [item["cif_sha256"] for item in top_k.selected_candidates]},
        }

    result = run_scaffold_hypotheses(
        "NaZr2P3O12", ["a", "b"], selection_policy="RETURN_ALL_VALID",
        solve_attempt=solve_attempt, scaffold_loader=records.__getitem__,
    )
    assert result.feasible_scaffold_count == 2
    assert result.selected_scaffold_ids == ("a", "b")
    assert all(len(attempt["artifacts"]["candidate_hashes"]) == 2 for attempt in result.attempts)
