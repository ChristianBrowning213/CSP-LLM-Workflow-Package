from __future__ import annotations

import json
import shutil
from pathlib import Path

from spp_maker_qlip.qlip_package import discover_published_spp_pot_root, select_compatible_pot_root


def _real_pot_file() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    latest = (repo_root / "QLIP_Outputs" / "SPP" / "latest.txt").read_text(encoding="utf-8").strip()
    return next((repo_root / "QLIP_Outputs" / latest / "spp_root").rglob("*.POT"))


def _real_pot_file_for_pair(pair: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    runs_root = repo_root / "QLIP_Outputs" / "SPP" / "runs"
    left, right = pair.split("-", 1)
    reversed_pair = f"{right}-{left}"
    paths = sorted(runs_root.glob(f"*/spp_root/{pair}/{pair}.POT"), reverse=True)
    if not paths:
        paths = sorted(runs_root.glob(f"*/spp_root/{reversed_pair}/{reversed_pair}.POT"), reverse=True)
    assert paths, pair
    path = paths[0]
    return path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _qlip_outputs_run(tmp_path: Path, *, with_pot: bool = True, failed: int = 0) -> tuple[Path, Path]:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    run_rel = "SPP/runs/test_spp_run"
    run_dir = qlip_outputs / run_rel
    spp_root = run_dir / "spp_root"
    spp_root.mkdir(parents=True, exist_ok=True)
    if with_pot:
        pair_dir = spp_root / "Ac-B"
        pair_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_real_pot_file(), pair_dir / "Ac-B.POT")
        pairs = [{"A": "Ac", "B": "B", "path": "Ac-B/Ac-B.POT"}]
    else:
        pairs = []
    _write_json(run_dir / "manifest.json", {"pairs": pairs})
    checked = 1 if with_pot else 0
    passed = checked - failed
    (run_dir / "compat_report.txt").write_text(
        f"POT files checked: {checked}\nPassed: {passed}\nFailed: {failed}\n",
        encoding="utf-8",
    )
    _write_json(
        run_dir / "publish_meta.json",
        {
            "checks": {
                "compat": {
                    "checked": checked,
                    "passed": passed,
                    "failed": failed,
                    "strict": True,
                }
            }
        },
    )
    latest = qlip_outputs / "SPP" / "latest.txt"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(run_rel + "\n", encoding="utf-8")
    return qlip_outputs, run_dir


def _add_published_run(
    qlip_outputs: Path,
    *,
    run_name: str,
    pairs: list[str],
    latest: bool = False,
) -> Path:
    run_rel = f"SPP/runs/{run_name}"
    run_dir = qlip_outputs / run_rel
    spp_root = run_dir / "spp_root"
    manifest_pairs = []
    for pair in pairs:
        pair_dir = spp_root / pair
        pair_dir.mkdir(parents=True, exist_ok=True)
        source_pot = _real_pot_file_for_pair(pair)
        assert source_pot.parent.name == pair
        assert source_pot.name == f"{pair}.POT"
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
    return run_dir


def test_valid_published_spp_root_sets_context_pot_root(tmp_path: Path) -> None:
    qlip_outputs, run_dir = _qlip_outputs_run(tmp_path)
    result = discover_published_spp_pot_root(qlip_outputs_root=qlip_outputs)

    assert result["ok"] is True
    assert result["pot_root"] == str(run_dir / "spp_root")
    assert result["pot_count"] == 1
    assert result["compat"]["checked"] == 1
    assert result["compat"]["passed"] == 1
    assert result["compat"]["failed"] == 0
    assert any(item["ref_name"] == "pot_root" for item in result["artifact_refs"])


def test_no_pot_files_returns_structured_error(tmp_path: Path) -> None:
    qlip_outputs, _ = _qlip_outputs_run(tmp_path, with_pot=False)
    result = discover_published_spp_pot_root(qlip_outputs_root=qlip_outputs)

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "pot_root_no_pot_files"


def test_compat_failed_returns_structured_error(tmp_path: Path) -> None:
    qlip_outputs, _ = _qlip_outputs_run(tmp_path, failed=1)
    result = discover_published_spp_pot_root(qlip_outputs_root=qlip_outputs)

    assert result["ok"] is False
    assert any(item["code"] == "pot_compat_failed" for item in result["errors"])


