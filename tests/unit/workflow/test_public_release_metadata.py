from __future__ import annotations

import tomllib
from pathlib import Path


def test_validation_extra_uses_bundled_sca_without_vcs_fetch() -> None:
    root = Path(__file__).resolve().parents[3]
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extras = metadata["project"].get("optional-dependencies", {})

    assert not any(
        item.casefold().startswith("sca") for item in metadata["project"]["dependencies"]
    )
    assert extras["validation"] == [
        "click>=8",
        "pandas>=2",
        "pydantic>=2",
        "rich>=13",
        "tqdm>=4.60",
        "typer>=0.12,<0.25",
    ]
    assert not any("git+" in item for item in extras["validation"])
