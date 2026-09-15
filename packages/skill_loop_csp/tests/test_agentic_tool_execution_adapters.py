from __future__ import annotations

import ast
import inspect
import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

from sok_llm_orchestrator.agentic.tool_execution_adapters import (
    TOOL_EXECUTION_RESULT_SCHEMA_VERSION,
    _client_for_tool,
    _unwrap_mcp_payload,
    get_default_tool_execution_adapters,
)
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.contracts.qlip_builders import MaterialSystemError, build_solve_request
from sok_llm_orchestrator.contracts.qlip_schema import validate_solve_request
import sok_llm_orchestrator.agentic.tool_execution_adapters as adapters_module


@contextmanager
def _local_test_dir(name: str):
    root = Path.cwd() / "test_workdir" / "agentic_exec_tests"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)


def _fake_settings(workdir: Path) -> Settings:
    root = Path(__file__).resolve().parents[1]
    return Settings(
        workspace_root=workdir,
        crystaldb_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_crystaldb_server.py")],
        spp_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_spp_server.py")],
        qlip_mcp_cmd=[sys.executable, "-u", str(root / "tests" / "fakes" / "mcp_qlip_server.py")],
        crystaldb_mcp_cwd=str(root),
        spp_mcp_cwd=str(root),
        qlip_mcp_cwd=str(root),
        crystaldb_policy_mode="demo",
        max_runtime_seconds=30,
    )


def _base_qlip_request(*, pot_root: str | None = None) -> dict[str, object]:
    request: dict[str, object] = {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "CoAs2"},
            "design_space": {
                "template": {"source": "test"},
                "sites": {"mode": "fixed"},
            },
        },
        "constraints": [],
        "guidance": [{"id": "objective.energy_spp", "params": {}}],
        "solver": {"name": "gurobi"},
    }
    if pot_root is not None:
        request["context"] = {"pot_root": pot_root}
    return request


def test_default_tool_execution_adapters_list_all_six_tools() -> None:
    adapters = get_default_tool_execution_adapters()
    assert sorted(adapters) == [
        "crystal.csp_pack",
        "crystal.novelty_check",
        "qlip.solve",
        "qlip.validate_request",
        "spp.package_for_qlip",
        "spp.run_pipeline",
    ]


def test_build_solve_request_prefers_material_system_over_goal_verb() -> None:
    request = build_solve_request(
        "Generate a simple binary sulfide candidate.",
        material_system="ZnS",
    )

    assert request["problem"]["chemistry"]["formula"] == "ZnS"


def test_build_solve_request_can_force_cubic_lattice_template(monkeypatch) -> None:
    monkeypatch.setenv("SKILL_LOOP_FORCE_CUBIC_LATTICE_TEMPLATE", "1")
    monkeypatch.setenv("SKILL_LOOP_CUBIC_LATTICE_A", "5.1")

    request = build_solve_request("Generate a BaTiO3 candidate.", material_system="BaTiO3")
    lattice = request["problem"]["design_space"]["template"]["lattice"]

    assert lattice == {
        "a": 5.1,
        "b": 5.1,
        "c": 5.1,
        "alpha": 90.0,
        "beta": 90.0,
        "gamma": 90.0,
        "units": "angstrom",
    }


def test_build_solve_request_sets_spp_guidance_weight() -> None:
    request = build_solve_request(
        "Generate a BaTiO3 candidate.",
        pot_root="C:/tmp/pots",
        material_system="BaTiO3",
        spp_guidance_weight=10.0,
    )

    assert request["guidance"][0]["id"] == "objective.energy_spp"
    assert request["guidance"][0]["weight"] == 10.0


def test_build_solve_request_preserves_soft_repulsive_missing_pair_policy() -> None:
    request = build_solve_request(
        "Generate a MgAl2O4 spinel candidate.",
        material_system="MgAl2O4",
        partial_spp_guidance={
            "pot_root": "C:/tmp/partial_pots",
            "supported_pairs": ["Al-Al", "Al-O"],
            "missing_pairs": ["Al-Mg", "Mg-Mg", "Mg-O", "O-O"],
            "missing_pair_policy": "soft_repulsive",
            "missing_pair_penalty": 0.0,
        },
        spp_guidance_weight=3.0,
        spp_regularisation_dir="C:/tmp/global_spp",
        spp_regularisation_weight=0.5,
    )

    guidance = request["guidance"][0]
    assert guidance["id"] == "objective.energy_spp"
    assert guidance["weight"] == 3.0
    assert guidance["params"]["mode"] == "partial"
    assert guidance["params"]["missing_pair_policy"] == "soft_repulsive"
    assert guidance["params"]["regularisation_spp_dir"] == "C:/tmp/global_spp"
    assert guidance["params"]["regularisation_weight"] == 0.5
    assert guidance["params"]["strict_pair_coverage"] is False
    validate_solve_request(request)


def test_build_solve_request_passes_regularisation_for_complete_spp() -> None:
    request = build_solve_request(
        "Generate a BaTiO3 candidate.",
        pot_root="C:/tmp/pots",
        material_system="BaTiO3",
        spp_regularisation_dir="C:/tmp/global_spp",
        spp_regularisation_weight=1.25,
    )

    params = request["guidance"][0]["params"]
    assert params["regularisation_spp_dir"] == "C:/tmp/global_spp"
    assert params["regularisation_weight"] == 1.25
    validate_solve_request(request)


def test_build_solve_request_blocks_goal_verb_formula_fallback() -> None:
    try:
        build_solve_request("Generate a crystal", material_system=None)
    except MaterialSystemError as exc:
        assert exc.code == "material_system_missing"
    else:  # pragma: no cover - defensive assertion clarity
        raise AssertionError("Expected material_system_missing")


def test_build_solve_request_uses_concrete_material_for_abo3_goal() -> None:
    request = build_solve_request(
        "Generate an ABO3 perovskite candidate.",
        material_system="CaTiO3",
    )

    assert request["problem"]["chemistry"]["formula"] == "CaTiO3"


def test_build_solve_request_blocks_literal_abo3_material_system() -> None:
    try:
        build_solve_request("Generate an ABO3 perovskite candidate.", material_system="ABO3")
    except MaterialSystemError as exc:
        assert exc.code == "non_concrete_formula"
    else:  # pragma: no cover - defensive assertion clarity
        raise AssertionError("Expected non_concrete_formula")


def test_qlip_client_sets_configured_allowed_path_roots(workdir: Path) -> None:
    settings = _fake_settings(workdir)
    allowed_root = workdir / "QLIP_Outputs"
    settings.qlip_allowed_path_roots = [allowed_root]

    client = _client_for_tool("qlip.validate_request", settings)

    assert client.env is not None
    assert client.env["QLIP_ALLOWED_PATH_ROOTS"] == str(allowed_root.resolve())


