from __future__ import annotations

import json
import sys
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_solve_request
from sok_llm_orchestrator.contracts.spp_regularisation import (
    CONFIG_C_MISSING_PAIR_POLICY,
    CONFIG_C_REGULARISATION_SPP_DIR,
    CONFIG_C_REGULARISATION_WEIGHT,
    CONFIG_C_SPP_GUIDANCE_WEIGHT,
    apply_regularised_partial_spp_guidance,
    regularised_partial_spp_config,
)


def _settings_for_workspace(workspace: Path, *, regularisation_dir: Path | None = None) -> Settings:
    settings = Settings.from_sources(None)
    settings.workspace_root = workspace
    settings.allowed_read_roots = [workspace.resolve(), Path.cwd().resolve()]
    settings.allowed_write_roots = [workspace.resolve()]
    if regularisation_dir is not None:
        settings.qlip_allowed_path_roots = [regularisation_dir.resolve()]
    return settings


def _regularisation_overrides(regularisation_dir: Path) -> dict[str, object]:
    return {
        "allow_partial_spp_guidance": True,
        "allow_qlip_without_spp": True,
        "spp_guidance_weight": CONFIG_C_SPP_GUIDANCE_WEIGHT,
        "runtime_spp_guidance_weight": CONFIG_C_SPP_GUIDANCE_WEIGHT,
        "spp_regularisation_dir": str(regularisation_dir.resolve()),
        "spp_regularisation_weight": CONFIG_C_REGULARISATION_WEIGHT,
        "spp_missing_pair_policy": CONFIG_C_MISSING_PAIR_POLICY,
    }


def _run_pipeline_once(**kwargs):
    try:
        from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline

        return run_csp_pipeline(**kwargs)
    finally:
        sys.modules.pop("sok_llm_orchestrator.orchestrator.pipeline", None)


def test_regularised_partial_spp_guidance_builds_strict_live_request() -> None:
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "BaTiO3"},
            "design_space": {
                "template": {"lattice": {"a": 4.0, "b": 4.0, "c": 4.0}},
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
            "objective": {"type": "none"},
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }
    overrides = {
        "allow_partial_spp_guidance": True,
        "allow_qlip_without_spp": True,
        "spp_guidance_weight": CONFIG_C_SPP_GUIDANCE_WEIGHT,
        "spp_regularisation_dir": CONFIG_C_REGULARISATION_SPP_DIR,
        "spp_regularisation_weight": CONFIG_C_REGULARISATION_WEIGHT,
        "spp_missing_pair_policy": CONFIG_C_MISSING_PAIR_POLICY,
    }

    patched = apply_regularised_partial_spp_guidance(request, formula="BaTiO3", overrides=overrides)

    validate_solve_request(patched)
    guidance = patched["guidance"][0]
    assert guidance["id"] == "objective.energy_spp"
    assert guidance["weight"] == CONFIG_C_SPP_GUIDANCE_WEIGHT
    assert guidance["params"]["mode"] == "partial"
    assert guidance["params"]["regularisation_spp_dir"] == CONFIG_C_REGULARISATION_SPP_DIR
    assert guidance["params"]["regularisation_weight"] == CONFIG_C_REGULARISATION_WEIGHT
    assert guidance["params"]["missing_pair_policy"] == CONFIG_C_MISSING_PAIR_POLICY
    assert "Ba-Ba" in guidance["params"]["missing_pairs"]
    assert "Ba-O" in guidance["params"]["missing_pairs"]
    assert "O-Ti" in guidance["params"]["missing_pairs"]


