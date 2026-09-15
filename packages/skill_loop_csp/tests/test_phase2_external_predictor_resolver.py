from __future__ import annotations

import pytest

from sok_llm_orchestrator.contracts.phase2_external_predictors import (
    Phase2ExternalPredictorResolutionError,
    normalize_phase2_external_predictor_request,
    resolve_phase2_external_predictor_request,
)


def test_phase2_external_predictor_resolver_accepts_implemented_alias() -> None:
    entry = resolve_phase2_external_predictor_request("mean_atomic_number")
    assert entry.id == "phase2.external.pymatgen_composition_descriptor"
    assert entry.implementation_status == "implemented_now"


def test_phase2_external_predictor_request_normalizes_to_canonical_id() -> None:
    payload = normalize_phase2_external_predictor_request(
        {"predictor_id": "pymatgen_composition_descriptor", "target": "mean_atomic_mass"}
    )
    assert payload == {
        "schema_version": "phase2.external_predictor_request.v1",
        "predictor_id": "phase2.external.pymatgen_composition_descriptor",
        "target": "mean_atomic_mass",
        "use": "reporting",
        "value_state": "raw",
    }


def test_phase2_external_predictor_resolver_rejects_unknown() -> None:
    with pytest.raises(Phase2ExternalPredictorResolutionError) as exc:
        resolve_phase2_external_predictor_request("unicorn_predictor")
    assert exc.value.code == "PHASE2_UNKNOWN_EXTERNAL_PREDICTOR"


def test_phase2_external_predictor_resolver_rejects_nonimplemented() -> None:
    with pytest.raises(Phase2ExternalPredictorResolutionError) as exc:
        resolve_phase2_external_predictor_request("phase2.external.matminer_formation_energy_rf")
    assert exc.value.code == "PHASE2_EXTERNAL_PREDICTOR_NOT_IMPLEMENTED"