def test_qlip_request_path_env_adds_exact_regularisation_root_and_dedupes() -> None:
    with _local_test_dir("qlip_allowed_roots_regularisation") as workdir:
        configured_root = workdir / "configured_allowed_root"
        pot_root = workdir / "partial_spp_root"
        regularisation_root = workdir / "exact_regularisation_root"
        configured_root.mkdir()
        pot_root.mkdir()
        regularisation_root.mkdir()
        settings = _fake_settings(workdir)
        settings.qlip_allowed_path_roots = [configured_root, regularisation_root]

        request = {
            "context": {"pot_root": str(pot_root)},
            "guidance": [
                {
                    "id": "objective.energy_spp",
                    "params": {
                        "regularisation_spp_dir": str(regularisation_root),
                        "regularisation_weight": 1.0,
                    },
                },
                {
                    "id": "objective.energy_spp",
                    "params": {
                        "regularization_spp_dir": str(regularisation_root),
                        "regularization_weight": "1.0",
                    },
                },
            ],
        }

        env = adapters_module._qlip_request_path_env(settings, request)
        roots = env["QLIP_ALLOWED_PATH_ROOTS"].split(os.pathsep)

        assert roots.count(str(regularisation_root.resolve())) == 1
        assert roots == [
            str(configured_root.resolve()),
            str(regularisation_root.resolve()),
            str(pot_root.resolve()),
        ]
        assert str(regularisation_root.parent.resolve()) not in roots


def test_qlip_request_path_env_omits_missing_regularisation_root_until_qlip_validation() -> None:
    with _local_test_dir("qlip_allowed_roots_missing_regularisation") as workdir:
        pot_root = workdir / "partial_spp_root"
        pot_root.mkdir()
        missing_regularisation_root = workdir / "missing_global_spp"
        settings = _fake_settings(workdir)
        settings.qlip_allowed_path_roots = []

        request = {
            "context": {"pot_root": str(pot_root)},
            "guidance": [
                {
                    "id": "objective.energy_spp",
                    "params": {
                        "regularisation_spp_dir": str(missing_regularisation_root),
                        "regularisation_weight": 1.0,
                    },
                },
                {
                    "id": "objective.energy_spp",
                    "params": {
                        "regularization_spp_dir": str(missing_regularisation_root),
                        "regularization_weight": 0.0,
                    },
                },
            ],
        }

        env = adapters_module._qlip_request_path_env(settings, request)
        roots = env["QLIP_ALLOWED_PATH_ROOTS"].split(os.pathsep)

        assert roots == [str(pot_root.resolve())]
        assert str(missing_regularisation_root.resolve()) not in roots


def test_configured_spp_client_prefers_configured_server_src(monkeypatch: pytest.MonkeyPatch, workdir: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    spp_repo = root.parent / "SPP-Maker-QLIP"
    settings = Settings(
        workspace_root=workdir,
        spp_mcp_cmd=f"{sys.executable} -m spp_maker_mcp.server",
        spp_mcp_cwd=str(spp_repo),
    )
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))

    client = _client_for_tool("spp.run_pipeline", settings)

    assert client.cwd == str(spp_repo)
    assert client.env is not None
    assert str(spp_repo / "src") == client.env["PYTHONPATH"].split(os.pathsep)[0]
    assert "mcp_spp_server.py" not in str(client.command)
    assert "spp_mcp.server" not in str(client.command)


def test_spp_run_pipeline_configured_launch_failure_is_not_shim_fallback(monkeypatch) -> None:
    with _local_test_dir("configured_spp_launch_failure") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        settings = _fake_settings(workdir)
        settings.spp_mcp_cmd = "python -m spp_maker_mcp.server"
        settings.spp_mcp_cwd = str(workdir / "SPP-Maker-QLIP")
        seen_extra_env: dict[str, str] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            seen_extra_env.update(extra_env or {})
            raise adapters_module.MCPClientError("configured server could not be launched")

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir), "material_system": "NaCl"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=settings,
        )

        assert result["status"] == "failed"
        assert result["error"]["code"] == "configured_spp_mcp_unavailable"
        assert result["raw_result_summary"]["mcp_server_cmd"] == "python -m spp_maker_mcp.server"
        assert "mcp_spp_server.py" not in result["raw_result_summary"]["mcp_server_cmd"]
        assert "spp_mcp.server" not in result["raw_result_summary"]["mcp_server_cmd"]
        assert "SPP_MCP_ALLOWED_READ_ROOTS" in seen_extra_env
        assert "SPP_MCP_ALLOWED_WRITE_ROOTS" in seen_extra_env
        assert str(cif_dir.resolve()) in seen_extra_env["SPP_MCP_ALLOWED_READ_ROOTS"]
        assert str(step_dir.resolve()) in seen_extra_env["SPP_MCP_ALLOWED_WRITE_ROOTS"]


def test_spp_run_pipeline_output_summary_includes_server_identity(monkeypatch) -> None:
    with _local_test_dir("spp_server_identity") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        settings = _fake_settings(workdir)
        settings.spp_mcp_cmd = "python -m spp_maker_mcp.server"
        settings.spp_mcp_cwd = str(workdir / "SPP-Maker-QLIP")
        (Path(settings.spp_mcp_cwd) / "src").mkdir(parents=True)

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir
            assert tool_name == "spp.run_pipeline"
            run_root = workdir / "spp_run"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "run_root": str(run_root),
                            "final_bundle": str(run_root / "final_bundle"),
                            "cif_count": 1,
                            "paths": {},
                            "qlip_package": {
                                "status": "partial",
                                "qlip_solve_compatible": False,
                                "required_pairs": ["Cl-Cl", "Cl-Na", "Na-Na"],
                                "missing_pairs": ["Cl-Cl"],
                                "extraction_mode": "qlip_required_pairs",
                                "pot_root_source": "none",
                                "fresh_generation": {
                                    "attempted": True,
                                    "corpus_quality": {
                                        "corpus_quality_status": "unsuitable",
                                        "detected_formulas": ["NaCl"],
                                        "files_with_all_target_elements": [],
                                        "files_with_exact_or_reduced_formula_match": [],
                                        "files_with_target_cross_pairs": [],
                                        "geometric_pair_counts": {"Cl-Cl": 0, "Cl-Na": 0, "Na-Na": 0},
                                    },
                                },
                                "warnings": [
                                    {
                                        "code": "corpus_weak_for_spp",
                                        "message": "weak corpus",
                                    }
                                ],
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir), "material_system": "NaCl"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=settings,
        )

        summary = result["output_summary"]
        assert summary["mcp_server_cmd"] == "python -m spp_maker_mcp.server"
        assert summary["mcp_server_cwd"] == str(Path(settings.spp_mcp_cwd).resolve())
        assert summary["mcp_server_src"] == str((Path(settings.spp_mcp_cwd) / "src").resolve())
        assert summary["extraction_mode"] == "qlip_required_pairs"
        assert summary["pot_root_source"] == "none"
        assert summary["fresh_generation"]["attempted"] is True
        assert summary["corpus_quality_status"] == "unsuitable"
        assert summary["detected_formulas"] == ["NaCl"]
        assert summary["files_with_target_cross_pairs"] == []
        assert summary["geometric_pair_counts"] == {"Cl-Cl": 0, "Cl-Na": 0, "Na-Na": 0}
        assert any("corpus_weak_for_spp" in warning for warning in result["warnings"])


