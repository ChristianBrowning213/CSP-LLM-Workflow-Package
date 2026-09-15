from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.qlip_builders import build_solve_request
from sok_llm_orchestrator.contracts.qlip_schema import QLIPValidationError, validate_solve_request
from sok_llm_orchestrator.orchestrator.pipeline import run_csp_pipeline


def test_unknown_top_level_key_rejected() -> None:
    request = build_solve_request("TiO2", None)
    request["unexpected"] = 1
    try:
        validate_solve_request(request)
    except QLIPValidationError as exc:
        assert "/" in str(exc)
    else:
        raise AssertionError("Expected strict validation failure.")


def test_energy_spp_unknown_param_rejected() -> None:
    request = build_solve_request("TiO2", "runs/x/spp_pkg")
    request["guidance"][0]["params"]["unexpected"] = 1
    try:
        validate_solve_request(request)
    except QLIPValidationError as exc:
        assert "/guidance/0/params" in str(exc)
    else:
        raise AssertionError("Expected strict plugin params validation failure.")


def test_spp_energy_objective_family_is_backward_compatible() -> None:
    request = build_solve_request("TiO2", None)
    validate_solve_request(request)
    request["problem"]["objective"] = {"type": "spp_energy"}
    validate_solve_request(request)


def test_pipeline_fails_schema_before_qlip_call(workdir: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CRYSTAL_ALLOW_EXPORT", "1")
    settings = Settings.from_sources(None)
    settings.workspace_root = workdir
    settings.allowed_read_roots = [workdir]
    settings.allowed_write_roots = [workdir]

    result = run_csp_pipeline(
        query="TiO2",
        with_spp=True,
        mode="stub",
        workspace=workdir,
        settings=settings,
        qlip_request_mutator=lambda request: {**request, "unexpected": True},
    )
    assert result.status == "FAILED_SCHEMA"
    log_path = result.run_dir / "tool_call_log.jsonl"
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert not any(line["tool_name"].startswith("qlip.") for line in lines)
