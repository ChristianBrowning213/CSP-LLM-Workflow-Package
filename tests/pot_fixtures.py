"""Newly authored software-test POT fixtures.

NOT SCIENTIFIC POTENTIALS. TEST FIXTURE ONLY.
The values below test parsing, pair coverage, and orchestration mechanics only.
"""

from __future__ import annotations

from pathlib import Path


def write_synthetic_pot_root(root: Path, pairs: list[str] | tuple[str, ...]) -> Path:
    for index, pair in enumerate(pairs, start=1):
        path = root / pair / f"{pair}.POT"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            "# NOT SCIENTIFIC POTENTIALS - TEST FIXTURE ONLY",
            "# r(Ang) U(test-units)",
        ]
        rows.extend(
            f"{distance:.1f} {index / distance:.8f}"
            for distance in (1.0, 2.0, 4.0, 8.0, 12.0)
        )
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root