def test_spp_run_pipeline_adapter_passes_inferred_material_system(monkeypatch) -> None:
    with _local_test_dir("spp_material_system") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir
            captured["tool_name"] = tool_name
            captured["arguments"] = dict(arguments)
            run_root = workdir / "spp_run"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "run_root": str(run_root),
                            "final_bundle": str(run_root / "final_bundle"),
                            "cif_count": 1,
                            "paths": {},
                            "qlip_package": {
                                "status": "partial",
                                "qlip_solve_compatible": False,
                                "missing": ["pot_pair_coverage"],
                                "required_pairs": ["As-As", "As-Co", "Co-Co"],
                                "missing_pairs": ["As-Co"],
                                "errors": [{"code": "pot_pair_coverage_missing", "message": "missing As-Co"}],
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir)},
            prior_step_results=[
                {
                    "tool_name": "crystal.csp_pack",
                    "output_summary": {"query": "Find candidates for CoAs2"},
                }
            ],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert captured["tool_name"] == "spp.run_pipeline"
        assert captured["arguments"]["material_system"] == "CoAs2"
        assert result["output_summary"]["qlip_package_required_pairs"] == ["As-As", "As-Co", "Co-Co"]
        assert result["output_summary"]["qlip_package_missing_pairs"] == ["As-Co"]
        assert not any(item["ref_name"] == "request_ref" for item in result["artifact_refs"])


