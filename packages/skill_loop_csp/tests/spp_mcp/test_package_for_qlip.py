"""
Tests for the SPP-QLIP-COMPILER-1 integration with package_for_qlip
"""

import json
import tempfile
from pathlib import Path
import pytest
from src.spp_mcp.server import on_call

def test_package_for_qlip_with_run_root_creates_guidance_package():
    """Test that package_for_qlip with run_root creates a guidance package with real SPP outputs"""
    # Create temporary directories for test
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test SPP run root
        spp_run_root = Path(temp_dir) / "spp_run"
        spp_run_root.mkdir()

        # Create test calibration JSON
        calibration_json = Path(temp_dir) / "calibration.json"
        calibration_json.write_text(json.dumps({"calibration": "data"}), encoding="utf-8")

        # Create test package.json
        package_json = spp_run_root / "package.json"
        package_json.write_text(json.dumps({"package": "metadata"}), encoding="utf-8")

        # Create test fit_spp_root directory
        fit_spp_root = spp_run_root / "fit_spp"
        fit_spp_root.mkdir()

        # Create test scaled_spp_root directory
        scaled_spp_root = spp_run_root / "scaled_spp"
        scaled_spp_root.mkdir()

        # Create test final_bundle directory
        final_bundle = spp_run_root / "final_bundle"
        final_bundle.mkdir()

        # Create test log file
        log_path = spp_run_root / "run.log"
        log_path.write_text("log content", encoding="utf-8")

        # Create test output directory
        out_dir = Path(temp_dir) / "out"

        # Call package_for_qlip with run_root
        result = on_call(
            "spp.package_for_qlip",
            {
                "run_root": str(spp_run_root),
                "calibration_json": str(calibration_json),
                "out_dir": str(out_dir),
                "name": "test_package"
            }
        )

        # Verify result
        assert result["ok"] is True
        assert "final_bundle_path" in result["result"]
        assert "package_json_path" in result["result"]
        assert "guidance_package_path" in result["result"]

        # Verify guidance package artifacts were created
        guidance_package_relative_path = result["result"]["guidance_package_path"]
        guidance_package_full_path = out_dir / guidance_package_relative_path
        assert (guidance_package_full_path / "package_manifest.json").exists()
        assert (guidance_package_full_path / "calibration_refs.json").exists()
        assert (guidance_package_full_path / "statistical_refs.json").exists()
        assert (guidance_package_full_path / "compatibility.json").exists()
        assert (guidance_package_full_path / "provenance.json").exists()

        # Verify package_manifest.json contains real SPP output paths
        package_manifest = json.loads((guidance_package_full_path / "package_manifest.json").read_text(encoding="utf-8"))
        assert package_manifest["spp_run_root"] == str(spp_run_root)
        assert package_manifest["calibration_json"] == str(calibration_json)
        assert package_manifest["fit_spp_root"] == str(fit_spp_root)
        assert package_manifest["scaled_spp_root"] == str(scaled_spp_root)
        assert package_manifest["final_bundle"] == str(final_bundle)
        assert package_manifest["package_json"] == str(package_json)
        assert package_manifest["log_path"] == str(log_path)

        # Verify calibration_refs.json contains real calibration data
        calibration_refs = json.loads((guidance_package_full_path / "calibration_refs.json").read_text(encoding="utf-8"))
        assert calibration_refs["calibration_json"] == str(calibration_json)
        assert calibration_refs["calibration_data"] == {"calibration": "data"}

        # Verify statistical_refs.json contains real SPP output paths
        statistical_refs = json.loads((guidance_package_full_path / "statistical_refs.json").read_text(encoding="utf-8"))
        assert statistical_refs["fit_spp_root"] == str(fit_spp_root)
        assert statistical_refs["scaled_spp_root"] == str(scaled_spp_root)
        assert statistical_refs["final_bundle"] == str(final_bundle)
        assert statistical_refs["package_json"] == str(package_json)
        assert statistical_refs["log_path"] == str(log_path)

        # Verify compatibility.json has correct metadata
        compatibility = json.loads((guidance_package_full_path / "compatibility.json").read_text(encoding="utf-8"))
        assert compatibility["qlip_version"] == "1.0"
        assert compatibility["spp_maker_version"] == "runtime"
        assert compatibility["qlip_solve_compatible"] is False
        assert compatibility["reason"] == "SPP outputs are statistical guidance artifacts; no native QLIP POT root is available."
        assert compatibility["missing"] == ["context.pot_root"]
        assert compatibility["recommended_next"] == "Add QLIP native SPP guidance mode or implement real POT export."
        assert compatibility["accepted_parameters"] == ["spp_package_path"]
        assert compatibility["removed_parameters"] == [
            "pairs_policy",
            "oob_policy",
            "missing_pair_policy",
            "lambda_override",
            "convention_override",
            "r_cut",
            "top_k_breakdown",
            "weighting_profile",
            "structure_perturbation_profile",
            "base_weight_scale",
            "guidance_weight_scale",
            "template_seed_profile",
            "lattice_candidate_profile",
            "symmetry_relaxation_profile",
            "ordering_perturbation_profile"
        ]

        # Verify provenance.json has correct metadata
        provenance = json.loads((guidance_package_full_path / "provenance.json").read_text(encoding="utf-8"))
        assert provenance["tool"] == "SPP-Maker-QLIP"
        assert provenance["source"] == str(spp_run_root)
        assert provenance["calibration_source"] == str(calibration_json)

        # Verify no POT files were created
        pot_files = list(guidance_package_full_path.rglob("*.POT"))
        assert len(pot_files) == 0, f"Found {len(pot_files)} POT files in guidance package: {pot_files}"

        # Verify package.json contains guidance_package_path
        package_json_path = Path(result["result"]["package_json_path"])
        package_data = json.loads(package_json_path.read_text(encoding="utf-8"))
        assert package_data["guidance_package_path"] == guidance_package_relative_path


