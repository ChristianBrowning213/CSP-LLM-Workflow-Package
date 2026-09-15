from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.spp_mcp.server import on_call


def _cif_dir(root: Path) -> Path:
    cif_dir = root / "cifs"
    cif_dir.mkdir()
    (cif_dir / "candidate.cif").write_text("data_candidate\n", encoding="utf-8")
    return cif_dir


def test_run_pipeline_emits_unified_qlip_package() -> None:
    with tempfile.TemporaryDirectory() as temp_text:
        root = Path(temp_text)
        result = on_call(
            "spp.run_pipeline",
            {
                "cif_dir": str(_cif_dir(root)),
                "out_dir": str(root / "out"),
                "name": "case_a",
            },
        )

        assert result["ok"] is True
        payload = result["result"]
        assert Path(payload["spp_run_root"]).exists()
        assert Path(payload["calibration_json"]).exists()
        assert Path(payload["final_bundle_path"]).exists()
        assert payload["qlip_solve_compatible"] is False

        qlip_package = payload["qlip_package"]
        assert qlip_package["status"] == "partial"
        assert Path(qlip_package["guidance_package_path"]).exists()
        assert Path(qlip_package["package_json_path"]).exists()
        assert qlip_package["compatibility"]["qlip_solve_compatible"] is False
        assert qlip_package["compatibility"]["reason"]
        assert qlip_package["missing"] == ["context.pot_root"]
        assert payload["guidance_package_path"] == qlip_package["guidance_package_path"]
        assert payload["package_json_path"] == qlip_package["package_json_path"]

        assert list(Path(payload["spp_run_root"]).rglob("*.POT")) == []
        assert list(Path(qlip_package["guidance_package_path"]).rglob("*.POT")) == []


def test_run_pipeline_packaging_failure_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.spp_maker_qlip.qlip_package as qlip_package_module

    def boom(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("compiler exploded")

    monkeypatch.setattr(qlip_package_module, "create_spp_guidance_package", boom)
    with tempfile.TemporaryDirectory() as temp_text:
        root = Path(temp_text)
        result = on_call(
            "spp.run_pipeline",
            {
                "cif_dir": str(_cif_dir(root)),
                "out_dir": str(root / "out"),
                "name": "case_b",
            },
        )

        assert result["ok"] is True
        payload = result["result"]
        assert Path(payload["spp_run_root"]).exists()
        assert Path(payload["calibration_json"]).exists()
        assert payload["qlip_package"]["status"] == "failed"
        assert payload["qlip_package"]["qlip_solve_compatible"] is False
        assert payload["qlip_package"]["errors"][0]["code"] == "qlip_packaging_failed"
        assert "compiler exploded" in payload["qlip_package"]["errors"][0]["message"]


def test_package_for_qlip_backward_compatibility_still_works() -> None:
    with tempfile.TemporaryDirectory() as temp_text:
        root = Path(temp_text)
        run_result = on_call(
            "spp.run_pipeline",
            {
                "cif_dir": str(_cif_dir(root)),
                "out_dir": str(root / "out"),
                "name": "case_c",
            },
        )
        result = on_call(
            "spp.package_for_qlip",
            {
                "run_root": run_result["result"]["spp_run_root"],
                "out_dir": str(root / "package_out"),
                "name": "case_c",
            },
        )

        assert result["ok"] is True
        payload = result["result"]
        assert Path(payload["final_bundle_path"]).exists()
        assert Path(payload["package_json_path"]).exists()
        assert Path(payload["guidance_package_path"]).exists()
        package_json = json.loads(Path(payload["package_json_path"]).read_text(encoding="utf-8"))
        assert package_json["guidance_package_path"] == payload["guidance_package_path"]
        assert list(Path(payload["final_bundle_path"]).rglob("*.POT")) == []