def test_spp_run_pipeline_blocks_request_when_pot_root_misses_required_pairs(monkeypatch) -> None:
    with _local_test_dir("spp_pot_root_pair_mismatch") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        pot_root = workdir / "wrong_pot_root"
        pot_root.mkdir()
        (pot_root / "manifest.json").write_text(json.dumps({"pairs": ["As-As", "As-Co", "Co-Co"]}), encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir
            captured["arguments"] = dict(arguments)
            run_root = workdir / "spp_run"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "run_root": str(run_root),
                            "final_bundle": str(run_root / "final_bundle"),
                            "cif_count": 1,
                            "paths": {},
                            "qlip_package": {
                                "status": "ready",
                                "qlip_solve_compatible": True,
                                "missing": [],
                                "required_pairs": [],
                                "missing_pairs": [],
                                "errors": [],
                                "context": {"pot_root": str(pot_root)},
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir), "material_system": "ZnS"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert captured["arguments"]["material_system"] == "ZnS"
        assert result["output_summary"]["qlip_solve_compatible"] is False
        assert result["output_summary"]["qlip_package_missing_pairs"] == ["S-S", "S-Zn", "Zn-Zn"]
        assert result["output_summary"]["selected_pot_root"] is None
        assert not any(item["ref_name"] == "request_ref" for item in result["artifact_refs"])


def test_spp_run_pipeline_can_build_no_spp_request_when_allowed(monkeypatch) -> None:
    with _local_test_dir("spp_no_guidance_request") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        monkeypatch.setenv("SKILL_LOOP_ALLOW_QLIP_WITHOUT_SPP", "1")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            run_root = workdir / "spp_run"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "run_root": str(run_root),
                            "final_bundle": str(run_root / "final_bundle"),
                            "cif_count": 1,
                            "paths": {},
                            "qlip_package": {
                                "status": "partial",
                                "qlip_solve_compatible": False,
                                "required_pairs": ["Al-Al", "Al-Mg", "Al-O", "Mg-Mg", "Mg-O", "O-O"],
                                "available_pairs": ["Al-Al", "Al-O", "Mg-Mg", "O-O"],
                                "missing_pairs": ["Al-Mg", "Mg-O"],
                                "errors": [{"code": "pot_pair_coverage_missing", "message": "missing Al-Mg, Mg-O"}],
                                "context": {"pot_root": ""},
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir), "material_system": "MgAl2O4"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        artifact_refs = {item["ref_name"]: item["value"] for item in result["artifact_refs"]}
        request_path = Path(artifact_refs["request_ref"])
        request = json.loads(request_path.read_text(encoding="utf-8"))
        assert result["output_summary"]["qlip_guidance_mode"] == "no_spp"
        assert result["output_summary"]["qlip_request_attempted"] is True
        assert result["output_summary"]["selected_pot_root"] is None
        assert "pot_root" not in artifact_refs
        assert "spp_pot_root" not in artifact_refs
        assert "qlip_guidance_mode" not in request
        assert "spp_status" not in request
        assert "spp_reason" not in request


def test_spp_run_pipeline_builds_partial_spp_guidance_request_when_allowed(monkeypatch) -> None:
    with _local_test_dir("spp_partial_guidance_request") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        pot_root = workdir / "partial_spp_root"
        (pot_root / "Al-Al").mkdir(parents=True)
        (pot_root / "Al-Al" / "Al-Al.POT").write_text("0.5 0.0\n1.0 0.1\n", encoding="utf-8")
        (pot_root / "O-Al").mkdir(parents=True)
        (pot_root / "O-Al" / "O-Al.POT").write_text("0.5 0.0\n1.0 0.2\n", encoding="utf-8")
        monkeypatch.setenv("SKILL_LOOP_ALLOW_PARTIAL_SPP_GUIDANCE", "1")
        monkeypatch.setenv("SKILL_LOOP_SPP_MISSING_PAIR_POLICY", "soft_repulsive")
        monkeypatch.setenv("SKILL_LOOP_SPP_GUIDANCE_WEIGHT", "10.0")
        monkeypatch.setenv("SKILL_LOOP_SPP_REGULARISATION_DIR", str(workdir / "global_spp"))
        monkeypatch.setenv("SKILL_LOOP_SPP_REGULARISATION_WEIGHT", "0.75")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            run_root = workdir / "spp_run"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "run_root": str(run_root),
                            "final_bundle": str(run_root / "final_bundle"),
                            "cif_count": 1,
                            "paths": {},
                            "qlip_package": {
                                "status": "partial",
                                "qlip_solve_compatible": False,
                                "qlip_partial_guidance_compatible": True,
                                "can_use_as_partial_guidance": True,
                                "partial_guidance_pot_root": str(pot_root),
                                "required_pairs": ["Al-Al", "Al-Mg"],
                                "supported_pairs": ["Al-Al", "Al-O"],
                                "available_pairs": ["Al-Al", "Al-O"],
                                "missing_pairs": ["Al-Mg"],
                                "missing_pair_policy_recommendation": "neutral",
                                "errors": [{"code": "pot_pair_coverage_missing", "message": "missing Al-Mg"}],
                                "context": {"pot_root": ""},
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir), "material_system": "MgAl2O4"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        artifact_refs = {item["ref_name"]: item["value"] for item in result["artifact_refs"]}
        request = json.loads(Path(artifact_refs["request_ref"]).read_text(encoding="utf-8"))
        assert result["output_summary"]["qlip_guidance_mode"] == "partial_spp"
        assert result["output_summary"]["partial_pair_evidence_available"] is True
        assert request["guidance"][0]["id"] == "objective.energy_spp"
        assert request["guidance"][0]["weight"] == 10.0
        assert request["guidance"][0]["params"] == {
            "pot_root": str(pot_root),
            "mode": "partial",
            "supported_pairs": ["Al-Al", "Al-O"],
            "missing_pairs": ["Al-Mg", "Mg-Mg", "Mg-O", "O-O"],
            "missing_pair_policy": "soft_repulsive",
            "missing_pair_penalty": 0.0,
            "regularisation_spp_dir": str(workdir / "global_spp"),
            "regularisation_weight": 0.75,
            "strict_pair_coverage": False,
        }
        assert result["output_summary"]["qlip_package_supported_pair_pot_paths"]["Al-Al"].endswith("Al-Al.POT")
        assert result["output_summary"]["qlip_package_supported_pair_pot_paths"]["Al-O"].endswith("O-Al.POT")
        assert result["output_summary"]["spp_missing_pair_policy"] == "soft_repulsive"
        assert result["output_summary"]["spp_regularisation_dir"] == str(workdir / "global_spp")
        assert result["output_summary"]["spp_regularisation_weight"] == 0.75
        assert result["output_summary"]["full_required_pairs"] == ["Al-Al", "Al-Mg", "Al-O", "Mg-Mg", "Mg-O", "O-O"]
        assert result["output_summary"]["required_pair_universe_source"] == "target_formula"
        assert result["output_summary"]["file_truthful_supported_pairs"] == ["Al-Al", "Al-O"]
        assert "qlip_guidance_mode" not in request
        assert "spp_status" not in request
        assert "spp_reason" not in request


def test_spp_run_pipeline_blocks_unrelated_abo3_pot_root_for_binary_sulfide(monkeypatch) -> None:
    with _local_test_dir("spp_abo3_root_mismatch") as workdir:
        step_dir = workdir / "step_001"
        cif_dir = workdir / "cifs"
        cif_dir.mkdir()
        (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
        pot_root = workdir / "20260218_ABO3_demo" / "spp_root"
        pot_root.mkdir(parents=True)
        (pot_root / "manifest.json").write_text(
            json.dumps({"cif_dir": "C:\\demo\\mp_ABO3_fe\\cifs", "pairs": ["Zn-Zn", "Zn-S", "S-S"]}),
            encoding="utf-8",
        )
        for pair in ("Zn-Zn", "Zn-S", "S-S"):
            pair_dir = pot_root / pair
            pair_dir.mkdir()
            (pair_dir / f"{pair}.POT").write_text("fake pot\n", encoding="utf-8")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            run_root = workdir / "spp_run"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "run_root": str(run_root),
                            "final_bundle": str(run_root / "final_bundle"),
                            "cif_count": 1,
                            "paths": {},
                            "qlip_package": {
                                "status": "ready",
                                "qlip_solve_compatible": True,
                                "required_pairs": ["Zn-Zn", "Zn-S", "S-S"],
                                "missing_pairs": [],
                                "errors": [],
                                "context": {"pot_root": str(pot_root)},
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._spp_run_pipeline_adapter(
            {"step_index": 1, "tool_name": "spp.run_pipeline"},
            arguments={"case_id": "run_001", "corpus_ref": str(cif_dir), "material_system": "ZnS"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["output_summary"]["qlip_solve_compatible"] is False
        assert result["output_summary"]["selected_pot_root"] is None
        assert "pot_root_material_system_mismatch" in result["output_summary"]["qlip_package_missing"]
        assert result["output_summary"]["qlip_package_errors"][0]["code"] == "pot_root_material_system_mismatch"
        assert not any(item["ref_name"] == "request_ref" for item in result["artifact_refs"])


def test_default_adapters_execute_against_fake_servers_and_capture_real_refs() -> None:
    with _local_test_dir("tool_execution_adapters") as workdir:
        adapters = get_default_tool_execution_adapters(_fake_settings(workdir))
        prior: list[dict[str, object]] = []

        crystal_step = {"step_index": 0, "tool_name": "crystal.csp_pack"}
        crystal_result = adapters["crystal.csp_pack"](
            crystal_step,
            arguments={"case_id": "run_001", "objective_family": "TiO2"},
            prior_step_results=prior,
            step_dir=workdir / "step_000",
        )
        assert crystal_result["schema_version"] == TOOL_EXECUTION_RESULT_SCHEMA_VERSION
        assert crystal_result["execution_performed"] is True
        assert crystal_result["status"] == "succeeded"
        assert any(item["ref_name"] == "corpus_ref" for item in crystal_result["artifact_refs"])
        prior.append(crystal_result)

        spp_step = {"step_index": 1, "tool_name": "spp.run_pipeline"}
        corpus_ref = next(item["value"] for item in crystal_result["artifact_refs"] if item["ref_name"] == "corpus_ref")
        spp_result = adapters["spp.run_pipeline"](
            spp_step,
            arguments={"case_id": "run_001", "corpus_ref": corpus_ref},
            prior_step_results=prior,
            step_dir=workdir / "step_001",
        )
        assert spp_result["execution_performed"] is True
        assert spp_result["status"] == "succeeded"
        assert any(item["ref_name"] == "spp_package_ref" for item in spp_result["artifact_refs"])
        assert any(item["ref_name"] == "request_ref" for item in spp_result["artifact_refs"])
        assert spp_result["output_summary"]["qlip_package_status"] == "ready"
        assert spp_result["output_summary"]["qlip_solve_compatible"] is True
        assert spp_result["output_summary"]["pot_root"]
        assert any(item["ref_name"] == "pot_root" for item in spp_result["artifact_refs"])
        assert any(item["ref_name"] == "spp_pot_root" for item in spp_result["artifact_refs"])
        prior.append(spp_result)

        request_ref = next(item["value"] for item in spp_result["artifact_refs"] if item["ref_name"] == "request_ref")
        assert Path(request_ref).exists()
        request_payload = json.loads(Path(request_ref).read_text(encoding="utf-8"))
        assert request_payload["problem"]["chemistry"]["formula"] == "TiO2"
        assert request_payload["context"]["pot_root"] == spp_result["output_summary"]["pot_root"]
        assert request_payload["guidance"][0]["params"] == {}
        assert "spp_package_path" not in request_payload["guidance"][0]["params"]

        validate_step = {"step_index": 2, "tool_name": "qlip.validate_request"}
        validate_result = adapters["qlip.validate_request"](
            validate_step,
            arguments={"case_id": "run_001", "request_ref": request_ref},
            prior_step_results=prior,
            step_dir=workdir / "step_002",
        )
        assert validate_result["execution_performed"] is True
        assert validate_result["status"] == "succeeded"
        assert validate_result["output_summary"]["validated_request_written_kind"] == "normalized_request"
        assert validate_result["output_summary"]["validated_request_schema_check"] == {"ok": True}
        validated_request_ref = next(
            item["value"] for item in validate_result["artifact_refs"] if item["ref_name"] == "validated_request_ref"
        )
        assert Path(validated_request_ref).exists()
        assert next(
            item["value"] for item in validate_result["artifact_refs"] if item["ref_name"] == "solve_ready_request_ref"
        ) == validated_request_ref
        validated_payload = json.loads(Path(validated_request_ref).read_text(encoding="utf-8"))
        assert validated_payload["problem"]["objective"] == {"type": "spp_energy"}
        assert "objective" not in validated_payload
        validate_solve_request(validated_payload)
        prior.append(validate_result)

        solve_step = {"step_index": 3, "tool_name": "qlip.solve"}
        solve_result = adapters["qlip.solve"](
            solve_step,
            arguments={"case_id": "run_001", "validated_request_ref": validated_request_ref},
            prior_step_results=prior,
            step_dir=workdir / "step_003",
        )
        assert solve_result["execution_performed"] is True
        assert solve_result["status"] == "succeeded"
        assert solve_result.get("error") is None
        candidate_cif_path = next(item["value"] for item in solve_result["artifact_refs"] if item["ref_name"] == "candidate_cif_path")
        solution_cif_path = next(item["value"] for item in solve_result["artifact_refs"] if item["ref_name"] == "solution_cif_path")
        assert Path(solution_cif_path).is_absolute()
        assert Path(candidate_cif_path).exists()
        assert candidate_cif_path == solution_cif_path
        prior.append(solve_result)

        novelty_step = {"step_index": 4, "tool_name": "crystal.novelty_check"}
        novelty_result = adapters["crystal.novelty_check"](
            novelty_step,
            arguments={"case_id": "run_001"},
            prior_step_results=prior,
            step_dir=workdir / "step_004",
        )
        assert novelty_result["execution_performed"] is True
        assert novelty_result["status"] == "succeeded"
        assert novelty_result["output_summary"]["is_novel"] is True
        assert novelty_result["output_summary"]["novelty_input_ref_name"] == "solution_cif_path"
        assert novelty_result["output_summary"]["novelty_input_cif_path"] == solution_cif_path
        assert novelty_result["output_summary"]["novelty_input_cif_exists"] is True
        assert json.loads(json.dumps(novelty_result))["tool_name"] == "crystal.novelty_check"


def test_unwrap_mcp_payload_accepts_content_json_envelope() -> None:
    payload = _unwrap_mcp_payload(
        {
            "content": [
                {
                    "type": "json",
                    "json": {
                        "schema_version": "csp_pack.v1",
                        "status": "error",
                        "errors": {
                            "code": "query_embedding_failed",
                            "message": "Failed to create query embedding for text-search.",
                        },
                    },
                }
            ],
            "isError": False,
        }
    )

    assert payload["status"] == "error"
    assert payload["errors"]["code"] == "query_embedding_failed"


def test_crystal_csp_pack_adapter_reads_real_export_bundle_and_propagates_refs(monkeypatch) -> None:
    with _local_test_dir("tool_execution_real_export_bundle") as workdir:
        step_dir = workdir / "step_000"
        export_dir = step_dir / "csp_pack" / "cifs"
        export_dir.mkdir(parents=True, exist_ok=True)
        first_cif = export_dir / "neighbor_1.cif"
        first_cif.write_text("data_neighbor_1\n", encoding="utf-8")
        manifest_path = step_dir / "csp_pack" / "manifest.json"
        manifest_path.write_text("{}", encoding="utf-8")
        results_path = step_dir / "csp_pack" / "results.json"
        results_path.write_text("{}", encoding="utf-8")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, settings, step_dir
            assert arguments["material_system"] == "CoAs2"
            assert arguments["semantic_min_threshold"] == 0.25
            return (
                {
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "schema_version": "csp_pack.v1",
                                "status": "ok",
                                "neighbors": [{"rank": 1, "structure_id": "mp-1"}],
                                "corpus_selection": {
                                    "final_selection_reason": "selected_semantic_chemistry_corpus",
                                    "selected_corpus_pair_coverage": {"missing_pairs": []},
                                },
                                "export": {
                                    "cif_dir": str(export_dir),
                                    "manifest_path": str(manifest_path),
                                    "results_path": str(results_path),
                                    "items": [
                                        {
                                            "rank": 1,
                                            "export_status": "exported",
                                            "cif_path": str(first_cif),
                                            "error": None,
                                        }
                                    ],
                                },
                            },
                        }
                    ],
                    "isError": False,
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._crystal_csp_pack_adapter(
            {"step_index": 0, "tool_name": "crystal.csp_pack"},
            arguments={"case_id": "run_001", "objective_family": "CoAs2", "material_system": "CoAs2"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        artifact_refs = {item["ref_name"]: item["value"] for item in result["artifact_refs"]}
        assert result["status"] == "succeeded"
        assert result["output_summary"]["exported_cif_count"] == 1
        assert result["output_summary"]["corpus_selection"]["final_selection_reason"] == "selected_semantic_chemistry_corpus"
        assert artifact_refs["corpus_ref"] == str(export_dir)
        assert artifact_refs["candidate_cif_path"] == str(first_cif)
        assert artifact_refs["crystal_manifest_json"] == str(manifest_path)
        assert artifact_refs["crystal_results_json"] == str(results_path)


def test_crystal_csp_pack_adapter_blocks_partial_joint_corpus_selection(monkeypatch) -> None:
    with _local_test_dir("tool_execution_joint_corpus_partial") as workdir:
        step_dir = workdir / "step_000"

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            return (
                {
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "schema_version": "csp_pack.v1",
                                "status": "partial",
                                "neighbors": [{"rank": 1, "structure_id": "mp-1"}],
                                "corpus_selection": {
                                    "final_selection_reason": "semantic_support_exists_but_pair_coverage_incomplete",
                                    "selected_corpus_pair_coverage": {"missing_pairs": ["S-Zn"]},
                                },
                                "errors": {
                                    "code": "no_valid_semantic_chemistry_corpus",
                                    "message": "No retrieved corpus satisfies both semantic relevance and chemistry/pair coverage requirements.",
                                },
                                "export": {
                                    "cif_dir": str(step_dir / "csp_pack" / "cifs"),
                                    "manifest_path": str(step_dir / "csp_pack" / "manifest.json"),
                                    "results_path": str(step_dir / "csp_pack" / "results.json"),
                                    "items": [],
                                },
                            },
                        }
                    ],
                    "isError": False,
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._crystal_csp_pack_adapter(
            {"step_index": 0, "tool_name": "crystal.csp_pack"},
            arguments={"case_id": "run_001", "objective_family": "ZnS", "material_system": "ZnS"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["status"] == "blocked"
        assert result["error"]["code"] == "no_valid_semantic_chemistry_corpus"
        assert result["output_summary"]["corpus_selection"]["selected_corpus_pair_coverage"]["missing_pairs"] == ["S-Zn"]


def test_crystal_csp_pack_adapter_accepts_useful_partial_pair_corpus(monkeypatch) -> None:
    with _local_test_dir("tool_execution_joint_corpus_partial_useful") as workdir:
        step_dir = workdir / "step_000"
        export_dir = step_dir / "csp_pack" / "cifs"
        export_dir.mkdir(parents=True, exist_ok=True)
        first_cif = export_dir / "al2o3.cif"
        second_cif = export_dir / "mgo.cif"
        first_cif.write_text("data_al2o3\n", encoding="utf-8")
        second_cif.write_text("data_mgo\n", encoding="utf-8")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            return (
                {
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "schema_version": "csp_pack.v1",
                                "status": "partial",
                                "neighbors": [{"rank": 1, "structure_id": "al2o3"}, {"rank": 2, "structure_id": "mgo"}],
                                "corpus_selection": {
                                    "corpus_selection_status": "partial_pair_coverage",
                                    "final_selection_reason": "selected_partial_semantic_chemistry_corpus",
                                    "covered_required_pairs": ["Al-Al", "Al-O", "Mg-Mg", "O-O"],
                                    "missing_required_pairs": ["Al-Mg", "Mg-O"],
                                    "useful_partial_pair_evidence": True,
                                    "exported_partial_cif_count": 2,
                                    "selected_cif_count": 2,
                                },
                                "errors": {
                                    "code": "partial_pair_coverage",
                                    "message": "Retrieved corpus has useful partial pair evidence but does not cover all required pairs.",
                                },
                                "export": {
                                    "cif_dir": str(export_dir),
                                    "items": [
                                        {"rank": 1, "export_status": "exported", "cif_path": str(first_cif), "error": None},
                                        {"rank": 2, "export_status": "exported", "cif_path": str(second_cif), "error": None},
                                    ],
                                },
                            },
                        }
                    ],
                    "isError": False,
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._crystal_csp_pack_adapter(
            {"step_index": 0, "tool_name": "crystal.csp_pack"},
            arguments={"case_id": "run_001", "objective_family": "MgAl2O4", "material_system": "MgAl2O4"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        artifact_refs = {item["ref_name"]: item["value"] for item in result["artifact_refs"]}
        assert result["status"] == "succeeded"
        assert artifact_refs["corpus_ref"] == str(export_dir)
        assert result["output_summary"]["exported_cif_count"] == 2
        assert result["output_summary"]["useful_partial_pair_evidence"] is True
        assert result["output_summary"]["corpus_selection_status"] == "partial_pair_coverage"
        assert result["output_summary"]["covered_required_pairs"] == ["Al-Al", "Al-O", "Mg-Mg", "O-O"]
        assert result["output_summary"]["missing_required_pairs"] == ["Al-Mg", "Mg-O"]
        assert any("partial_pair_coverage" in warning for warning in result["warnings"])


def test_crystal_csp_pack_adapter_keeps_corpus_ref_absent_when_real_export_is_blocked(monkeypatch) -> None:
    with _local_test_dir("tool_execution_real_export_blocked") as workdir:
        step_dir = workdir / "step_000"
        export_dir = step_dir / "csp_pack" / "cifs"
        export_dir.mkdir(parents=True, exist_ok=True)

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir
            return (
                {
                    "content": [
                        {
                            "type": "json",
                            "json": {
                                "schema_version": "csp_pack.v1",
                                "status": "ok",
                                "neighbors": [{"rank": 1, "structure_id": "mp-1"}],
                                "export": {
                                    "cif_dir": str(export_dir),
                                    "manifest_path": str(step_dir / "csp_pack" / "manifest.json"),
                                    "results_path": str(step_dir / "csp_pack" / "results.json"),
                                    "items": [
                                        {
                                            "rank": 1,
                                            "export_status": "blocked",
                                            "cif_path": None,
                                            "error": "policy_blocked: allow_export=0 and demo_export=false",
                                        }
                                    ],
                                },
                            },
                        }
                    ],
                    "isError": False,
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._crystal_csp_pack_adapter(
            {"step_index": 0, "tool_name": "crystal.csp_pack"},
            arguments={"case_id": "run_001", "objective_family": "CoAs2"},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        ref_names = [item["ref_name"] for item in result["artifact_refs"]]
        assert result["status"] == "succeeded"
        assert result["output_summary"]["exported_cif_count"] == 0
        assert result["output_summary"]["export_block_reasons"] == [
            "policy_blocked: allow_export=0 and demo_export=false"
        ]
        assert "corpus_ref" not in ref_names
        assert any(
            "policy_blocked: allow_export=0 and demo_export=false" in warning for warning in result["warnings"]
        )


def test_qlip_validate_request_adapter_writes_solve_ready_normalized_request(monkeypatch) -> None:
    with _local_test_dir("qlip_validate_normalized") as workdir:
        step_dir = workdir / "step_002"
        request_path = step_dir / "qlip_request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_payload = _base_qlip_request(pot_root=str(workdir / "spp_root"))
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")
        normalized_request = json.loads(json.dumps(request_payload))
        normalized_request["problem"]["objective"] = {"type": "spp_energy"}
        normalized_request["guidance_mode"] = "weighted_sum"
        normalized_request["artifacts"] = {}
        normalized_request["runtime"] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir, extra_env
            assert tool_name == "qlip.validate_request"
            assert arguments["request"] == request_payload
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "valid": True,
                            "normalized_request": normalized_request,
                            "request": {"unexpected": "fallback"},
                            "warnings": [],
                            "errors": [],
                            "capabilities": {"pot_root_resolved": True},
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._qlip_validate_request_adapter(
            {"step_index": 2, "tool_name": "qlip.validate_request"},
            arguments={"case_id": "run_001", "request_ref": str(request_path)},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["status"] == "succeeded"
        assert result["output_summary"]["validated_request_written_kind"] == "normalized_request"
        assert result["output_summary"]["validated_request_schema_check"] == {"ok": True}
        assert result["output_summary"]["solve_ready_request_ref"]
        validated_request_ref = next(
            item["value"] for item in result["artifact_refs"] if item["ref_name"] == "validated_request_ref"
        )
        assert result["output_summary"]["solve_ready_request_ref"] == validated_request_ref
        assert any(item["ref_name"] == "solve_ready_request_ref" for item in result["artifact_refs"])
        written = json.loads(Path(validated_request_ref).read_text(encoding="utf-8"))
        assert written == normalized_request
        assert "valid" not in written
        assert "errors" not in written
        assert "normalized_request" not in written
        validate_solve_request(written)


def test_qlip_validate_request_adapter_accepts_regularised_soft_repulsive_partial_request(monkeypatch) -> None:
    with _local_test_dir("qlip_validate_soft_repulsive_regularised") as workdir:
        step_dir = workdir / "step_002"
        pot_root = workdir / "partial_spp_root"
        (pot_root / "Al-Al").mkdir(parents=True)
        (pot_root / "Al-Al" / "Al-Al.POT").write_text("0.0 1.0\n", encoding="utf-8")
        regularisation_root = workdir / "global_spp"
        (regularisation_root / "Al-Mg").mkdir(parents=True)
        (regularisation_root / "Al-Mg" / "Al-Mg.POT").write_text("0.0 1.0\n", encoding="utf-8")
        request_path = step_dir / "qlip_request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_payload = build_solve_request(
            "Generate a MgAl2O4 candidate.",
            material_system="MgAl2O4",
            partial_spp_guidance={
                "pot_root": str(pot_root),
                "supported_pairs": ["Al-Al"],
                "missing_pairs": ["Al-Mg", "Al-O", "Mg-Mg", "Mg-O", "O-O"],
                "missing_pair_policy": "soft_repulsive",
                "missing_pair_penalty": 0.0,
            },
            spp_guidance_weight=10.0,
            spp_regularisation_dir=str(regularisation_root),
            spp_regularisation_weight=1.0,
        )
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir, kwargs
            assert tool_name == "qlip.validate_request"
            captured["request"] = arguments["request"]
            captured["extra_env"] = extra_env or {}
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "valid": True,
                            "normalized_request": arguments["request"],
                            "warnings": [],
                            "errors": [],
                            "capabilities": {
                                "spp_partial_guidance": {"enabled": True},
                                "spp_missing_pairs_soft_repulsive": ["Al-Mg"],
                            },
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._qlip_validate_request_adapter(
            {"step_index": 2, "tool_name": "qlip.validate_request"},
            arguments={"case_id": "run_001", "request_ref": str(request_path)},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["status"] == "succeeded"
        assert captured["request"] == request_payload
        params = captured["request"]["guidance"][0]["params"]  # type: ignore[index]
        assert params["missing_pair_policy"] == "soft_repulsive"
        assert params["regularisation_spp_dir"] == str(regularisation_root)
        assert params["regularisation_weight"] == 1.0
        assert "QLIP_ALLOWED_PATH_ROOTS" in captured["extra_env"]
        roots = captured["extra_env"]["QLIP_ALLOWED_PATH_ROOTS"].split(os.pathsep)  # type: ignore[index]
        assert str(pot_root.resolve()) in roots
        assert str(regularisation_root.resolve()) in roots
        assert str(regularisation_root.parent.resolve()) not in roots
        validated_request_ref = next(
            item["value"] for item in result["artifact_refs"] if item["ref_name"] == "validated_request_ref"
        )
        validate_solve_request(json.loads(Path(validated_request_ref).read_text(encoding="utf-8")))


def test_qlip_solve_adapter_accepts_validated_request_with_problem_objective(monkeypatch) -> None:
    with _local_test_dir("qlip_solve_problem_objective") as workdir:
        validate_dir = workdir / "step_002"
        solve_dir = workdir / "step_003"
        request_path = validate_dir / "qlip_request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_payload = _base_qlip_request(pot_root=str(workdir / "spp_root"))
        request_payload["problem"]["objective"] = {"type": "spp_energy"}
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, extra_env
            captured.setdefault("calls", []).append(tool_name)
            if tool_name == "qlip.validate_request":
                return (
                    {
                        "structuredContent": {
                            "ok": True,
                            "result": {
                                "valid": True,
                                "normalized_request": request_payload,
                                "warnings": [],
                                "errors": [],
                                "capabilities": {"pot_root_resolved": True},
                            },
                        }
                    },
                    str(step_dir / "raw_tool_response.json"),
                )
            if tool_name == "qlip.solve":
                captured["solve_request"] = arguments["request"]
                return (
                    {
                        "structuredContent": {
                            "ok": True,
                            "result": {
                                "result": {
                                    "status": "OPTIMAL",
                                    "summary": {"objective_value": -1.0},
                                    "outputs": {"cif": "data_solution\n"},
                                }
                            },
                        }
                    },
                    str(step_dir / "raw_tool_response.json"),
                )
            raise AssertionError(tool_name)

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        validate_result = adapters_module._qlip_validate_request_adapter(
            {"step_index": 2, "tool_name": "qlip.validate_request"},
            arguments={"case_id": "run_001", "request_ref": str(request_path)},
            prior_step_results=[],
            step_dir=validate_dir,
            settings=_fake_settings(workdir),
        )
        validated_request_ref = next(
            item["value"] for item in validate_result["artifact_refs"] if item["ref_name"] == "validated_request_ref"
        )
        written = json.loads(Path(validated_request_ref).read_text(encoding="utf-8"))
        assert written["problem"]["objective"] == {"type": "spp_energy"}
        assert "objective" not in written
        validate_solve_request(written)

        solve_result = adapters_module._qlip_solve_adapter(
            {"step_index": 3, "tool_name": "qlip.solve"},
            arguments={"case_id": "run_001", "validated_request_ref": validated_request_ref},
            prior_step_results=[validate_result],
            step_dir=solve_dir,
            settings=_fake_settings(workdir),
        )

        assert solve_result["execution_performed"] is True
        assert solve_result["status"] == "succeeded"
        assert captured["calls"] == ["qlip.validate_request", "qlip.solve"]
        assert captured["solve_request"]["problem"]["objective"] == {"type": "spp_energy"}
        assert "objective" not in captured["solve_request"]


def test_qlip_solve_adapter_requests_and_surfaces_gurobi_visuals(monkeypatch) -> None:
    with _local_test_dir("qlip_solve_gurobi_visuals") as workdir:
        solve_dir = workdir / "step_003"
        solve_dir.mkdir(parents=True, exist_ok=True)
        request_path = workdir / "validated_request.json"
        request_payload = _base_qlip_request(pot_root=str(workdir / "spp_root"))
        request_payload["problem"]["objective"] = {"type": "spp_energy"}
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")
        visuals_dir = solve_dir / "gurobi_visuals"
        spy_path = visuals_dir / "gurobi_constraint_matrix_spy.png"
        meta_path = visuals_dir / "gurobi_constraint_matrix_meta.json"
        trace_path = visuals_dir / "gurobi_mip_trace.png"
        trace_json_path = visuals_dir / "gurobi_mip_trace.json"
        captured: dict[str, object] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir, extra_env, kwargs
            assert tool_name == "qlip.solve"
            captured["request"] = arguments["request"]
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "result": {
                                "status": "OPTIMAL",
                                "summary": {"objective_value": -2.0},
                                "outputs": {
                                    "cif": "data_solution\n",
                                    "artifacts": [
                                        {"kind": "constraint_matrix_spy_path", "data": str(spy_path)},
                                        {"kind": "constraint_matrix_meta_path", "data": str(meta_path)},
                                        {"kind": "mip_trace_plot_path", "data": str(trace_path)},
                                        {"kind": "mip_trace_json_path", "data": str(trace_json_path)},
                                    ],
                                },
                                "certificates": {
                                    "diagnostics": {
                                        "gurobi_visuals": {
                                            "enabled": True,
                                            "constraint_matrix_spy_path": str(spy_path),
                                            "constraint_matrix_meta_path": str(meta_path),
                                            "mip_trace_plot_path": str(trace_path),
                                            "mip_trace_json_path": str(trace_json_path),
                                        }
                                    }
                                },
                            }
                        },
                    }
                },
                str(solve_dir / "raw_tool_response.json"),
            )

        monkeypatch.setenv("QLIP_EXPORT_GUROBI_VISUALS", "1")
        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._qlip_solve_adapter(
            {"step_index": 3, "tool_name": "qlip.solve"},
            arguments={"case_id": "run_001", "validated_request_ref": str(request_path)},
            prior_step_results=[],
            step_dir=solve_dir,
            settings=_fake_settings(workdir),
        )

        refs = {item["ref_name"]: item["value"] for item in result["artifact_refs"]}
        sent = captured["request"]
        assert sent["runtime"]["export_gurobi_visuals"] is True
        assert Path(sent["context"]["gurobi_visuals_dir"]).name == "gurobi_visuals"
        assert result["status"] == "succeeded"
        assert refs["constraint_matrix_spy_path"] == str(spy_path)
        assert refs["mip_trace_plot_path"] == str(trace_path)
        assert result["output_summary"]["gurobi_visuals"]["enabled"] is True


def test_qlip_solve_adapter_normalizes_relative_solution_path(monkeypatch) -> None:
    with _local_test_dir("qlip_solve_relative_solution_path") as workdir:
        solve_dir = workdir / "step_003"
        solve_dir.mkdir(parents=True, exist_ok=True)
        validated_request_path = workdir / "validated_request.json"
        validated_request = _base_qlip_request(pot_root=str(workdir / "spp_root"))
        validated_request["problem"]["objective"] = {"type": "spp_energy"}
        validated_request_path.write_text(json.dumps(validated_request), encoding="utf-8")
        (solve_dir / "solution.cif").write_text("data_solution\n", encoding="utf-8")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = arguments, settings, step_dir, extra_env
            assert tool_name == "qlip.solve"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "result": {
                                "status": "OPTIMAL",
                                "summary": {"objective_value": -2.0},
                                "outputs": {"cif": "solution.cif"},
                            }
                        },
                    }
                },
                str(solve_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._qlip_solve_adapter(
            {"step_index": 3, "tool_name": "qlip.solve"},
            arguments={"case_id": "run_001", "validated_request_ref": str(validated_request_path)},
            prior_step_results=[],
            step_dir=solve_dir,
            settings=_fake_settings(workdir),
        )

        refs = {item["ref_name"]: item["value"] for item in result["artifact_refs"]}
        assert result["status"] == "succeeded"
        assert refs["solution_cif_path_original"] == "solution.cif"
        assert Path(refs["solution_cif_path"]).is_absolute()
        assert Path(refs["solution_cif_path"]).exists()
        assert refs["candidate_cif_path"] == refs["solution_cif_path"]
        assert result["output_summary"]["solution_cif_exists"] is True


def test_novelty_check_prefers_absolute_qlip_solution_path(monkeypatch) -> None:
    with _local_test_dir("novelty_prefers_solution") as workdir:
        step_dir = workdir / "step_004"
        solution_path = (workdir / "step_003" / "solution.cif").resolve()
        solution_path.parent.mkdir(parents=True, exist_ok=True)
        solution_path.write_text("data_solution\n", encoding="utf-8")
        captured: dict[str, object] = {}

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = settings, step_dir
            captured["tool_name"] = tool_name
            captured["arguments"] = dict(arguments)
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "novelty": {"is_novel": True, "max_text_similarity": 0.1, "max_fp_similarity": 0.2},
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._crystal_novelty_check_adapter(
            {"step_index": 4, "tool_name": "crystal.novelty_check"},
            arguments={"case_id": "run_001"},
            prior_step_results=[
                {
                    "tool_name": "qlip.solve",
                    "artifact_refs": [
                        {"ref_name": "candidate_cif_path", "value": "test_workdir/relative/old.cif", "kind": "file"},
                        {"ref_name": "solution_cif_path", "value": str(solution_path), "kind": "file"},
                    ],
                }
            ],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["status"] == "succeeded"
        assert captured["tool_name"] == "crystal.novelty_check"
        assert captured["arguments"]["cif_path"] == str(solution_path)
        assert not captured["arguments"]["cif_path"].startswith("test_workdir")
        assert result["output_summary"]["novelty_input_ref_name"] == "solution_cif_path"
        assert result["output_summary"]["novelty_input_cif_path"] == str(solution_path)
        assert result["output_summary"]["novelty_input_cif_exists"] is True


def test_novelty_check_blocks_with_attempted_paths_when_solution_missing() -> None:
    with _local_test_dir("novelty_missing_solution") as workdir:
        result = adapters_module._crystal_novelty_check_adapter(
            {"step_index": 4, "tool_name": "crystal.novelty_check"},
            arguments={"case_id": "run_001"},
            prior_step_results=[
                {
                    "tool_name": "qlip.solve",
                    "artifact_refs": [
                        {"ref_name": "solution_cif_path", "value": "solution.cif", "kind": "file"},
                    ],
                }
            ],
            step_dir=workdir / "step_004",
            settings=_fake_settings(workdir),
        )

        assert result["execution_performed"] is False
        assert result["status"] == "blocked"
        assert result["error"]["code"] == "solution_cif_path_missing"
        assert "attempted paths" in result["error"]["message"]
        assert result["output_summary"]["solution_cif_path_candidates"][0]["value"] == "solution.cif"
        assert result["output_summary"]["attempted_paths"]


def test_qlip_validate_request_adapter_propagates_invalid_diagnostics(monkeypatch) -> None:
    with _local_test_dir("qlip_validate_invalid") as workdir:
        step_dir = workdir / "step_003"
        request_path = step_dir / "request.json"
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "problem": {"chemistry": {"formula": "TiO2"}},
                    "design_space": {"sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}}},
                    "solver": {"name": "gurobi"},
                }
            ),
            encoding="utf-8",
        )

    def fake_validate_schema(
        payload,  # noqa: ANN001
        *,
        enforce_objective_guidance_contract=True,  # noqa: ANN001
    ):
        assert enforce_objective_guidance_contract is False
        return None

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = tool_name, arguments, settings, step_dir, extra_env
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "valid": False,
                            "errors": [
                                {
                                    "code": "pot_root_missing",
                                    "message": "missing potential root",
                                    "path": "/context/pot_root",
                                }
                            ],
                            "warnings": [],
                            "capabilities": {"pot_root_resolved": False},
                        },
                        "warnings": [],
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "validate_solve_request", fake_validate_schema)
        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._qlip_validate_request_adapter(
            {"step_index": 3, "tool_name": "qlip.validate_request"},
            arguments={"case_id": "run_001", "request_ref": str(request_path)},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["status"] == "succeeded"
        assert result["execution_performed"] is True
        assert result["output_summary"]["valid"] is False
        assert result["output_summary"]["package_valid"] is False
        assert result["output_summary"]["package_validation_status"] == "invalid"
        assert result["output_summary"]["validation_errors"][0]["code"] == "pot_root_missing"
        assert result["output_summary"]["validation_error_codes"] == ["pot_root_missing"]
        assert result["output_summary"]["capabilities"]["pot_root_resolved"] is False
        assert result["raw_result_summary"]["valid"] is False
        validated_request_ref = next(
            item["value"] for item in result["artifact_refs"] if item["ref_name"] == "validated_request_ref"
        )
        assert Path(validated_request_ref).exists()


def test_qlip_solve_adapter_surfaces_error_diagnostics(monkeypatch) -> None:
    with _local_test_dir("qlip_solve_error_diagnostics") as workdir:
        step_dir = workdir / "step_003"
        pot_root = workdir / "spp_root"
        pot_root.mkdir()
        (pot_root / "manifest.json").write_text(json.dumps({"pairs": ["Zn-Zn"]}), encoding="utf-8")
        request_path = workdir / "validated_request.json"
        request_payload = _base_qlip_request(pot_root=str(pot_root))
        request_payload["problem"]["chemistry"]["formula"] = "ZnS"
        request_payload["problem"]["objective"] = {"type": "spp_energy"}
        request_path.write_text(json.dumps(request_payload), encoding="utf-8")

        def fake_call_tool(tool_name, arguments, *, settings, step_dir, extra_env=None, **kwargs):  # noqa: ANN001
            _ = arguments, settings, step_dir, extra_env
            assert tool_name == "qlip.solve"
            return (
                {
                    "structuredContent": {
                        "ok": True,
                        "result": {
                            "result": {
                                "status": "ERROR",
                                "summary": {"termination": "error"},
                                "outputs": {"cif": None},
                                "certificates": {},
                                "errors": [{"code": "solve_error", "message": "solver crashed"}],
                            }
                        },
                    }
                },
                str(step_dir / "raw_tool_response.json"),
            )

        monkeypatch.setattr(adapters_module, "_call_tool", fake_call_tool)

        result = adapters_module._qlip_solve_adapter(
            {"step_index": 3, "tool_name": "qlip.solve"},
            arguments={"case_id": "run_001", "validated_request_ref": str(request_path)},
            prior_step_results=[],
            step_dir=step_dir,
            settings=_fake_settings(workdir),
        )

        assert result["status"] == "failed"
        assert result["output_summary"]["qlip_status"] == "ERROR"
        assert result["output_summary"]["qlip_error_codes"] == ["solve_error"]
        assert result["output_summary"]["formula"] == "ZnS"
        assert result["output_summary"]["pot_root"] == str(pot_root)
        assert result["output_summary"]["missing_pairs"] == ["S-S", "S-Zn"]
        assert result["output_summary"]["raw_tool_response_path"].endswith("raw_tool_response.json")


def test_tool_execution_adapters_have_no_pipeline_or_sqlite_dependency() -> None:
    source = inspect.getsource(adapters_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])

    assert "sqlite3" not in imported_modules
    assert "sqlalchemy" not in imported_modules
    assert "pipeline" not in imported_modules


def test_tool_execution_adapters_do_not_import_pipeline_code() -> None:
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
    _ = get_default_tool_execution_adapters()
    assert "sok_llm_orchestrator.orchestrator.pipeline" not in sys.modules
