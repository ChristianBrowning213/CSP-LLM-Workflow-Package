from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.config import Settings
from sok_llm_orchestrator.orchestrator.pipeline import _stub_command
from sok_llm_orchestrator.orchestrator.startup import run_startup_validation


def test_startup_probe_tracks_real_qlip_artifact_path(workdir: Path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings.from_sources(None)
    report = run_startup_validation(
        mode="stub",
        settings=settings,
        workspace=workdir,
        commands=(
            _stub_command("mcp_crystaldb_server.py"),
            _stub_command("mcp_spp_server.py"),
            _stub_command("mcp_qlip_server.py"),
        ),
        strict=True,
    )
    qlip_probe = report["dependencies"]["qlip"]["probe"]
    cif_path = Path(str(qlip_probe["cif_path_a"])).resolve()
    assert "runs\\shim" not in str(cif_path)
    assert cif_path.exists()
    expected_prefix = (workdir / "startup" / "probe_outputs" / "qlip" / "run").resolve()
    assert str(cif_path).startswith(str(expected_prefix))

