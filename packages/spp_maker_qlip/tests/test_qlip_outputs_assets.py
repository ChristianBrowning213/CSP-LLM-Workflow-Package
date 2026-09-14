"""Tests for QLIP integration asset files."""

from __future__ import annotations

from pathlib import Path


def test_integration_md_exists_and_mentions_sppcollection() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    integration_md = repo_root / "QLIP_Outputs" / "INTEGRATION.md"
    assert integration_md.exists()
    content = integration_md.read_text(encoding="utf-8")
    assert "SPPCollection" in content
