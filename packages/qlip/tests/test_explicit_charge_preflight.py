from __future__ import annotations

from qlip.core.chemistry import preflight_charge
from qlip.core.validate import validate_request


def _request(chemistry):
    return {
        "version": "1.0",
        "problem": {
            "chemistry": chemistry,
            "design_space": {
                "template": {"lattice": {"a": 4, "b": 4, "c": 4, "alpha": 90, "beta": 90, "gamma": 90}},
                "sites": {"mode": "explicit_fractional_sites", "explicit_fractional_sites": [[0, 0, 0], [0.5, 0.5, 0.5]]},
            },
            "objective": {"type": "none"},
        },
        "solver": {"name": "gurobi"},
    }


def test_explicit_required_neutral_chemistry_passes() -> None:
    result = preflight_charge({
        "formula": "NaCl", "charge_policy": "EXPLICIT_REQUIRED",
        "oxidation_states": {"Na": 1, "Cl": -1},
        "compensation_operation": "none", "assumptions_source": "benchmark task",
    })
    assert result.accepted and result.charge_neutral
    assert result.charge_sum == 0


def test_explicit_required_non_neutral_chemistry_is_rejected() -> None:
    chemistry = {
        "formula": "NaCl", "charge_policy": "EXPLICIT_REQUIRED",
        "oxidation_states": {"Na": 1, "Cl": 1},
    }
    result = preflight_charge(chemistry)
    assert not result.accepted and result.charge_sum == 2
    report = validate_request(_request(chemistry), strict=True)
    assert "explicit_chemistry_rejected" in {issue.code for issue in report.errors}


def test_required_policy_rejects_missing_species_assumption() -> None:
    result = preflight_charge({
        "formula": "NaCl", "charge_policy": "EXPLICIT_REQUIRED", "oxidation_states": {"Na": 1},
    })
    assert not result.accepted
    assert "missing" in (result.rejection_reason or "")


def test_informational_policy_records_non_neutral_sum_without_enforcing() -> None:
    result = preflight_charge({
        "formula": "NaCl", "charge_policy": "EXPLICIT_INFORMATIONAL",
        "oxidation_states": {"Na": 1, "Cl": 1},
    })
    assert result.accepted
    assert result.charge_neutral is False
    assert result.charge_sum == 2


def test_not_enforced_policy_does_not_infer_states() -> None:
    result = preflight_charge({"formula": "NaCl", "charge_policy": "NOT_ENFORCED"})
    assert result.accepted
    assert result.oxidation_states_used == {}
    assert result.charge_sum is None
    assert result.charge_neutral is None
