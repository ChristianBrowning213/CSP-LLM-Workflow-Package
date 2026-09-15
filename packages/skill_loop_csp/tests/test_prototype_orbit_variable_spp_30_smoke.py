from __future__ import annotations

import csv
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run_prototype_orbit_variable_spp_30_smoke.py"
SPEC = importlib.util.spec_from_file_location("run_prototype_orbit_variable_spp_30_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _write_fixture_pot(root: Path, pair: str, value: float = 1.0) -> None:
    pair_dir = root / pair
    pair_dir.mkdir(parents=True, exist_ok=True)
    (pair_dir / f"{pair}.POT").write_text(f"0.0 {value}\n8.0 {value}\n", encoding="utf-8")


def test_30_smoke_manifest_has_30_intended_rows_and_tiers() -> None:
    rows = list(csv.DictReader(MODULE.DEFAULT_MANIFEST.open("r", encoding="utf-8", newline="")))

    assert len(rows) == 30
    assert all(row["prompt_id"] for row in rows)
    assert all(row["expected_validation_tier"] for row in rows)
    assert {row["requested_mode"] for row in rows} == {
        "prototype_orbit_variable_spp_qlip",
        "prototype_orbit_qlip",
    }
    assert sum(row["expected_validation_tier"] == "variable_spp_scored" for row in rows) == 3


def test_strict_supported_only_excludes_unsupported_rows_without_fake_generation() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        manifest = root / "manifest.csv"
        manifest.write_text(
            "prompt_id,formula,target_family,requested_space_group,requested_space_group_number,requested_crystal_system,requested_mode,expected_validation_tier,notes\n"
            "bad,Unobtanium2,unknown,P1,1,triclinic,prototype_orbit_qlip,unsupported,unsupported row\n",
            encoding="utf-8",
        )

        summary = MODULE.run_smoke(
            manifest=manifest,
            out_root=root / "out",
            pot_dir=None,
            require_real_spp=False,
            allow_spp_unavailable=True,
            max_rows=1,
            strict_supported_only=True,
        )

        assert summary["generated_rows"] == 0
        assert summary["unsupported_rows"] == 1
        assert summary["rows"][0]["validation_tier"] == "unsupported"
        assert not summary["rows"][0]["cif_path"]


def test_require_real_spp_fails_clearly_when_required_pairs_missing() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        pot_root = root / "spp_root"
        _write_fixture_pot(pot_root, "Ba-O")

        with pytest.raises(SystemExit) as excinfo:
            MODULE.run_smoke(
                out_root=root / "out",
                pot_dir=pot_root,
                require_real_spp=True,
                allow_spp_unavailable=False,
                max_rows=1,
                strict_supported_only=True,
            )

        assert "lacked required real SPP POT coverage" in str(excinfo.value)
        summary = MODULE._read_json(root / "out" / "targeted_smoke_manifest.json")
        assert summary["real_spp_failures"] == 1
        assert summary["rows"][0]["validation_tier"] == "failed"
        assert "Ba-Ba" in summary["rows"][0]["missing_pairs"]


def test_variable_row_scores_and_remains_symmetry_closed_with_fixture_pots() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        pot_root = root / "spp_root"
        for pair in ("Ba-Ba", "Ba-O", "Ba-Ti", "O-O", "O-Ti", "Ti-Ti"):
            _write_fixture_pot(pot_root, pair)

        summary = MODULE.run_smoke(
            out_root=root / "out",
            pot_dir=pot_root,
            require_real_spp=True,
            allow_spp_unavailable=False,
            max_rows=1,
            strict_supported_only=True,
        )

        row = summary["rows"][0]
        assert summary["generated_rows"] == 1
        assert row["validation_tier"] == "variable_spp_scored"
        assert row["spp_scoring_status"] == "scored"
        assert row["objective_value"] is not None
        assert row["symmetry_closed"] is True


def test_unscored_fixed_rows_have_null_objective_when_spp_unavailable() -> None:
    with TemporaryDirectory() as tmp_name:
        root = Path(tmp_name)
        manifest = root / "manifest.csv"
        manifest.write_text(
            "prompt_id,formula,target_family,requested_space_group,requested_space_group_number,requested_crystal_system,requested_mode,expected_validation_tier,notes\n"
            "nio,NiO,rocksalt,Fm-3m,225,cubic,prototype_orbit_qlip,fixed_orbit_unscored,no pot fallback\n",
            encoding="utf-8",
        )

        summary = MODULE.run_smoke(
            manifest=manifest,
            out_root=root / "out",
            pot_dir=None,
            require_real_spp=False,
            allow_spp_unavailable=True,
            max_rows=1,
            strict_supported_only=True,
        )

        row = summary["rows"][0]
        assert row["validation_tier"] == "fixed_orbit_unscored"
        assert row["spp_scoring_status"] == "unavailable"
        assert row["objective_value"] is None
