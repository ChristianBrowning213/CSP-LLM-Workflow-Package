from scripts.validate_paper_results_redesign import validate


def test_final_paper_results_redesign_package() -> None:
    result = validate()
    assert result["status"] == "PASS"
    assert result["valid_primary_spp"] == 0
