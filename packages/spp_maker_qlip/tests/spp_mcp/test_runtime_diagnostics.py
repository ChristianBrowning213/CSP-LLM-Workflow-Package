from __future__ import annotations

from pathlib import Path
from time import perf_counter

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def _runtime(tmp_path: Path) -> RuntimeContext:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = (repo_root / "tests" / "fixtures" / "cifs").resolve()
    return RuntimeContext(
        config=MCPServerConfig(
            allowed_read_roots=[str(cif_root), str(tmp_path.resolve())],
            allowed_write_roots=[str(tmp_path.resolve())],
            max_cif_count=100,
            max_runtime_seconds=60,
            max_output_bytes=100_000_000,
        ),
        read_roots=(cif_root, tmp_path.resolve()),
        write_roots=(tmp_path.resolve(),),
        repo_root=repo_root.resolve(),
    )


def _probe_payload(tmp_path: Path, *, material_system: str = "NaCl") -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = (repo_root / "tests" / "fixtures" / "cifs").resolve()
    return {
        "trace_id": "trace_runtime_probe",
        "cif_dir": str(cif_root),
        "out_dir": str((tmp_path / "out").resolve()),
        "name": f"runtime_{material_system.lower()}",
        "material_system": material_system,
        "qlip_pair_mode": "required_pairs",
        "qlip_pair_cutoff": 6.0,
        "runtime_profile": "probe",
        "max_cifs": 2,
        "max_distances_per_pair": 128,
        "allow_fallback_precompiled": False,
        "calibration": {"target": 1.0, "max_calib": 2, "bandpass": {"enabled": False}},
    }


def test_tiny_nacl_required_pair_probe_returns_under_60s(tmp_path: Path) -> None:
    t0 = perf_counter()
    response = invoke_tool("spp.run_pipeline", _probe_payload(tmp_path), runtime=_runtime(tmp_path))
    elapsed = perf_counter() - t0

    assert response["ok"] is True, response
    assert elapsed < 60
    result = response["result"]
    assert result["runtime_profile"] == "probe"
    assert result["runtime_stages"]
    assert result["qlip_package"]["runtime_stages"]
    assert result["qlip_package"]["fresh_generation"]["attempted"] is True
    assert result["qlip_package"]["fresh_generation"]["extraction_mode"] == "qlip_required_pairs"


def test_runtime_stages_present_for_partial_output(tmp_path: Path) -> None:
    response = invoke_tool(
        "spp.run_pipeline",
        _probe_payload(tmp_path, material_system="ZnS"),
        runtime=_runtime(tmp_path),
    )

    assert response["ok"] is True, response
    package = response["result"]["qlip_package"]
    assert package["status"] == "partial"
    assert package["runtime_stages"]
    assert any(stage["stage"] == "required_pair_extraction" for stage in package["runtime_stages"])
    assert any(item["code"] == "required_pair_distances_missing" for item in package["errors"])


def test_probe_response_uses_pair_stats_not_raw_distance_arrays(tmp_path: Path) -> None:
    response = invoke_tool("spp.run_pipeline", _probe_payload(tmp_path), runtime=_runtime(tmp_path))

    assert response["ok"] is True, response
    fresh_generation = response["result"]["qlip_package"]["fresh_generation"]
    assert fresh_generation["pair_stats"]
    assert "pair_histograms" not in fresh_generation


def test_allowlisted_absolute_cif_and_out_dir_work(tmp_path: Path) -> None:
    payload = _probe_payload(tmp_path)
    assert Path(payload["cif_dir"]).is_absolute()
    assert Path(payload["out_dir"]).is_absolute()

    response = invoke_tool("spp.run_pipeline", payload, runtime=_runtime(tmp_path))

    assert response["ok"] is True, response
