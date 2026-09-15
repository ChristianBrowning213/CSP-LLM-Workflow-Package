"""
Tests for the SPP-QLIP-COMPILER-1 functionality in qlip_package.py
"""

import json
import tempfile
from pathlib import Path
import pytest
from src.spp_maker_qlip.qlip_package import create_spp_guidance_package


def test_create_spp_guidance_package_success():
    """Test successful creation of SPP guidance package with all required files"""
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

        # Call the compiler
        result = create_spp_guidance_package(
            spp_run_root,
            calibration_json,
            out_dir,
            "test_package"
        )

        # Verify results
        guidance_package_path = result["guidance_package_path"]
        # Verify it's the expected path format
        assert Path(guidance_package_path).parts[-2:] == ("test_package_bundle", "guidance_package")

        # Get the full path for verification
        guidance_package_full_path = Path(guidance_package_path)

        # Verify all required files are created
        assert (guidance_package_full_path / "package_manifest.json").exists()
        assert (guidance_package_full_path / "calibration_refs.json").exists()
        assert (guidance_package_full_path / "statistical_refs.json").exists()
        assert (guidance_package_full_path / "compatibility.json").exists()
        assert (guidance_package_full_path / "provenance.json").exists()

        # Verify package_manifest.json contains correct data
        package_manifest = json.loads((guidance_package_full_path / "package_manifest.json").read_text(encoding="utf-8"))
        assert package_manifest["spp_run_root"] == str(spp_run_root)
        assert package_manifest["calibration_json"] == str(calibration_json)
        assert package_manifest["fit_spp_root"] == str(fit_spp_root)
        assert package_manifest["scaled_spp_root"] == str(scaled_spp_root)
        assert package_manifest["final_bundle"] == str(final_bundle)
        assert package_manifest["package_json"] == str(package_json)
        assert package_manifest["log_path"] == str(log_path)

        # Verify calibration_refs.json contains correct data
        calibration_refs = json.loads((guidance_package_full_path / "calibration_refs.json").read_text(encoding="utf-8"))
        assert calibration_refs["calibration_json"] == str(calibration_json)
        assert calibration_refs["calibration_data"] == {"calibration": "data"}

        # Verify statistical_refs.json contains correct data
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

        # Verify no POT files are created
        pot_files = list(guidance_package_full_path.rglob("*.POT"))
        assert len(pot_files) == 0, f"Found {len(pot_files)} POT files in output: {pot_files}"

        # Verify output_bytes is correct
        total_bytes = sum((guidance_package_full_path / f).stat().st_size for f in [
            "package_manifest.json",
            "calibration_refs.json",
            "statistical_refs.json",
            "compatibility.json",
            "provenance.json",
            "pot_handoff.json",
        ])
        assert result["output_bytes"] == total_bytes

def test_create_spp_guidance_package_missing_inputs():
    """Test creation fails with missing inputs"""
    with tempfile.TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir) / "out"

        # Test with missing run_root
        with pytest.raises(FileNotFoundError):
            create_spp_guidance_package(
                Path(temp_dir) / "missing_run_root",
                Path(temp_dir) / "calibration.json",
                out_dir,
                "test_package"
            )

        # Test with missing calibration_json
        with pytest.raises(FileNotFoundError):
            create_spp_guidance_package(
                Path(temp_dir) / "spp_run",
                Path(temp_dir) / "missing_calibration.json",
                out_dir,
                "test_package"
            )

def test_create_spp_guidance_package_no_pot_files():
    """Test that no POT files are created in the guidance package"""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test SPP run root with POT files
        spp_run_root = Path(temp_dir) / "spp_run"
        spp_run_root.mkdir()

        # Create POT files in the run root
        pot_dir = spp_run_root / "spp_root"
        pot_dir.mkdir()
        (pot_dir / "test.POT").write_text("test content", encoding="utf-8")

        # Create test calibration JSON
        calibration_json = Path(temp_dir) / "calibration.json"
        calibration_json.write_text(json.dumps({"calibration": "data"}), encoding="utf-8")

        # Create test package.json
        package_json = spp_run_root / "package.json"
        package_json.write_text(json.dumps({"package": "metadata"}), encoding="utf-8")

        # Create test output directory
        out_dir = Path(temp_dir) / "out"

        # Call the compiler
        result = create_spp_guidance_package(
            spp_run_root,
            calibration_json,
            out_dir,
            "test_package"
        )

        # Verify no POT files were created in the output bundle
        guidance_package_full_path = out_dir / "test_package_bundle" / "guidance_package"
        pot_files = list(guidance_package_full_path.rglob("*.POT"))
        assert len(pot_files) == 0, f"Found {len(pot_files)} POT files in guidance package: {pot_files}"