def test_pipeline_uses_regularisation_fallback_when_local_spp_export_unavailable(workdir: Path) -> None:
    regularisation_dir = workdir / "global_spp"
    regularisation_dir.mkdir(parents=True)
    run = _run_pipeline_once(
        query="Generate a plausible BaTiO3 perovskite oxide candidate",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=_settings_for_workspace(workdir, regularisation_dir=regularisation_dir),
        execution_overrides=_regularisation_overrides(regularisation_dir),
    )

    assert run.status == "SUCCEEDED"
    manifest = run.manifest_path.read_text(encoding="utf-8")
    assert "spp_corpus_unavailable:no_export_ready_candidate" not in manifest
    fallback = json.loads((run.run_dir / "artifacts" / "spp_regularisation_fallback.json").read_text(encoding="utf-8"))
    assert fallback["local_spp_package_generated"] is False
    assert fallback["regularisation_weight"] == CONFIG_C_REGULARISATION_WEIGHT
    assert fallback["missing_pair_policy"] == CONFIG_C_MISSING_PAIR_POLICY
    assert (run.run_dir / "artifacts" / "qlip_request.json").exists()
    assert (run.run_dir / "artifacts" / "qlip_solve.json").exists()


def test_pipeline_no_local_spp_without_regularisation_fails_with_no_fallback_category(workdir: Path) -> None:
    run = _run_pipeline_once(
        query="Generate a plausible BaTiO3 perovskite oxide candidate",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=_settings_for_workspace(workdir),
    )

    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert run.status == "FAILED"
    assert (
        manifest["failure_reason"]
        == "spp_corpus_unavailable:no_export_ready_candidate_and_no_regularisation_fallback"
    )
    diagnostics = json.loads(
        (run.run_dir / "artifacts" / "spp_corpus_unavailable_diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics["retrieval_candidate_count"] >= 1
    assert diagnostics["export_ready_candidate_count"] == 0
    assert diagnostics["regularisation_fallback"]["configured"] is False
    assert diagnostics["regularisation_fallback"]["path_exists"] is False
    assert diagnostics["settings"]["crystaldb_policy_mode"] == "safe"
    assert not (run.run_dir / "artifacts" / "qlip_request.json").exists()


def test_pipeline_regularisation_fallback_preserves_qlip_diagnostics(
    workdir: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("FAKE_QLIP_SOLVE_ERROR_DIAGNOSTICS", "1")
    regularisation_dir = workdir / "global_spp"
    regularisation_dir.mkdir(parents=True)
    run = _run_pipeline_once(
        query="Generate a plausible BaTiO3 perovskite oxide candidate",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=_settings_for_workspace(workdir, regularisation_dir=regularisation_dir),
        execution_overrides=_regularisation_overrides(regularisation_dir),
    )

    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert run.status == "FAILED"
    assert str(manifest["failure_reason"]).startswith("qlip_outputs_invalid:")
    assert "spp_corpus_unavailable:no_export_ready_candidate" not in str(manifest["failure_reason"])
    assert "objective_terms_missing" not in str(manifest["failure_reason"])
    fallback = json.loads((run.run_dir / "artifacts" / "spp_regularisation_fallback.json").read_text(encoding="utf-8"))
    assert fallback["missing_pair_policy"] == CONFIG_C_MISSING_PAIR_POLICY
    solve_payload = json.loads((run.run_dir / "artifacts" / "qlip_solve.json").read_text(encoding="utf-8"))
    nested = solve_payload["result"]["result"]
    assert nested["status"] == "ERROR"
    assert nested["error"] == "pot_root_missing"
    diagnostics = nested["certificates"]["diagnostics"]
    assert diagnostics["qlip_error"]["code"] == "pot_root_missing"
    assert diagnostics["spp_guidance"]["missing_pair_policy"] == CONFIG_C_MISSING_PAIR_POLICY
    verification = json.loads((run.run_dir / "artifacts" / "verification_report.json").read_text(encoding="utf-8"))
    assert "qlip_solver_status:ERROR" in verification["qlip_outputs"]["errors"]
    assert any(error == "qlip_solver_error:pot_root_missing" for error in verification["qlip_outputs"]["errors"])
    assert verification["qlip_outputs"]["objective_metadata"]["spp_guidance"]["regularisation_weight"] == 2.0


def test_regularised_spp_guidance_with_pot_root_matches_live_contract() -> None:
    pot_root = r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP\QLIP_Outputs\SPP\runs\example\spp_root"
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "BaTiO3"},
            "design_space": {
                "template": {"lattice": {"a": 4.0, "b": 4.0, "c": 4.0}},
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
            "objective": {"type": "none"},
        },
        "constraints": [],
        "guidance": [],
        "solver": {"name": "gurobi"},
    }
    patched = apply_regularised_partial_spp_guidance(
        request,
        formula="BaTiO3",
        overrides={
            "allow_partial_spp_guidance": True,
            "allow_qlip_without_spp": True,
            "spp_guidance_weight": CONFIG_C_SPP_GUIDANCE_WEIGHT,
            "spp_regularisation_dir": CONFIG_C_REGULARISATION_SPP_DIR,
            "spp_regularisation_weight": CONFIG_C_REGULARISATION_WEIGHT,
            "spp_missing_pair_policy": CONFIG_C_MISSING_PAIR_POLICY,
            "spp_pot_root": pot_root,
        },
    )

    validate_solve_request(patched)
    assert patched["problem"]["objective"] == {"type": "spp_energy"}
    assert patched["context"]["pot_root"] == pot_root
    guidance = patched["guidance"][0]
    assert guidance["id"] == "objective.energy_spp"
    assert guidance["params"] == {
        "regularisation_spp_dir": CONFIG_C_REGULARISATION_SPP_DIR,
        "regularisation_weight": CONFIG_C_REGULARISATION_WEIGHT,
    }


def test_bad_spp_guidance_objective_mix_fails_locally() -> None:
    request = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "BaTiO3"},
            "design_space": {
                "template": {"lattice": {"a": 4.0, "b": 4.0, "c": 4.0}},
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
            "objective": {"type": "none"},
        },
        "constraints": [],
        "guidance": [
            {
                "id": "objective.energy_spp",
                "weight": 10.0,
                "params": {
                    "regularisation_spp_dir": CONFIG_C_REGULARISATION_SPP_DIR,
                    "regularisation_weight": CONFIG_C_REGULARISATION_WEIGHT,
                },
            }
        ],
        "solver": {"name": "gurobi"},
    }

    try:
        validate_solve_request(request)
    except QLIPValidationError as exc:
        assert "requires problem.objective.type='spp_energy'" in str(exc)
    else:
        raise AssertionError("Expected objective/guidance contract failure.")


