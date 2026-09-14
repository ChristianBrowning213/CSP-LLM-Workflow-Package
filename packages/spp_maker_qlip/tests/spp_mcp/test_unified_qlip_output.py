from __future__ import annotations

import json
import shutil
from pathlib import Path

import spp_maker_mcp.server as server_module
from spp_maker_mcp.contracts import MCPServerConfig
from spp_maker_mcp.server import RuntimeContext, invoke_tool


def _runtime(tmp_path: Path, *, repo_root_override: Path | None = None) -> RuntimeContext:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = (repo_root / "tests" / "fixtures" / "cifs").resolve()
    return RuntimeContext(
        config=MCPServerConfig(
            allowed_read_roots=[str(cif_root), str(tmp_path.resolve())],
            allowed_write_roots=[str(tmp_path.resolve())],
            max_cif_count=100,
            max_runtime_seconds=600,
            max_output_bytes=100_000_000,
        ),
        read_roots=(cif_root, tmp_path.resolve()),
        write_roots=(tmp_path.resolve(),),
        repo_root=(repo_root_override or repo_root).resolve(),
    )


def _run_pipeline(
    tmp_path: Path,
    *,
    name: str = "unified",
    material_system: str | None = None,
    repo_root_override: Path | None = None,
    r_cut: float | None = None,
    qlip_pair_mode: str | None = None,
    qlip_pair_cutoff: float | None = None,
) -> dict:
    repo_root = Path(__file__).resolve().parents[2]
    cif_root = (repo_root / "tests" / "fixtures" / "cifs").resolve()
    payload = {
            "trace_id": f"trace_{name}",
            "cif_dir": str(cif_root),
            "out_dir": str(tmp_path / "out"),
            "name": name,
            "fit": {"fit_method": "neighbors"},
            "calibration": {"target": 5.0, "max_calib": 2, "bandpass": {"enabled": False}},
    }
    if r_cut is not None:
        payload["fit"]["r_cut"] = r_cut
    if material_system is not None:
        payload["material_system"] = material_system
    if qlip_pair_mode is not None:
        payload["qlip_pair_mode"] = qlip_pair_mode
    if qlip_pair_cutoff is not None:
        payload["qlip_pair_cutoff"] = qlip_pair_cutoff
    response = invoke_tool(
        "spp.run_pipeline",
        payload,
        runtime=_runtime(tmp_path, repo_root_override=repo_root_override),
    )
    assert response["ok"] is True, response
    return response["result"]


def _real_pot_file_for_pair(pair: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    paths = sorted((repo_root / "QLIP_Outputs" / "SPP" / "runs").glob(f"*/spp_root/{pair}/{pair}.POT"), reverse=True)
    assert paths, pair
    path = paths[0]
    assert path.parent.name == pair
    assert path.name == f"{pair}.POT"
    return path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _add_published_run(qlip_outputs: Path, *, run_name: str, pairs: list[str], latest: bool) -> None:
    run_rel = f"SPP/runs/{run_name}"
    run_dir = qlip_outputs / run_rel
    spp_root = run_dir / "spp_root"
    manifest_pairs = []
    for pair in pairs:
        source_pot = _real_pot_file_for_pair(pair)
        pair_dir = spp_root / pair
        pair_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_pot, pair_dir / f"{pair}.POT")
        left, right = pair.split("-", 1)
        manifest_pairs.append({"A": left, "B": right, "path": f"{pair}/{pair}.POT"})
    _write_json(run_dir / "manifest.json", {"pairs": manifest_pairs})
    count = len(pairs)
    (run_dir / "compat_report.txt").write_text(
        f"POT files checked: {count}\nPassed: {count}\nFailed: 0\n",
        encoding="utf-8",
    )
    _write_json(
        run_dir / "publish_meta.json",
        {"checks": {"compat": {"checked": count, "passed": count, "failed": 0, "strict": True}}},
    )
    if latest:
        latest_path = qlip_outputs / "SPP" / "latest.txt"
        latest_path.parent.mkdir(parents=True, exist_ok=True)
        latest_path.write_text(run_rel + "\n", encoding="utf-8")


