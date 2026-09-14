from __future__ import annotations

from pathlib import Path
from time import perf_counter

from scripts.diagnose_pair_extraction import build_diagnostic
from spp_maker_qlip.required_pair_extraction import collect_required_pair_distances


def test_nacl_pair_extraction_diagnostic_explains_observed_pair_subset(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cif_dir = repo_root / "tests" / "fixtures" / "cifs"
    out_json = tmp_path / "nacl_pair_extraction_diagnostic.json"

    diagnostic = build_diagnostic(
        cif_dir=cif_dir,
        formula="NaCl",
        out_json=out_json,
        cutoff=6.0,
        supercell=1,
    )

    assert diagnostic["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    nacl_entry = next(item for item in diagnostic["cifs"] if Path(item["file"]).name == "nacl.cif")
    geometric = nacl_entry["geometric_pairs_within_cutoff"]
    assert {"Cl-Cl", "Cl-Na", "Na-Na"}.issubset(geometric)
    assert all(geometric[pair]["count"] > 0 for pair in ("Cl-Cl", "Cl-Na", "Na-Na"))

    assert diagnostic["spp_selected_pairs"] == ["Cl-Na"]
    assert diagnostic["pot_pairs"] == ["Cl-Na"]
    assert diagnostic["missing_after_spp"] == ["Cl-Cl", "Na-Na"]
    assert "selected a subset" in diagnostic["likely_reason"]


def test_required_pair_extraction_nacl_finds_all_pairs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cif_dir = repo_root / "tests" / "fixtures" / "cifs"

    result = collect_required_pair_distances(
        cif_dir=cif_dir,
        formula="NaCl",
        cutoff=6.0,
        supercell=(1, 1, 1),
    )

    assert result["required_pairs"] == ["Cl-Cl", "Cl-Na", "Na-Na"]
    assert result["missing_pairs"] == []
    assert result["sparse_pairs"] == []
    for pair in ("Cl-Cl", "Cl-Na", "Na-Na"):
        distances = result["pair_histograms"][pair]
        assert distances
        assert all(distance > 0.0 for distance in distances)
        assert result["pair_stats"][pair]["count"] == len(distances)


def test_required_pair_extraction_fixture_finishes_under_10s() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    cif_dir = repo_root / "tests" / "fixtures" / "cifs"

    t0 = perf_counter()
    result = collect_required_pair_distances(
        cif_dir=cif_dir,
        formula="NaCl",
        cutoff=6.0,
        supercell=(1, 1, 1),
        max_distances_per_pair=128,
    )

    assert perf_counter() - t0 < 10
    assert result["pair_stats"]["Cl-Cl"]["count"] > 0
    assert result["max_distances_per_pair"] == 128
