from __future__ import annotations

import tomllib
from pathlib import Path


def test_public_metadata_does_not_install_unlicensed_sca() -> None:
    root = Path(__file__).resolve().parents[3]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"].get("optional-dependencies", {})

    assert "validation" not in extras
    declared = [*metadata["project"]["dependencies"]]
    declared.extend(item for values in extras.values() for item in values)
    assert not any(item.casefold().startswith("sca") for item in declared)
