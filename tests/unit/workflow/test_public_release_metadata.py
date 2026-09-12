from __future__ import annotations

import tomllib
from pathlib import Path


def test_validation_extra_pins_licensed_sca_without_making_it_mandatory() -> None:
    root = Path(__file__).resolve().parents[3]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"].get("optional-dependencies", {})

    assert not any(
        item.casefold().startswith("sca") for item in metadata["project"]["dependencies"]
    )
    assert extras["validation"] == [
        "sca @ git+https://github.com/ChristianBrowning213/Structured_Crystal_Analyser.git@3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af"
    ]
