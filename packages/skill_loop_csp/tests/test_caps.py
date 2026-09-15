from __future__ import annotations

import pytest

from sok_llm_orchestrator.safety.caps import Caps, CapViolationError, enforce_requested_caps, enforce_result_caps


def test_timeout_cap_rejected() -> None:
    caps = Caps(max_cif_count=10, max_runtime_seconds=5, max_output_bytes=1000)
    with pytest.raises(CapViolationError, match="timeout_seconds"):
        enforce_requested_caps({"timeout_seconds": 7}, caps)


def test_result_cap_rejected() -> None:
    caps = Caps(max_cif_count=1, max_runtime_seconds=100, max_output_bytes=50)
    with pytest.raises(CapViolationError, match="cif_count"):
        enforce_result_caps({"cif_count": 2, "output_bytes": 10}, caps)
