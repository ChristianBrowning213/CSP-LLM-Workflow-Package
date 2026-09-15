from __future__ import annotations

import pytest

from sok_llm_orchestrator.contracts.phase1_properties import (
    Phase1PropertyResolutionError,
    resolve_phase1_property_request,
    resolve_property_bias_key,
)


def test_resolver_accepts_implemented_alias() -> None:
    entry = resolve_phase1_property_request("property x")
    assert entry.id == "qlip.property.property_x_estimate"
    assert entry.implementation_status == "implemented_now"
    assert resolve_property_bias_key("property x") == "property_x"


def test_resolver_rejects_small_wiring_without_opt_in() -> None:
    entry = resolve_phase1_property_request("density")
    assert entry.id == "qlip.native.density_packing_proxy"
    assert entry.implementation_status == "implemented_now"


def test_resolver_allows_small_wiring_with_opt_in() -> None:
    entry = resolve_phase1_property_request("density", allow_small_wiring=True)
    assert entry.id == "qlip.native.density_packing_proxy"
    assert entry.implementation_status == "implemented_now"


def test_resolver_rejects_unknown_request() -> None:
    with pytest.raises(Phase1PropertyResolutionError) as exc:
        resolve_phase1_property_request("unicorn_property")
    assert exc.value.code == "PHASE1_UNKNOWN_PROPERTY_REQUEST"
