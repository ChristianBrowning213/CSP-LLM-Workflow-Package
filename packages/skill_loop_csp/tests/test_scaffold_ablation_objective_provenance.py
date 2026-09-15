from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPTS / "execute_scaffold_ablation_v1.py"
SPEC = importlib.util.spec_from_file_location("execute_scaffold_ablation_v1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
scripts_path = str(SCRIPTS)
path_was_present = scripts_path in sys.path
if not path_was_present:
    sys.path.insert(0, scripts_path)
try:
    SPEC.loader.exec_module(MODULE)
finally:
    if not path_was_present:
        sys.path.remove(scripts_path)
validate = MODULE.validate_frozen_objective_provenance


def regulator_only_trace() -> dict:
    return {
        "qlip_adapter": {
            "representation": "REGULATOR_AS_PRIMARY_WEIGHTED",
            "guidance_weight": 20.0,
            "primary_pot_root": "C:/frozen/regulator",
        },
        "regulator_root": "C:/frozen/regulator",
        "pair_components": [{
            "species_pair": "Ba-O", "request_pair_status": "REQUEST_DISABLED",
            "request_pair_score": 0.0, "regulator_pair_score": -2.5,
            "combined_pair_score": -50.0,
        }],
        "request_component": 0.0, "regulator_component": -2.5,
        "solver_objective": -50.0, "independent_objective": -50.0,
    }


def request_plus_regulator_trace() -> dict:
    return {
        "qlip_adapter": {
            "representation": "REQUEST_PLUS_REGULATOR_FALLBACK",
            "guidance_weight": 10.0,
        },
        "pair_components": [
            {"species_pair": "Ba-O", "request_pair_status": "REQUEST_USABLE",
             "request_pair_score": -1.0, "regulator_pair_score": -2.0, "combined_pair_score": -50.0},
            {"species_pair": "O-O", "request_pair_status": "REQUEST_MISSING",
             "request_pair_score": 0.0, "regulator_pair_score": -0.5, "combined_pair_score": -10.0},
        ],
        "request_component": -1.0, "regulator_component": -2.5,
        "solver_objective": -60.0, "independent_objective": -60.0,
    }


def test_regulator_only_validates_actual_twenty_times_regulator_objective() -> None:
    result = validate(regulator_only_trace(), request_mode="disabled")
    assert result["expected_total"] == -50.0
    assert result["absolute_difference"] == 0.0


def test_request_plus_regulator_validates_ten_times_request_plus_twice_regulator() -> None:
    result = validate(request_plus_regulator_trace(), request_mode="enabled")
    assert result["expected_total"] == -60.0


def test_request_disabled_rejects_nonzero_request_contribution() -> None:
    trace = regulator_only_trace()
    trace["request_component"] = 0.25
    with pytest.raises(RuntimeError, match="nonzero request contribution"):
        validate(trace, request_mode="disabled")


def test_wrong_regulator_coefficient_is_detected() -> None:
    trace = request_plus_regulator_trace()
    trace["pair_components"][0]["combined_pair_score"] = -70.0
    trace["solver_objective"] = trace["independent_objective"] = -80.0
    with pytest.raises(RuntimeError, match="wrong effective regulator/request coefficient"):
        validate(trace, request_mode="enabled")


def test_wrong_request_weighting_is_detected() -> None:
    trace = request_plus_regulator_trace()
    trace["pair_components"][0]["combined_pair_score"] = -45.0
    trace["solver_objective"] = trace["independent_objective"] = -55.0
    with pytest.raises(RuntimeError, match="wrong effective regulator/request coefficient"):
        validate(trace, request_mode="enabled")


def test_wrong_outer_scale_is_detected() -> None:
    trace = regulator_only_trace()
    trace["qlip_adapter"]["guidance_weight"] = 10.0
    with pytest.raises(RuntimeError, match="wrong outer objective scale"):
        validate(trace, request_mode="disabled")


def test_optional_convenience_fields_are_not_required() -> None:
    trace = regulator_only_trace()
    for key in ("outer_objective_scale", "regulator_coefficient", "request_pot_count", "regulator_pot_count"):
        trace["qlip_adapter"].pop(key, None)
    result = validate(copy.deepcopy(trace), request_mode="disabled")
    assert result["solver_objective"] == -50.0
