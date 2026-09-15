from __future__ import annotations

import sys
from pathlib import Path

from sok_llm_orchestrator.cli import _doctor_mode_commands
from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_startup_qlip_dependency_resolution_prefers_configured_server(workdir: Path) -> None:  # type: ignore[no-untyped-def]
    root = Path(__file__).resolve().parents[1]
    qlip_script = root / "tests" / "fakes" / "mcp_qlip_server.py"
    settings = Settings.from_sources(None)
    settings.crystaldb_mcp_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_crystaldb_server.py').as_posix()}"
    settings.spp_mcp_cmd = f"{sys.executable} -u {(root / 'tests' / 'fakes' / 'mcp_spp_server.py').as_posix()}"
    settings.qlip_mcp_cmd = f"{sys.executable} -u {qlip_script.as_posix()}"
    settings.qlip_mcp_cwd = str(root)

    commands = _doctor_mode_commands("live", settings)
    report = run_startup_validation(
        mode="live",
        settings=settings,
        workspace=workdir,
        commands=commands,
        strict=True,
    )
    qlip_dep = report["dependencies"]["qlip"]
    provenance = qlip_dep["provenance"]
    assert report["startup_ok"] is True
    assert str(provenance.get("script_path")) == str(qlip_script.resolve())
    assert bool(provenance.get("is_repo_qlip_shim")) is False

