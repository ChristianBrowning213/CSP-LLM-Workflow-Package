from __future__ import annotations

from pathlib import Path

from sok_llm_orchestrator.skills.loader import load_skillcards, validate_skillcards


def test_skillcards_validate() -> None:
    root = Path(__file__).resolve().parents[1]
    skills_dir = root / "skills"
    errors = validate_skillcards(skills_dir)
    assert errors == []
    cards = load_skillcards(skills_dir)
    ids = {card["id"] for card in cards}
    assert "crystaldb.csp_pack" in ids
    assert "spp.run_pipeline" in ids
    assert "qlip.solve" in ids
