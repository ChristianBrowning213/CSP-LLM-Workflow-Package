from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from sok_llm_orchestrator.retrieval.specialist_corpora import load_corpus_registry, resolve_corpus


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_nasicon_corpora_resolve_from_repository_relative_registry():
    registry = load_corpus_registry()
    assert "nasicon_specialist_v1" in registry["corpora"]
    for corpus_id in ("nasicon_specialist_v1", "nasicon_specialist_leave_target_out_v1"):
        resolved = resolve_corpus(corpus_id)
        assert Path(resolved["database"]).is_file()
        assert not Path(registry["corpora"][corpus_id]["database"]).is_absolute()


def test_leave_target_out_database_has_no_exact_target_and_has_both_tiers():
    resolved = resolve_corpus("nasicon_specialist_leave_target_out_v1")
    conn = sqlite3.connect(resolved["database"])
    formulas = {row[0] for row in conn.execute("SELECT reduced_formula FROM structures")}
    tiers = {row[0] for row in conn.execute("SELECT DISTINCT topology_tier FROM structure_annotations")}
    conn.close()
    assert "Na3Zr2Si2PO12" not in formulas
    assert tiers == {"TIER_1_TOPOLOGY", "TIER_2_PAIR_COMPLETION"}


def test_paper_task_records_required_structured_fields():
    task = json.loads((REPO_ROOT / "benchmarks" / "paper_nasicon_specialist" / "task.json").read_text(encoding="utf-8"))
    assert task["target_formula"] == "Na3Zr2Si2PO12"
    assert task["space_group_number"] == 5
    assert task["structure_family"] == "NASICON"
    assert task["scaffold_id"]
    assert len(task["required_spp_pairs"]) == 15
    assert task["validation_policy"]["require_complete_spp_pair_coverage"] is True
