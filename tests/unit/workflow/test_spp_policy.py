import shutil

from llm_csp.schemas import SPPConfig
from llm_csp.workflow.spp_policy import prepare_spp_guidance
from qlip.resources import bundled_spp_root


PAIRS = ["O-O", "O-Sr", "O-Ti", "Sr-Sr", "Sr-Ti", "Ti-Ti"]


def test_regulator_only_policy_preserves_all_pair_hashes(tmp_path) -> None:
    result = prepare_spp_guidance(
        formula="SrTiO3",
        evidence=(),
        config=SPPConfig(request_mode="disabled", regulator_root=bundled_spp_root()),
        output_root=tmp_path / "spp",
    )
    assert result["ready"] is True
    assert result["required_pairs"] == PAIRS
    assert result["regulator_fallback_pairs"] == PAIRS
    assert all(row["guidance_mode"] == "REGULATOR_ONLY_REQUEST_DISABLED" for row in result["pair_decisions"])
    assert all(row["regulator_sha256"] for row in result["pair_decisions"])


def test_missing_regulator_pair_blocks_before_qlip(tmp_path) -> None:
    incomplete = tmp_path / "source"
    for pair in PAIRS[:-1]:
        source = bundled_spp_root() / pair / f"{pair}.POT"
        destination = incomplete / pair / f"{pair}.POT"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)

    result = prepare_spp_guidance(
        formula="SrTiO3",
        evidence=(),
        config=SPPConfig(request_mode="disabled", regulator_root=incomplete),
        output_root=tmp_path / "spp",
    )
    assert result["ready"] is False
    assert result["status"] == "spp_incomplete"
    assert result["missing_pairs"] == ["Ti-Ti"]


def test_missing_source_root_has_distinct_configuration_error(tmp_path) -> None:
    import pytest

    with pytest.raises(ValueError, match="source POT root is not a directory"):
        prepare_spp_guidance(
            formula="SrTiO3",
            evidence=(),
            config=SPPConfig(request_mode="disabled", regulator_root=tmp_path / "absent"),
            output_root=tmp_path / "spp",
        )


def test_invalid_regulator_pot_blocks_before_qlip(tmp_path) -> None:
    source_root = tmp_path / "source"
    for pair in PAIRS:
        source = bundled_spp_root() / pair / f"{pair}.POT"
        destination = source_root / pair / f"{pair}.POT"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)
    (source_root / "O-O" / "O-O.POT").write_text("not a POT\n", encoding="utf-8")

    result = prepare_spp_guidance(
        formula="SrTiO3",
        evidence=(),
        config=SPPConfig(request_mode="disabled", regulator_root=source_root),
        output_root=tmp_path / "spp",
    )

    assert result["ready"] is False
    assert result["reason"] == "regulator_pair_quality_failed"
    assert result["unusable_pairs"] == ["O-O"]