def test_regularised_partial_spp_config_requires_real_regularisation_dir() -> None:
    assert regularised_partial_spp_config({"spp_regularisation_weight": 2.0}) is None
    assert (
        regularised_partial_spp_config(
            {
                "spp_regularisation_dir": str(Path("SPP").resolve()),
                "spp_regularisation_weight": 0.0,
            }
        )
        is None
    )


def test_full_100_runner_import_is_pipeline_safe_and_uses_config_c_defaults() -> None:
    import inspect
    import sys

    sys.modules.pop("sok_llm_orchestrator.orchestrator.pipeline", None)
    from scripts import run_full_100_skill_loop_benchmark as runner

    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    args = runner.build_parser().parse_args(
        [
            "--manifest",
            "benchmarks/full_100_seeded_20260626/full_100_skill_loop_manifest.csv",
            "--out-root",
            "reports/x",
            "--seed",
            "20260626",
        ]
    )
    assert args.spp_guidance_weight == CONFIG_C_SPP_GUIDANCE_WEIGHT
    assert args.regularisation_weight == CONFIG_C_REGULARISATION_WEIGHT
    assert args.missing_pair_policy == CONFIG_C_MISSING_PAIR_POLICY
    assert args.regularisation_spp_dir == CONFIG_C_REGULARISATION_SPP_DIR

    settings = runner._settings_for_run(
        None,
        Path(".pytest_tmp") / "full100_config_reports",
        Path(".pytest_tmp") / "full100_config_workspace",
        Path(CONFIG_C_REGULARISATION_SPP_DIR),
    )
    assert Path(CONFIG_C_REGULARISATION_SPP_DIR).resolve() in settings.qlip_allowed_path_roots

    source = inspect.getsource(runner)
    assert "objective.energy_spp" not in source
    assert "problem.objective" not in source
    assert "context.pot_root" not in source
    assert "supported_pairs" not in source
    assert "missing_pairs" not in source
