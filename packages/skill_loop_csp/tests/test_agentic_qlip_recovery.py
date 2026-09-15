from __future__ import annotations

import ast
import inspect
import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from sok_llm_orchestrator.agentic.qlip_recovery import (
    QLIP_RECOVERY_SCHEMA_VERSION,
    build_corrected_qlip_request_from_spp,
)
import sok_llm_orchestrator.agentic.qlip_recovery as qlip_recovery_module


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


def _invalid_request(bundle_path: str) -> dict[str, object]:
    return {
        "version": "1.0",
        "problem": {
            "chemistry": {"formula": "CoAs2"},
            "design_space": {
                "template": {
                    "lattice": {
                        "a": 4.6,
                        "b": 4.6,
                        "c": 3.0,
                        "alpha": 90.0,
                        "beta": 90.0,
                        "gamma": 90.0,
                        "units": "angstrom",
                    }
                },
                "sites": {"mode": "uniform_grid", "uniform_grid": {"density": 4}},
            },
        },
        "constraints": [],
        "guidance": [
            {
                "id": "objective.energy_spp",
                "params": {
                    "spp_package_path": bundle_path,
                    "pairs_policy": "task_pairs",
                    "oob_policy": "max",
                    "missing_pair_policy": "max_global",
                    "top_k_breakdown": 10,
                },
            }
        ],
        "solver": {"name": "gurobi"},
    }


def test_corrected_request_uses_real_pot_root_and_removes_invalid_guidance_params() -> None:
    with _local_test_dir("qlip_recovery_corrected") as workdir:
        bundle_root = workdir / "bundle"
        spp_root = bundle_root / "spp_root"
        spp_root.mkdir(parents=True, exist_ok=True)
        (spp_root / "Co-Co.POT").write_text("0.1 1.0\n0.2 0.5\n", encoding="utf-8")

        result = build_corrected_qlip_request_from_spp(
            invalid_request=_invalid_request(str(bundle_root)),
            spp_step_result={
                "artifact_refs": [
                    {"ref_name": "scaled_spp_root", "value": str(spp_root), "kind": "directory"},
                ]
            },
            package_step_result={
                "artifact_refs": [
                    {"ref_name": "spp_bundle_path", "value": str(bundle_root), "kind": "directory"},
                ]
            },
            out_dir=workdir / "recovery",
        )

        assert result["schema_version"] == QLIP_RECOVERY_SCHEMA_VERSION
        assert result["status"] == "corrected"
        assert result["pot_root"] == str(spp_root)
        assert result["removed_guidance_params"] == [
            "missing_pair_policy",
            "oob_policy",
            "pairs_policy",
            "spp_package_path",
            "top_k_breakdown",
        ]
        corrected_path = Path(result["corrected_request_path"])
        assert corrected_path.exists()
        corrected_request = json.loads(corrected_path.read_text(encoding="utf-8"))
        assert corrected_request["context"]["pot_root"] == str(spp_root)
        assert corrected_request["guidance"][0]["params"] == {}


def test_missing_real_pot_root_returns_blocked_without_fabricating_path() -> None:
    with _local_test_dir("qlip_recovery_blocked") as workdir:
        bundle_root = workdir / "bundle"
        (bundle_root / "spp_root").mkdir(parents=True, exist_ok=True)

        result = build_corrected_qlip_request_from_spp(
            invalid_request=_invalid_request(str(bundle_root)),
            spp_step_result={
                "artifact_refs": [
                    {"ref_name": "scaled_spp_root", "value": str(bundle_root / "scaled_spp"), "kind": "directory"},
                ]
            },
            package_step_result={
                "artifact_refs": [
                    {"ref_name": "spp_bundle_path", "value": str(bundle_root), "kind": "directory"},
                ]
            },
            out_dir=workdir / "recovery",
        )

        assert result["status"] == "blocked"
        assert result["blocked_reason"] == "pot_root_unavailable"
        assert result["pot_root"] is None
        assert Path(result["corrected_request_path"]).exists()
        assert any("no_pot_files" in warning for warning in result["warnings"])


def test_qlip_recovery_has_no_pipeline_or_sqlite_dependency() -> None:
    source = inspect.getsource(qlip_recovery_module)
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


