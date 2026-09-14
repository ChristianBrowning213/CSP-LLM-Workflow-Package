"""Lenient parsing tests for slightly incorrect LLM-style MCP calls."""

from __future__ import annotations

from pathlib import Path

from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def _runtime(tmp_path: Path, *, extra_read_roots: list[Path]) -> RuntimeContext:
    repo_root = Path(__file__).resolve().parents[2]
    all_read = tuple(sorted({tmp_path.resolve(), *[p.resolve() for p in extra_read_roots]}, key=str))
    return RuntimeContext(
        config=MCPServerConfig(
            allowed_read_roots=[str(p) for p in all_read],
            allowed_write_roots=[str(tmp_path.resolve())],
            max_cif_count=100,
            max_runtime_seconds=600,
            max_output_bytes=100_000_000,
        ),
        read_roots=all_read,
        write_roots=(tmp_path.resolve(),),
        repo_root=repo_root.resolve(),
    )


def test_lenient_run_pipeline_normalizes_common_aliases(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = (repo_root / "tests" / "fixtures" / "cifs").resolve()
    runtime = _runtime(tmp_path, extra_read_roots=[cif_root])

    response = invoke_tool(
        "spp.run_pipeline",
        {
            "arguments": {
                "traceId": "trace_lenient_run",
                "cifDir": str(cif_root),
                "outDir": str(tmp_path / "out"),
                "name": "lenient_run",
                "fit_method": "neighbors",
                "target": "5.0",
                "dryRun": True,
                "noise_field": 123,
            }
        },
        runtime=runtime,
    )

    assert response["ok"] is True, response
    assert response["trace_id"] == "trace_lenient_run"
    assert response["result"]["dry_run"] is True
    warning_codes = {item["code"] for item in response["warnings"]}
    assert "wrapper_unwrapped" in warning_codes
    assert "alias_key_used" in warning_codes
    assert "unknown_key_filtered" in warning_codes


def test_lenient_publish_normalizes_camel_case(tmp_path: Path, spp_root: Path) -> None:
    runtime = _runtime(tmp_path, extra_read_roots=[spp_root])
    response = invoke_tool(
        "spp.publish_to_qlip_outputs",
        {
            "artifactRoot": str(spp_root),
            "qlipOutputsPath": str(tmp_path / "QLIP_Outputs"),
            "name": "lenient_pub",
            "kind": "spp",
            "setLatest": True,
            "copyMode": "copy",
            "extra": "drop-me",
        },
        runtime=runtime,
    )

    assert response["ok"] is True, response
    warning_codes = {item["code"] for item in response["warnings"]}
    assert "alias_key_used" in warning_codes
    assert "unknown_key_filtered" in warning_codes