def test_missing_qlip_outputs_or_latest_returns_structured_error(tmp_path: Path) -> None:
    missing = discover_published_spp_pot_root(qlip_outputs_root=tmp_path / "missing")
    assert missing["ok"] is False
    assert missing["errors"][0]["code"] == "qlip_outputs_missing"

    qlip_outputs = tmp_path / "QLIP_Outputs"
    (qlip_outputs / "SPP").mkdir(parents=True)
    no_latest = discover_published_spp_pot_root(qlip_outputs_root=qlip_outputs)
    assert no_latest["ok"] is False
    assert no_latest["errors"][0]["code"] == "qlip_outputs_missing"


def test_helper_does_not_create_pot_files(tmp_path: Path) -> None:
    qlip_outputs, run_dir = _qlip_outputs_run(tmp_path, with_pot=False)
    before = list(run_dir.rglob("*.POT"))
    result = discover_published_spp_pot_root(qlip_outputs_root=qlip_outputs)
    after = list(run_dir.rglob("*.POT"))

    assert result["ok"] is False
    assert before == after == []


def test_root_selection_prefers_required_pair_coverage_over_latest(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    latest_run = _add_published_run(qlip_outputs, run_name="latest_lacks_pair", pairs=["Ac-Ac"], latest=True)
    covering_run = _add_published_run(qlip_outputs, run_name="covers_pair", pairs=["Ac-Ac", "Ac-B"])

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        required_pairs=["Ac-Ac", "Ac-B"],
    )

    assert result["ok"] is True
    assert result["run_path"] == str(covering_run)
    assert result["pot_root"] != str(latest_run / "spp_root")
    assert result["missing_pairs"] == []


def test_missing_as_co_pair_coverage_is_structured(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    _add_published_run(qlip_outputs, run_name="coas_without_cross_pair", pairs=["As-As", "Co-Co"], latest=True)

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="CoAs2",
    )

    assert result["ok"] is False
    assert result["required_pairs"] == ["As-As", "As-Co", "Co-Co"]
    assert result["missing_pairs"] == ["As-Co"]
    assert any(item["code"] == "pot_pair_coverage_missing" for item in result["errors"])


