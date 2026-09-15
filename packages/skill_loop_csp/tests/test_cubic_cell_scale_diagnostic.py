from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_cubic_cell_scale.py"
SPEC = importlib.util.spec_from_file_location("cubic_cell_scale_diagnostic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
diagnostic = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = diagnostic
SPEC.loader.exec_module(diagnostic)


def test_edge_volume_and_grid_spacing() -> None:
    assert diagnostic.edge_volume(4.0) == pytest.approx(64.0)
    assert diagnostic.edge_grid_spacing(4.0) == pytest.approx(1.0)


def test_absolute_and_multiplier_sweeps() -> None:
    assert diagnostic.absolute_edge_sweep([3.9, 4.0, 4.2]) == (3.9, 4.0, 4.2)
    assert diagnostic.multiplier_edge_sweep(4.0, [1.0, 1.1, 1.3]) == pytest.approx((4.0, 4.4, 5.2))
    with pytest.raises(ValueError, match="duplicates"):
        diagnostic.absolute_edge_sweep([4.0, 4.0])


def test_invariant_enforcement_and_held_out_preservation() -> None:
    invariant = {"request": "x", "held_out_reference": "mp-target", "solver": {"threads": 1}}
    result = diagnostic.audit_invariant_variants(invariant, [4.0, 4.2])
    assert result["status"] == "PASS"
    assert result["held_out_reference_excluded"] is True
    assert len(set(result["variant_invariant_hashes"].values())) == 1


def test_no_source_overlap_and_dynamic_cell_does_not_mutate_input() -> None:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "source"
        source.mkdir()
        with pytest.raises(ValueError, match="must not overlap"):
            diagnostic.assert_output_separate(source / "child", [source])
    original = {
        "cell_mode": "retrieval_feasible_cell_v1", "a": 3.9, "b": 3.9, "c": 3.9,
        "alpha": 90.0, "beta": 90.0, "gamma": 90.0, "grid_density": 4,
        "grid_spacing_A": 0.975, "n_target_atoms": 6, "vpa_source": "x",
        "vpa_value_A3_per_atom": 10.0, "cell_volume_A3": 59.319, "provenance": {"frozen": True},
    }
    snapshot = json.loads(json.dumps(original))
    changed = diagnostic.cubic_dynamic_cell(original, 4.6, "edge_4p600")
    assert original == snapshot
    assert changed["a"] == changed["b"] == changed["c"] == 4.6


def test_topology_aggregation_and_transition_classification() -> None:
    rows = [
        {"row_id": "x", "scale_multiplier": 1.0, "topology_status": "FAIL"},
        {"row_id": "x", "scale_multiplier": 1.1, "topology_status": "PARTIAL"},
        {"row_id": "x", "scale_multiplier": 1.2, "topology_status": "PASS"},
        {"row_id": "y", "scale_multiplier": 1.0, "topology_status": "PARTIAL"},
        {"row_id": "y", "scale_multiplier": 1.2, "topology_status": "PASS"},
    ]
    assert diagnostic.aggregate_best_transitions(rows) == {"FAIL_TO_PASS": 1, "PARTIAL_TO_PASS": 1}
    stage1 = [
        {"edge_A": 3.9, "topology_status": "PARTIAL", "minimum_distance_A": 1.3},
        {"edge_A": 4.1, "topology_status": "PARTIAL", "minimum_distance_A": 1.5},
        {"edge_A": 4.3, "topology_status": "PASS", "minimum_distance_A": 1.9},
        {"edge_A": 4.5, "topology_status": "PASS", "minimum_distance_A": 2.0},
    ]
    decision = diagnostic.classify_stage1_transition(stage1)
    assert decision["classification"] == "REPRESENTABILITY_THRESHOLD"
    assert decision["stage2_triggered"] is True
    assert decision["threshold_interval_A"] == [4.1, 4.3]


def _fake_row(root: Path, row_id: str, topology: str, formula: str = "LiCoO2") -> None:
    row = root / row_id
    for directory in ("cell", "generated", "input", "qlip", "retrieval/neighbours", "sca", "spp/potentials/Li-O", "structured_task"):
        (row / directory).mkdir(parents=True, exist_ok=True)
    required_json = {
        "cell/dynamic_cell.json": {"a": 4.0},
        "input/effective_config.json": {"target_reference_id": f"ref-{row_id}", "exclude_target_reference": True, "grid_density": 4, "solver_time_limit_s": 300},
        "input/input_row.json": {}, "qlip/solver_result.json": {},
        "retrieval/retrieval_manifest.json": {"selected": []},
        "sca/result.json": {"topology_status": topology},
        "sca/summary.json": {}, "structured_task/structured_task.json": {"formula": formula},
    }
    for relative, payload in required_json.items():
        (row / relative).write_text(json.dumps(payload), encoding="utf-8")
    (row / "generated/candidate.cif").write_text("candidate", encoding="utf-8")
    (row / "input/request.txt").write_text("request", encoding="utf-8")
    (row / "retrieval/neighbour_hashes.csv").write_text("x\n", encoding="utf-8")
    (row / "spp/pair_manifest.csv").write_text("x\n", encoding="utf-8")
    (row / "spp/potentials/Li-O/Li-O.POT").write_text("pot", encoding="utf-8")
    pot_hash = diagnostic.sha256_file(row / "spp/potentials/Li-O/Li-O.POT")
    request_spp = {"request_spp_hashes": {"Li-O/Li-O.POT": pot_hash}, "quality": {"request_pair_results": []}}
    (row / "spp/request_spp_cache.json").write_text(json.dumps(request_spp), encoding="utf-8")


def test_deterministic_panel_selection() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        _fake_row(root, "layered_007", "PARTIAL", "Li2FeO3")
        for index in range(1, 7):
            _fake_row(root, f"layered_{index:03d}", "FAIL")
        for row_id, status in (("spinel_051", "PARTIAL"), ("spinel_052", "PARTIAL"), ("spinel_053", "PASS"), ("spinel_054", "PASS"), ("spinel_055", "PARTIAL")):
            _fake_row(root, row_id, status, "ZnFe2O4")
        selected = diagnostic.deterministic_panel_selection(root)
    assert [row["row_id"] for row in selected] == [
        "layered_007", "layered_001", "layered_002", "layered_003", "layered_004", "layered_005",
        "spinel_051", "spinel_052", "spinel_055", "spinel_053", "spinel_054",
    ]