def test_run_pipeline_creates_spp_outputs_and_unified_qlip_package(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path)

    assert Path(result["spp_run_root"]).is_dir()
    assert Path(result["calibration_json"]).is_file()
    assert Path(result["final_bundle_path"]).is_dir()
    assert Path(result["paths"]["scaled_spp_root"]).is_dir()

    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "ready"
    assert Path(qlip_package["guidance_package_path"]).is_dir()
    assert Path(qlip_package["package_json_path"]).is_file()
    assert qlip_package["compatibility"]["qlip_solve_compatible"] is True
    assert qlip_package["compatibility"]["reason"]
    assert qlip_package["missing"] == []
    assert result["qlip_solve_compatible"] is True
    assert result["guidance_package_path"] == qlip_package["guidance_package_path"]
    assert Path(qlip_package["context"]["pot_root"]).is_dir()
    assert qlip_package["pot_root_source"] == "fresh_corpus"
    assert qlip_package["fallback_used"] is False
    assert qlip_package["request_ref"]
    assert Path(qlip_package["fresh_generation"]["spp_root"]) == Path(result["paths"]["scaled_spp_root"])
    assert Path(qlip_package["context"]["pot_root"]) == Path(result["paths"]["scaled_spp_root"])
    assert list(Path(qlip_package["context"]["pot_root"]).rglob("*.POT"))
    assert qlip_package["artifact_refs"]
    assert any(item["ref_name"] == "pot_root" for item in qlip_package["artifact_refs"])

    assert list(Path(qlip_package["guidance_package_path"]).rglob("*.POT")) == []


