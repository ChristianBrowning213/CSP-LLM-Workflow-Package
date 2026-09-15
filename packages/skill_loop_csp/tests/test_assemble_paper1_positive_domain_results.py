from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "assemble_paper1_positive_domain_results.py"
SPEC = importlib.util.spec_from_file_location("assemble_paper1", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def test_family_of() -> None:
    assert mod.family_of("rocksalt_b1_001_agbr") == "rocksalt_b1"
    assert mod.family_of("fluorite_antifluorite_015_baf2") == "fluorite_antifluorite"
    assert mod.family_of("oxide_perovskite_016_bapao3") == "oxide_perovskite"


def _primary_rows() -> list[dict]:
    rows = []
    for i in range(3):
        rows.append({
            "row_id": f"rocksalt_b1_00{i + 1}_x", "family": "rocksalt_b1", "executable": True,
            "generation_state": "GENERATED", "solver_status": "OPTIMAL", "parse_ok": "True",
            "composition_match": "True", "geometry_valid": "True", "bad_contacts": "0",
            "sca_topology_result": "PARTIAL", "family_recovery_verdict": "FAMILY_FAIL",
        })
    rows.append({
        "row_id": "rocksalt_b1_004_ac", "family": "rocksalt_b1", "executable": False,
        "generation_state": "", "solver_status": "", "parse_ok": "", "composition_match": "",
        "geometry_valid": "", "bad_contacts": "", "sca_topology_result": "",
        "family_recovery_verdict": "NO_CANDIDATE",
    })
    return rows


def test_generation_summary_counts_coverage_failures() -> None:
    summary = {s["family"]: s for s in mod.family_generation_summary(_primary_rows())}
    rock = summary["rocksalt_b1"]
    assert rock["frozen_targets"] == 4
    assert rock["candidates"] == 3
    assert rock["optimal"] == 3
    assert rock["coverage_fail"] == 1
    assert rock["other_fail"] == 0
    assert summary["__all__"]["frozen_targets"] == 4


def test_topology_summary_marks_sca_coverage() -> None:
    summary = {s["family"]: s for s in mod.family_topology_summary(_primary_rows())}
    assert summary["rocksalt_b1"]["sca_topology_coverage"] == "policy"
    assert summary["rocksalt_b1"]["family_recovery_fail"] == 3


def test_validation_summary_is_rate_string() -> None:
    summary = {s["family"]: s for s in mod.family_validation_summary(_primary_rows())}
    assert summary["rocksalt_b1"]["composition_match"] == "3/3"


def test_ablation_level2_matched_only() -> None:
    ablation_rows = [
        {"row_id": "a", "both_generated": True, "B_family_recovery": "FAMILY_PASS",
         "C_family_recovery": "FAMILY_PASS", "B_detected_sg": "Pm-3m", "C_detected_sg": "Pm-3m"},
        {"row_id": "b", "both_generated": True, "B_family_recovery": "FAMILY_PASS",
         "C_family_recovery": "NOT_CLASSIFIABLE", "B_detected_sg": "Pm-3m", "C_detected_sg": "P4mm"},
        {"row_id": "c", "both_generated": False, "B_family_recovery": "", "C_family_recovery": "FAMILY_PASS",
         "B_detected_sg": "", "C_detected_sg": "Pm-3m"},
    ]
    level2 = mod.ablation_level2(ablation_rows)
    assert level2["matched_rows"] == 2
    assert level2["B_family_pass"] == 2
    assert level2["C_family_pass"] == 1
    assert level2["family_recovery_agreement"] == 1
    assert level2["detected_sg_agreement"] == 1
