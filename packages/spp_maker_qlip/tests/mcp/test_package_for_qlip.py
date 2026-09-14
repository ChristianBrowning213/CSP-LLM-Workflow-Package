"""MCP tool tests for spp.package_for_qlip."""

from __future__ import annotations

import json
from pathlib import Path

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def test_package_for_qlip_from_spp_root_and_calibration(tmp_path: Path, spp_root: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    calibration_json = tmp_path / "calibration.json"
    calibration_json.write_text(
        json.dumps(
            {
                "lambda_used": 1.5,
                "convention": "reward",
                "score_method": "neighbors",
                "fit_method": "neighbors",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    config = MCPServerConfig(
        allowed_read_roots=[str(spp_root.resolve()), str(tmp_path.resolve())],
        allowed_write_roots=[str(tmp_path.resolve())],
        max_cif_count=100,
        max_runtime_seconds=600,
        max_output_bytes=100_000_000,
    )
    runtime = RuntimeContext(
        config=config,
        read_roots=(spp_root.resolve(), tmp_path.resolve()),
        write_roots=(tmp_path.resolve(),),
        repo_root=repo_root.resolve(),
    )

    out_dir = tmp_path / "out"
    response = invoke_tool(
        "spp.package_for_qlip",
        {
            "spp_root": str(spp_root),
            "calibration_json": str(calibration_json),
            "out_dir": str(out_dir),
            "name": "pkg_demo",
        },
        runtime=runtime,
    )
    assert response["ok"] is True, response
    result = response["result"]

    final_bundle = Path(result["final_bundle_path"])
    assert final_bundle.is_dir()
    assert Path(result["package_json_path"]).is_file()
    assert (final_bundle / "spp_root").is_dir()
    assert (final_bundle / "guidance" / "calibration.json").is_file()
    assert (final_bundle / "compat_report.txt").is_file()
    assert (final_bundle / "README.txt").is_file()
    assert result["contents"] == sorted(result["contents"])

