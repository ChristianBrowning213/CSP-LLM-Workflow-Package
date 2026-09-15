from __future__ import annotations

import csv
from pathlib import Path

from qlip.paper_diversity.smoke_preparation import load_frozen_e4_tasks, resolve_skill_loop_root


def test_preparation_module_imports_and_resolves_configured_project_root(tmp_path: Path) -> None:
    project = tmp_path / "Skill-Loop-CSP"
    benchmark = project / "benchmarks" / "paper_diversity_v2"
    benchmark.mkdir(parents=True)
    manifest = benchmark / "EXP4_NASICON_32_TASKS.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task_id", "target_formula"])
        writer.writeheader()
        writer.writerow({"task_id": "E4_TEST", "target_formula": "NaCl"})

    assert resolve_skill_loop_root(project) == project.resolve()
    assert load_frozen_e4_tasks(project)["E4_TEST"]["target_formula"] == "NaCl"