def test_run_pipeline_packaging_failure_is_structured(tmp_path: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("compiler exploded")

    monkeypatch.setattr(server_module, "create_spp_guidance_package", boom)
    result = _run_pipeline(tmp_path, name="packaging_failure")

    assert Path(result["spp_run_root"]).is_dir()
    assert Path(result["calibration_json"]).is_file()
    assert result["qlip_package"]["status"] == "failed"
    assert result["qlip_package"]["qlip_solve_compatible"] is False
    assert result["qlip_package"]["errors"][0]["code"] == "qlip_packaging_failed"
    assert "compiler exploded" in result["qlip_package"]["errors"][0]["message"]


def test_run_pipeline_reports_fresh_pair_extraction_gap_for_nacl(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path, name="nacl_complete", material_system="NaCl", r_cut=6.0)

    assert Path(result["spp_run_root"]).is_dir()
    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "partial"
    assert qlip_package["qlip_solve_compatible"] is False
    assert qlip_package["pot_root_source"] == "none"
    assert qlip_package["fallback_used"] is False
    assert qlip_package["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert qlip_package["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    assert qlip_package["supported_pairs"] == ["Cl-Na"]
    assert qlip_package["diagnostic_only"] is True
    assert qlip_package["required_pair_pot_export_complete"] is False
    assert qlip_package["can_use_as_partial_guidance"] is True
    assert qlip_package["qlip_partial_guidance_compatible"] is True
    assert qlip_package["missing_pair_policy_recommendation"] == "neutral"
    assert qlip_package["strict_pair_coverage"] is False
    assert qlip_package["partial_guidance_pot_root"]
    assert qlip_package["supported_pair_pot_paths"]["Cl-Na"].endswith("Cl-Na.POT")
    assert Path(qlip_package["supported_pair_pot_paths"]["Cl-Na"]).is_file()
    assert qlip_package["fallback_required_to_solve"] is True
    assert qlip_package["fallback_selected_reason"]
    assert qlip_package["selected_package"]["supported_pairs"] == ["Cl-Na"]
    assert qlip_package["selected_package"]["diagnostic_only"] is True
    assert qlip_package["selected_package"]["qlip_solve_compatible"] is False
    assert qlip_package["selected_package"]["qlip_partial_guidance_compatible"] is True
    assert set(qlip_package["available_pairs"]).issubset(set(qlip_package["required_pairs"]))
    assert set(qlip_package["supported_pairs"]).issubset(set(qlip_package["required_pairs"]))
    assert qlip_package["context"] == {}
    diagnostics = qlip_package["fresh_generation"]["pair_extraction_diagnostics"]
    assert diagnostics["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert diagnostics["spp_selected_pairs"] == ["Cl-Na"]
    assert diagnostics["pot_pairs"] == ["Cl-Na"]
    assert diagnostics["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    assert {"Cl-Cl", "Cl-Na", "Na-Na"}.issubset(set(diagnostics["geometric_pairs_detected"]))
    assert any(item["code"] == "fresh_spp_generation_failed" for item in qlip_package["errors"])


def test_required_pair_mode_exports_all_nacl_pots(tmp_path: Path) -> None:
    result = _run_pipeline(
        tmp_path,
        name="nacl_required_pairs",
        material_system="NaCl",
        qlip_pair_mode="required_pairs",
        qlip_pair_cutoff=6.0,
    )

    qlip_package = result["qlip_package"]
    assert qlip_package["status"] in {"ready", "partial"}
    assert qlip_package["extraction_mode"] == "qlip_required_pairs"
    assert qlip_package["fallback_used"] is False
    assert qlip_package["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert qlip_package["missing_pairs"] == []
    assert qlip_package["sparse_pairs"] == []
    assert qlip_package["fresh_generation"]["extraction_mode"] == "qlip_required_pairs"
    assert qlip_package["fresh_generation"]["corpus_cif_count"] == 2
    assert qlip_package["fresh_generation"]["pair_stats"]["Cl-Cl"]["count"] > 0
    fresh_package = qlip_package["fresh_package"]
    assert fresh_package["required_pair_pot_export_complete"] is True
    assert fresh_package["fresh_required_pair_coverage_complete"] is True
    assert fresh_package["available_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert qlip_package["supported_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert qlip_package["partial_pair_coverage"] is False
    if fresh_package["pot_quality"].get("diagnostic_only"):
        assert qlip_package["status"] == "partial"
        assert qlip_package["qlip_solve_compatible"] is False
        assert qlip_package["fallback_required_to_solve"] is True
        assert qlip_package["fallback_selected_reason"]
        assert any(item["code"] == "capped_pot_detected" for item in qlip_package["errors"])
    else:
        assert qlip_package["qlip_solve_compatible"] is True
        assert qlip_package["fallback_required_to_solve"] is False
        assert qlip_package["fallback_selected_reason"] in {None, "", "not_required"}
    pot_root = Path(fresh_package["pot_root"])
    assert pot_root.is_dir()
    assert result["paths"]["scaled_spp_root"] != str(pot_root)
    for pair in ("Cl-Cl", "Cl-Na", "Na-Na"):
        assert (pot_root / pair / f"{pair}.POT").is_file()


def test_neighbor_mode_still_exports_only_contact_pairs(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path, name="nacl_neighbors", material_system="NaCl", r_cut=6.0)

    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "partial"
    diagnostics = qlip_package["fresh_generation"]["pair_extraction_diagnostics"]
    assert diagnostics["pair_policy"] == "neighbors"
    assert diagnostics["pot_pairs"] == ["Cl-Na"]
    assert diagnostics["missing_pairs"] == ["Cl-Cl", "Na-Na"]


def test_required_pair_mode_blocks_when_pair_distance_missing(tmp_path: Path) -> None:
    result = _run_pipeline(
        tmp_path,
        name="zns_required_pairs",
        material_system="ZnS",
        qlip_pair_mode="required_pairs",
        qlip_pair_cutoff=6.0,
    )

    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "partial"
    assert qlip_package["qlip_solve_compatible"] is False
    assert qlip_package["request_ref"] is None
    assert qlip_package["pot_root_source"] == "none"
    assert qlip_package["fresh_generation"]["extraction_mode"] == "qlip_required_pairs"
    assert "S-Zn" in qlip_package["missing_pairs"]
    assert any(item["code"] == "required_pair_distances_missing" for item in qlip_package["errors"])


def test_required_pair_mode_metadata_in_unified_output(tmp_path: Path) -> None:
    result = _run_pipeline(
        tmp_path,
        name="nacl_required_metadata",
        material_system="NaCl",
        qlip_pair_mode="required_pairs",
        qlip_pair_cutoff=6.0,
    )

    qlip_package = result["qlip_package"]
    assert qlip_package["extraction_mode"] == "qlip_required_pairs"
    assert qlip_package["fresh_generation"]["pair_stats"]
    assert qlip_package["fresh_generation"]["corpus_cif_files"]
    assert qlip_package["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert qlip_package["available_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert len(qlip_package["available_pairs"]) <= len(qlip_package["required_pairs"])
    assert qlip_package["fresh_package"]["available_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert qlip_package["missing_pairs"] == []


def test_fallback_only_after_required_pair_failure(tmp_path: Path) -> None:
    fake_repo_root = tmp_path / "repo_with_zns_fallback"
    _add_published_run(
        fake_repo_root / "QLIP_Outputs",
        run_name="published_zns_compatible",
        pairs=["S-S", "S-Zn", "Zn-Zn"],
        latest=True,
    )

    result = _run_pipeline(
        tmp_path,
        name="zns_required_fallback",
        material_system="ZnS",
        repo_root_override=fake_repo_root,
        qlip_pair_mode="required_pairs",
        qlip_pair_cutoff=6.0,
    )

    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "ready"
    assert qlip_package["pot_root_source"] == "fallback_precompiled"
    assert qlip_package["fresh_generation"]["attempted"] is True
    assert qlip_package["fresh_generation"]["extraction_mode"] == "qlip_required_pairs"
    assert qlip_package["fallback_used"] is True
    assert qlip_package["fallback_reason"] == "fresh_corpus_insufficient"


def test_compatible_published_root_used_when_fresh_nacl_pairs_incomplete(tmp_path: Path) -> None:
    fake_repo_root = tmp_path / "repo_with_compatible_registry"
    _add_published_run(
        fake_repo_root / "QLIP_Outputs",
        run_name="published_nacl_compatible",
        pairs=["Cl-Cl", "Cl-Na", "Na-Na"],
        latest=True,
    )
    result = _run_pipeline(
        tmp_path,
        name="nacl_prefers_fresh",
        material_system="NaCl",
        repo_root_override=fake_repo_root,
        r_cut=6.0,
    )

    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "ready"
    assert qlip_package["pot_root_source"] == "fallback_precompiled"
    assert qlip_package["fallback_used"] is True
    assert qlip_package["fallback_reason"] == "fresh_corpus_insufficient"
    assert qlip_package["fresh_generation"]["pair_extraction_diagnostics"]["pot_pairs"] == ["Cl-Na"]
    assert qlip_package["fresh_generation"]["pair_extraction_diagnostics"]["missing_pairs"] == ["Cl-Cl", "Na-Na"]
    assert Path(qlip_package["selected_pot_root"]).name == "spp_root"


def test_run_pipeline_fallback_selects_published_coas2_root_for_material_system(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path, name="coas2_complete", material_system="CoAs2")

    assert Path(result["spp_run_root"]).is_dir()
    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "ready"
    assert qlip_package["qlip_solve_compatible"] is True
    assert qlip_package["pot_root_source"] == "fallback_precompiled"
    assert qlip_package["fallback_used"] is True
    assert qlip_package["fallback_reason"] == "fresh_corpus_insufficient"
    assert qlip_package["required_pairs"] == ["As-As", "As-Co", "Co-Co"]
    assert qlip_package["missing_pairs"] == []
    assert qlip_package["compatibility"]["missing_pairs"] == []
    assert qlip_package["compatibility"]["qlip_solve_compatible"] is True
    assert Path(qlip_package["context"]["pot_root"]).is_dir()
    for pair in ("As-As", "As-Co", "Co-Co"):
        assert (Path(qlip_package["context"]["pot_root"]) / pair / f"{pair}.POT").is_file()
    assert list(Path(qlip_package["guidance_package_path"]).rglob("*.POT")) == []


def test_run_pipeline_reports_pair_coverage_missing_for_coas2(tmp_path: Path) -> None:
    fake_repo_root = tmp_path / "repo_with_incomplete_registry"
    _add_published_run(
        fake_repo_root / "QLIP_Outputs",
        run_name="coas_without_cross_pair",
        pairs=["As-As", "Co-Co"],
        latest=True,
    )
    result = _run_pipeline(
        tmp_path,
        name="coas2_missing_pair",
        material_system="CoAs2",
        repo_root_override=fake_repo_root,
    )

    assert Path(result["spp_run_root"]).is_dir()
    qlip_package = result["qlip_package"]
    assert qlip_package["status"] == "partial"
    assert qlip_package["qlip_solve_compatible"] is False
    assert qlip_package["pot_root_source"] == "none"
    assert qlip_package["fallback_used"] is False
    assert qlip_package["selected_pot_root"] is None
    assert qlip_package["context"] == {}
    assert qlip_package["required_pairs"] == ["As-As", "As-Co", "Co-Co"]
    assert set(qlip_package["missing_pairs"]) == {"As-As", "As-Co", "Co-Co"}
    assert set(qlip_package["compatibility"]["missing_pairs"]) == {"As-As", "As-Co", "Co-Co"}
    partial_root = Path(qlip_package["partial_guidance_pot_root"])
    supported_paths = qlip_package["supported_pair_pot_paths"]
    assert qlip_package["supported_pairs"] == []
    assert supported_paths == {}
    assert qlip_package["can_use_as_partial_guidance"] is False
    assert qlip_package["qlip_partial_guidance_compatible"] is False
    assert partial_root.is_dir()
    for pair in qlip_package["supported_pairs"]:
        path = Path(supported_paths[pair])
        assert path.is_file()
        assert partial_root in path.parents
    for pair in qlip_package["missing_pairs"]:
        assert not (partial_root / pair / f"{pair}.POT").is_file()
    fallback_package = qlip_package["fallback_package"]
    assert set(fallback_package["available_pairs"]) == {"As-As", "Co-Co"}
    assert set(fallback_package["missing_pairs"]) == {"As-Co"}
    assert qlip_package["compatibility"]["qlip_solve_compatible"] is False
    assert any(item["code"] == "fresh_spp_generation_failed" for item in qlip_package["errors"])
    assert any(item["code"] == "fallback_pot_pair_coverage_missing" for item in qlip_package["errors"])
    assert list(Path(qlip_package["guidance_package_path"]).rglob("*.POT")) == []


def test_run_pipeline_unified_output_includes_material_and_root_diagnostics(tmp_path: Path) -> None:
    result = _run_pipeline(tmp_path, name="coas2_diagnostics", material_system="CoAs2")

    qlip_package = result["qlip_package"]
    assert qlip_package["material_system"] == "CoAs2"
    assert qlip_package["formula"] == "CoAs2"
    assert qlip_package["required_pairs"] == ["As-As", "As-Co", "Co-Co"]
    assert qlip_package["selected_pot_root"] == qlip_package["context"]["pot_root"]
    assert qlip_package["pot_root_source"] == "fallback_precompiled"
    assert qlip_package["fallback_used"] is True
    assert qlip_package["candidate_roots_checked"]


def test_package_for_qlip_backward_compatibility_still_works(tmp_path: Path) -> None:
    pipeline_result = _run_pipeline(tmp_path, name="backcompat")
    response = invoke_tool(
        "spp.package_for_qlip",
        {
            "run_root": pipeline_result["spp_run_root"],
            "out_dir": str(tmp_path / "pkg"),
            "name": "backcompat_pkg",
        },
        runtime=_runtime(tmp_path),
    )

    assert response["ok"] is True, response
    result = response["result"]
    assert Path(result["final_bundle_path"]).is_dir()
    assert Path(result["package_json_path"]).is_file()
    assert (Path(result["final_bundle_path"]) / "spp_root").is_dir()
