from __future__ import annotations

from sok_llm_orchestrator.spp.shrink_controls import apply_shrink_controls


def test_spp_shrink_controls_filter_bad_distances() -> None:
    rows = [
        {"pair": "A-B", "distance": 0.8},
        {"pair": "A-B", "distance": 2.0},
        {"pair": "A-B", "distance": 9.0},
    ]
    filtered, meta = apply_shrink_controls(rows, min_distance=1.0, max_distance=6.0)
    assert len(filtered) == 1
    assert meta["short_suppressed"] == 1
    assert meta["long_suppressed"] == 1
