from __future__ import annotations

import os
from pathlib import Path

import pytest

from sok_llm_orchestrator.config import Settings


def test_missing_llm_requirements_fail() -> None:
    settings = Settings.from_sources(None)
    settings.llm_api_key = None
    settings.llm_model = None
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        settings.validate_llm()


def test_load_from_yaml(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = workdir / "cfg.yaml"
    cfg.write_text("llm_model: m1\nllm_api_key: k\n", encoding="utf-8")
    for key in ("LLM_MODEL", "LLM_API_KEY"):
        if key in os.environ:
            monkeypatch.delenv(key)
    settings = Settings.from_sources(cfg)
    assert settings.llm_model == "m1"
    assert settings.llm_api_key == "k"


def test_loads_configured_qlip_allowed_path_roots(workdir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    qlip_root = workdir / "QLIP_Outputs"
    cfg = workdir / "cfg.yaml"
    cfg.write_text(f"qlip_allowed_path_roots:\n  - {qlip_root}\n", encoding="utf-8")
    monkeypatch.delenv("QLIP_ALLOWED_PATH_ROOTS", raising=False)

    settings = Settings.from_sources(cfg)

    assert settings.qlip_allowed_path_roots == [qlip_root.resolve()]


def test_live_config_routes_spp_to_real_spp_maker_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    config_path = root / "my_live_config.yaml"
    for key in ("SPP_MCP_CMD", "SPP_MCP_CWD"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_sources(config_path)
    spp_cwd = (root / settings.spp_mcp_cwd).resolve() if settings.spp_mcp_cwd else None

    assert spp_cwd == (root.parent / "SPP-Maker-QLIP").resolve()
    assert "spp_maker_mcp.server" in str(settings.spp_mcp_cmd)
    assert "spp_mcp.server" not in str(settings.spp_mcp_cmd)
    assert "mcp_spp_server.py" not in str(settings.spp_mcp_cmd)