def test_published_root_with_coas2_pairs_is_selectable_for_material_system(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    run_dir = _add_published_run(
        qlip_outputs,
        run_name="coas2_complete",
        pairs=["As-As", "As-Co", "Co-Co"],
        latest=True,
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="CoAs2",
    )

    assert result["ok"] is True
    assert result["run_path"] == str(run_dir)
    assert result["required_pairs"] == ["As-As", "As-Co", "Co-Co"]
    assert result["missing_pairs"] == []
    assert result["pot_count"] == 3
    assert result["compat"]["failed"] == 0


def test_selector_prefers_coas2_complete_root_over_abo3_latest(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    abo3_latest = _add_published_run(
        qlip_outputs,
        run_name="abo3_latest_lacks_as_co",
        pairs=["As-As", "Co-Co"],
        latest=True,
    )
    coas2_run = _add_published_run(
        qlip_outputs,
        run_name="coas2_complete",
        pairs=["As-As", "As-Co", "Co-Co"],
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="CoAs2",
    )

    assert result["ok"] is True
    assert result["run_path"] == str(coas2_run)
    assert result["pot_root"] != str(abo3_latest / "spp_root")
    assert result["missing_pairs"] == []


def test_pair_helpers_do_not_rename_unrelated_pot_files() -> None:
    for pair in ("As-As", "As-Co", "Co-Co"):
        pot = _real_pot_file_for_pair(pair)
        assert pot.parent.name == pair
        assert pot.stem == pair


def test_selects_coas2_root_when_required_pairs_present(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    run_dir = _add_published_run(
        qlip_outputs,
        run_name="20260514_CoAs2_complete",
        pairs=["As-As", "As-Co", "Co-Co"],
        latest=True,
    )

    result = select_compatible_pot_root("CoAs2", qlip_outputs)

    assert result.qlip_solve_compatible is True
    assert result.selected_pot_root == str(run_dir / "spp_root")


def test_does_not_select_abo3_root_for_zns(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    _add_published_run(
        qlip_outputs,
        run_name="20260217_ABO3_latest",
        pairs=["Ca-Ca", "Ca-O", "Ca-Ti", "O-O", "O-Ti", "Ti-Ti"],
        latest=True,
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="ZnS",
    )

    assert result["ok"] is False
    assert result["selected_pot_root"] is None
    assert result["required_pairs"] == ["S-S", "S-Zn", "Zn-Zn"]
    assert "S-Zn" in result["missing_pairs"]
    assert any(item["code"] == "pot_pair_coverage_missing" for item in result["errors"])


def test_does_not_select_broad_abo3_root_for_zns_even_if_pairs_present(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    _add_published_run(
        qlip_outputs,
        run_name="20260217_ABO3_all_pairs",
        pairs=["S-S", "S-Zn", "Zn-Zn"],
        latest=True,
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="ZnS",
    )

    assert result["ok"] is False
    assert result["selected_pot_root"] is None
    assert result["candidate_roots_checked"][0]["reason"] == "material_family_mismatch"
    assert any(item["code"] == "pot_pair_coverage_missing" for item in result["errors"])


def test_does_not_select_abo3_root_for_lico2_if_pairs_missing(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    _add_published_run(
        qlip_outputs,
        run_name="20260217_ABO3_lacks_lico2_cross_pair",
        pairs=["Co-Co", "Co-O", "Li-Li", "O-O"],
        latest=True,
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="LiCoO2",
    )

    assert result["ok"] is False
    assert result["selected_pot_root"] is None
    assert result["required_pairs"] == ["Co-Co", "Co-Li", "Co-O", "Li-Li", "Li-O", "O-O"]
    assert "Co-Li" in result["missing_pairs"]
    assert any(item["code"] == "pot_pair_coverage_missing" for item in result["errors"])


def test_does_not_select_broad_abo3_root_for_lico2_even_if_pairs_present(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    _add_published_run(
        qlip_outputs,
        run_name="20260217_ABO3_all_lico2_pairs",
        pairs=["Co-Co", "Co-Li", "Co-O", "Li-Li", "Li-O", "O-O"],
        latest=True,
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="LiCoO2",
    )

    assert result["ok"] is False
    assert result["selected_pot_root"] is None
    assert result["candidate_roots_checked"][0]["reason"] == "material_family_mismatch"
    assert any(item["code"] == "pot_pair_coverage_missing" for item in result["errors"])


def test_accepts_catio3_abo3_root_when_pairs_present(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    run_dir = _add_published_run(
        qlip_outputs,
        run_name="20260217_ABO3_catio3_pairs",
        pairs=["Ca-Ca", "Ca-O", "Ca-Ti", "O-O", "O-Ti", "Ti-Ti"],
        latest=True,
    )

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="CaTiO3",
    )

    assert result["ok"] is True
    assert result["selected_pot_root"] == str(run_dir / "spp_root")
    assert result["missing_pairs"] == []


def test_pair_normalization_accepts_reversed_paths(tmp_path: Path) -> None:
    qlip_outputs = tmp_path / "QLIP_Outputs"
    run_rel = "SPP/runs/reversed_coas2"
    run_dir = qlip_outputs / run_rel
    spp_root = run_dir / "spp_root"
    for pair in ("As-As", "Co-Co"):
        pair_dir = spp_root / pair
        pair_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_real_pot_file_for_pair(pair), pair_dir / f"{pair}.POT")
    reversed_dir = spp_root / "Co-As"
    reversed_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_real_pot_file_for_pair("As-Co"), reversed_dir / "Co-As.POT")
    _write_json(
        run_dir / "manifest.json",
        {
            "pairs": [
                {"A": "As", "B": "As", "path": "As-As/As-As.POT"},
                {"A": "Co", "B": "As", "path": "Co-As/Co-As.POT"},
                {"A": "Co", "B": "Co", "path": "Co-Co/Co-Co.POT"},
            ]
        },
    )
    (run_dir / "compat_report.txt").write_text("POT files checked: 3\nPassed: 3\nFailed: 0\n", encoding="utf-8")
    _write_json(run_dir / "publish_meta.json", {"checks": {"compat": {"checked": 3, "passed": 3, "failed": 0, "strict": True}}})
    (qlip_outputs / "SPP" / "latest.txt").write_text(run_rel + "\n", encoding="utf-8")

    result = discover_published_spp_pot_root(
        qlip_outputs_root=qlip_outputs,
        material_system="CoAs2",
    )

    assert result["ok"] is True
    assert result["selected_pot_root"] == str(spp_root)
    assert result["missing_pairs"] == []
