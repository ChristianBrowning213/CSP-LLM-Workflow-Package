from __future__ import annotations

import pytest

from sok_llm_orchestrator.workflow.runner import (
    MAX_GENERIC_CANDIDATE_SITES,
    MAX_ORDERED_SCAFFOLD_SITES,
    WorkflowStageError,
    _explicit_site_runtime_limits,
)


def _sites(count: int, *, ordered: bool) -> dict:
    coordinates = [[index / count, 0.0, 0.0] for index in range(count)]
    result = {
        "mode": "explicit_fractional_sites",
        "explicit_fractional_sites": coordinates,
    }
    if ordered:
        midpoint = count // 2
        result["ordered_orbits"] = [
            {
                "orbit_id": "left",
                "site_indices": list(range(midpoint)),
                "allowed_species": ["Li"],
                "fixed_species": "Li",
                "required_occupancy": True,
            },
            {
                "orbit_id": "right",
                "site_indices": list(range(midpoint, count)),
                "allowed_species": ["Na"],
                "fixed_species": "Na",
                "required_occupancy": True,
            },
        ]
    return result


def _design_space(count: int, *, ordered: bool) -> dict:
    return {
        "template": {
            "name": "synthetic-boundary-fixture",
            "lattice": {
                "a": 20.0,
                "b": 20.0,
                "c": 20.0,
                "alpha": 90.0,
                "beta": 90.0,
                "gamma": 90.0,
                "units": "angstrom",
            },
        },
        "sites": _sites(count, ordered=ordered),
    }


def _ordered_request(count: int) -> dict:
    design_space = _design_space(count, ordered=True)
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": f"Li{count // 2}Na{count // 2}"},
            "design_space": design_space,
            "objective": {"type": "none"},
        },
        "constraints": [],
        "guidance": [],
        "guidance_mode": "weighted_sum",
        "solver": {"name": "gurobi"},
        "artifacts": {"return_cif": False},
        "runtime": _explicit_site_runtime_limits(design_space),
        "context": {"run_id": "ordered-site-limit-fixture"},
    }


def test_generic_explicit_candidate_grid_keeps_64_site_limit() -> None:
    assert MAX_GENERIC_CANDIDATE_SITES == 64
    assert _explicit_site_runtime_limits(_design_space(64, ordered=False))["max_sites"] == 64

    with pytest.raises(WorkflowStageError) as captured:
        _explicit_site_runtime_limits(_design_space(65, ordered=False))

    assert captured.value.code == "GENERIC_CANDIDATE_SITE_LIMIT_EXCEEDED"
    assert "generic explicit candidate grid" in str(captured.value)
    assert "received 65" in str(captured.value)
    assert "allowed limit is 64" in str(captured.value)
    assert captured.value.details["received_site_count"] == 65
    assert captured.value.details["allowed_site_limit"] == 64


@pytest.mark.parametrize("site_count", [64, 80, 96, 128])
def test_ordered_scaffold_accepts_inclusive_128_site_boundary(site_count: int) -> None:
    assert MAX_ORDERED_SCAFFOLD_SITES == 128
    limits = _explicit_site_runtime_limits(_design_space(site_count, ordered=True))
    assert limits["max_sites"] == 128


def test_ordered_scaffold_rejects_above_128_with_specific_error() -> None:
    with pytest.raises(WorkflowStageError) as captured:
        _explicit_site_runtime_limits(_design_space(129, ordered=True))

    assert captured.value.code == "ORDERED_SCAFFOLD_SITE_LIMIT_EXCEEDED"
    assert "ordered scaffold" in str(captured.value)
    assert "received 129" in str(captured.value)
    assert "allowed limit is 128" in str(captured.value)
    assert captured.value.details["received_site_count"] == 129
    assert captured.value.details["allowed_site_limit"] == 128


@pytest.mark.parametrize("site_count", [80, 96])
def test_large_ordered_request_preserves_full_orbit_domain(site_count: int) -> None:
    from qlip.core.validate import validate_request

    request = _ordered_request(site_count)
    report = validate_request(request, strict=True)

    assert report.valid, [error.to_dict() for error in report.errors]
    normalized_sites = report.normalized_request["problem"]["design_space"]["sites"]
    assert len(normalized_sites["explicit_fractional_sites"]) == site_count
    claimed = [
        index
        for orbit in normalized_sites["ordered_orbits"]
        for index in orbit["site_indices"]
    ]
    assert len(claimed) == site_count
    assert sorted(claimed) == list(range(site_count))
    assert len(set(claimed)) == site_count