def test_package_for_qlip_with_spp_root_and_calibration_json_uses_original_behavior():
    """Test that package_for_qlip with spp_root and calibration_json uses original behavior without guidance package"""
    # Create temporary directories for test
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test SPP root
        spp_root = Path(temp_dir) / "spp_root"
        spp_root.mkdir()

        # Create test calibration JSON
        calibration_json = Path(temp_dir) / "calibration.json"
        calibration_json.write_text(json.dumps({"calibration": "data"}), encoding="utf-8")

        # Create test output directory
        out_dir = Path(temp_dir) / "out"

        # Call package_for_qlip with spp_root and calibration_json
        result = on_call(
            "spp.package_for_qlip",
            {
                "spp_root": str(spp_root),
                "calibration_json": str(calibration_json),
                "out_dir": str(out_dir),
                "name": "test_package"
            }
        )

        # Verify result
        assert result["ok"] is True
        assert "final_bundle_path" in result["result"]
        assert "package_json_path" in result["result"]
        assert "guidance_package_path" not in result["result"]

        # Verify only package.json was created
        bundle_path = Path(result["result"]["final_bundle_path"])
        assert (bundle_path / "package.json").exists()
        assert not (bundle_path / "guidance_package").exists()

        # Verify no POT files were created
        pot_files = list(bundle_path.rglob("*.POT"))
        assert len(pot_files) == 0, f"Found {len(pot_files)} POT files in bundle: {pot_files}"

        # Verify package.json content
        package_json_path = Path(result["result"]["package_json_path"])
        package_data = json.loads(package_json_path.read_text(encoding="utf-8"))
        assert package_data["name"] == "test_package"

        # Verify original provenance and output_bytes
        assert result["result"]["provenance"]["tool"] == "SPP_Maker"
        assert result["result"]["provenance"]["tool_version"] == "shim"
        assert result["result"]["output_bytes"] == 128


def test_package_for_qlip_missing_inputs():
    """Test that package_for_qlip raises validation error for missing inputs"""
    # Create temporary directories for test
    with tempfile.TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir) / "out"

        # Test with no inputs
        result = on_call(
            "spp.package_for_qlip",
            {
                "out_dir": str(out_dir),
                "name": "test_package"
            }
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "validation_error"
        assert "Either run_root OR (spp_root + calibration_json)" in result["error"]["message"]

        # Test with only run_root
        result = on_call(
            "spp.package_for_qlip",
            {
                "run_root": str(out_dir),
                "out_dir": str(out_dir),
                "name": "test_package"
            }
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "compilation_error"
        assert "Calibration file does not exist" in result["error"]["message"]

        # Test with only spp_root
        result = on_call(
            "spp.package_for_qlip",
            {
                "spp_root": str(out_dir),
                "out_dir": str(out_dir),
                "name": "test_package"
            }
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "validation_error"
        assert "Either run_root OR (spp_root + calibration_json)" in result["error"]["message"]

        # Test with only calibration_json
        result = on_call(
            "spp.package_for_qlip",
            {
                "calibration_json": str(out_dir),
                "out_dir": str(out_dir),
                "name": "test_package"
            }
        )
        assert result["ok"] is False
        assert result["error"]["code"] == "validation_error"
        assert "Either run_root OR (spp_root + calibration_json)" in result["error"]["message"]


def test_package_for_qlip_invalid_name():
    """Test that package_for_qlip works with empty name"""
    # Create temporary directories for test
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test SPP run root
        spp_run_root = Path(temp_dir) / "spp_run"
        spp_run_root.mkdir()
        (spp_run_root / "package.json").write_text("{}", encoding="utf-8")

        # Create test calibration JSON
        calibration_json = Path(temp_dir) / "calibration.json"
        calibration_json.write_text(json.dumps({"calibration": "data"}), encoding="utf-8")

        # Create test output directory
        out_dir = Path(temp_dir) / "out"

        # Call package_for_qlip with empty name
        result = on_call(
            "spp.package_for_qlip",
            {
                "run_root": str(spp_run_root),
                "calibration_json": str(calibration_json),
                "out_dir": str(out_dir),
                "name": ""
            }
        )

        # Verify result
        assert result["ok"] is True
        assert "final_bundle_path" in result["result"]
        assert "package_json_path" in result["result"]
        assert "guidance_package_path" in result["result"]

        # Verify bundle path is created with empty name
        bundle_path = Path(result["result"]["final_bundle_path"])
        assert bundle_path.name == "_bundle"  # Should create bundle with empty name

        # Verify guidance package path is created
        guidance_package_path = Path(result["result"]["guidance_package_path"])
        assert guidance_package_path.parts[-2:] == ("_bundle", "guidance_package")
