from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from sca.cli import app


runner = CliRunner()


def test_literature_comparison_cli_writes_json_and_markdown_with_missing_sun(tmp_path: Path) -> None:
    run_root = _fake_run_root(tmp_path)
    comparators = _comparators(tmp_path)
    markdown = tmp_path / "LITERATURE_COMPARISON_REPORT.md"
    json_out = tmp_path / "LITERATURE_COMPARISON_REPORT.json"

    result = runner.invoke(
        app,
        [
            "build-literature-comparison-report",
            "--run-root",
            str(run_root),
            "--comparators",
            str(comparators),
            "--out-markdown",
            str(markdown),
            "--out-json",
            str(json_out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert markdown.exists()
    assert json_out.exists()

    data = json.loads(json_out.read_text(encoding="utf-8"))
    assert data["headline_metrics"]["parse_validity_rate"]["value"] == 1.0
    assert data["headline_metrics"]["pre_dft_validity_rate"]["value"] == 0.5
    assert data["headline_metrics"]["bad_contact_rate"]["value"] == 0.5
    assert data["headline_metrics"]["novelty"]["display"] == "not_checked/not_computable"
    assert data["headline_metrics"]["stability"]["display"] == "not_computable"
    assert data["symmetry_intent_summary"]["space_group_exact_match_rate"]["value"] == 0.25
    assert data["symmetry_intent_summary"]["mean_symmetry_score"]["value"] == 0.5
    assert data["mlip_surrogate_summary"]["chgnet_static_ok_rate"]["value"] == 1.0
    assert data["mlip_surrogate_summary"]["relax_status"]["display"] == "unavailable"
    assert len(data["comparator_groups"]["needs_manual_check"]) == 1
    assert len(data["comparator_groups"]["not_comparable_without_reference_cifs"]) == 1
    assert len(data["comparator_groups"]["not_comparable_without_stability_hull_relaxation"]) == 1
    assert data["unique_verifiable_csp_summary"]["audit_bundle_score"]["status"] == "unavailable"

    text = markdown.read_text(encoding="utf-8")
    assert "Needs Manual Check" in text
    assert "Unique / Verifiable CSP Summary" in text
    assert "Symmetry Intent Benchmark Summary" in text
    assert "CrysText Contextual Symmetry Anchors" in text
    assert "CHGNet MLIP Surrogate Summary" in text
    assert "Rows in this section are cautions only" in text
    assert "Our run is not an MP-20/MPTS-52 leaderboard run." in text
    assert "Do not claim wins over MP-20, Lang2Str, or CrysText" in text
    assert "https://example.test/crystext" in text


def _fake_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    (run_root / "reports").mkdir(parents=True)
    (run_root / "sca_direct_benchmark").mkdir()
    (run_root / "sca_intent_benchmark").mkdir()
    (run_root / "sca_unique_benchmark").mkdir()
    (run_root / "symmetry_intent_benchmark").mkdir()
    (run_root / "stability_chgnet_static").mkdir()
    (run_root / "stability_chgnet_relax").mkdir()
    (run_root / "reports" / "FULL_100_INTENT_BENCHMARK_SUMMARY.json").write_text(
        json.dumps(
            {
                "parse_validity_rate": 1.0,
                "pre_dft_validity_rate": None,
                "bad_contact_rate": None,
                "intent_satisfaction_score_mean": 0.8,
                "intent_formula_satisfaction_rate": 1.0,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {"parse_ok": True, "pre_dft_valid": True, "num_bad_contacts": 0},
            {"parse_ok": True, "pre_dft_valid": False, "num_bad_contacts": 2},
        ]
    ).to_csv(run_root / "sca_direct_benchmark" / "benchmark_results.csv", index=False)
    pd.DataFrame(
        [
            {
                "parse_ok": True,
                "intent_formula_satisfied": True,
                "intent_satisfaction_score": 0.75,
                "target_structure_family": "rocksalt",
            },
            {
                "parse_ok": True,
                "intent_formula_satisfied": True,
                "intent_satisfaction_score": 0.85,
                "target_structure_family": "perovskite",
            },
        ]
    ).to_csv(run_root / "sca_intent_benchmark" / "intent_results.csv", index=False)
    (run_root / "symmetry_intent_benchmark" / "symmetry_summary.json").write_text(
        json.dumps(
            {
                "space_group_exact_match_rate": 0.25,
                "crystal_system_match_rate": 0.75,
                "family_symmetry_compatible_rate": 1.0,
                "mean_symmetry_score": 0.5,
            }
        ),
        encoding="utf-8",
    )
    (run_root / "stability_chgnet_static" / "chgnet_static_summary.json").write_text(
        json.dumps(
            {
                "chgnet_ok_rate": 1.0,
                "chgnet_energy_per_atom": {"median": -1.2},
                "max_force_ev_per_angstrom": {"median": 7.0, "mean": 8.0, "max": 12.0},
            }
        ),
        encoding="utf-8",
    )
    (run_root / "stability_chgnet_relax" / "chgnet_relax_summary.json").write_text(
        json.dumps({"relax_ok_rate": 0.0, "status": "unavailable"}),
        encoding="utf-8",
    )
    return run_root


def _comparators(tmp_path: Path) -> Path:
    path = tmp_path / "comparators.csv"
    pd.DataFrame(
        [
            {
                "paper_name": "CrysText",
                "system_name": "CrysText-RL",
                "source_title": "CrysText",
                "source_url": "https://example.test/crystext",
                "year": 2025,
                "task_type": "text_conditioned_generation",
                "dataset_scope": "paper_reported",
                "metric_name_normalized": "composition_and_sg_match_rate",
                "metric_name_as_reported": "joint satisfaction",
                "value": 0.76,
                "unit": "",
                "direction": "higher_is_better",
                "attempts": "",
                "sample_count": "",
                "status": "ok",
                "quote_or_source_note": "short source note",
                "comparability_to_our_100_prompt_run": "contextual_only",
                "reason": "same family but different prompts",
            },
            {
                "paper_name": "Lang2Str",
                "system_name": "Lang2Str",
                "source_title": "Lang2Str",
                "source_url": "https://example.test/lang2str",
                "year": 2026,
                "task_type": "CSP_from_formula",
                "dataset_scope": "MP-20",
                "metric_name_normalized": "structure_match_rate",
                "metric_name_as_reported": "MR",
                "value": 0.6392,
                "unit": "",
                "direction": "higher_is_better",
                "attempts": "",
                "sample_count": "",
                "status": "ok",
                "quote_or_source_note": "short source note",
                "comparability_to_our_100_prompt_run": "not_comparable",
                "reason": "requires reference CIFs",
            },
            {
                "paper_name": "Chemeleon",
                "system_name": "Chemeleon",
                "source_title": "Chemeleon",
                "source_url": "https://example.test/chemeleon",
                "year": 2025,
                "task_type": "property_conditioned_generation",
                "dataset_scope": "Li-P-S-Cl",
                "metric_name_normalized": "metastable_count",
                "metric_name_as_reported": "metastable",
                "value": 435,
                "unit": "count",
                "direction": "higher_is_better",
                "attempts": "",
                "sample_count": "",
                "status": "ok",
                "quote_or_source_note": "short source note",
                "comparability_to_our_100_prompt_run": "not_comparable",
                "reason": "requires hull workflow",
            },
            {
                "paper_name": "CrysText",
                "system_name": "CrysText-RL",
                "source_title": "CrysText",
                "source_url": "https://example.test/crystext",
                "year": 2025,
                "task_type": "text_conditioned_generation",
                "dataset_scope": "paper_reported",
                "metric_name_normalized": "composition_match_rate",
                "metric_name_as_reported": "composition satisfaction",
                "value": "",
                "unit": "",
                "direction": "higher_is_better",
                "attempts": "",
                "sample_count": "",
                "status": "needs_manual_check",
                "quote_or_source_note": "not confidently extracted",
                "comparability_to_our_100_prompt_run": "contextual_only",
                "reason": "manual check needed",
            },
        ]
    ).to_csv(path, index=False)
    return path
