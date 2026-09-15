from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def describe(cif_path: Path) -> dict[str, Any]:
    result = {
        "robocrys_available": False,
        "description": None,
        "condensed_structure": None,
        "engine": "robocrys",
        "text_view": "robocrys",
        "robocrys_version": None,
        "cif_path": str(cif_path),
        "warnings": [],
        "error": None,
    }
    try:
        from pymatgen.core import Structure  # type: ignore
        from robocrys import StructureCondenser, StructureDescriber  # type: ignore
        import robocrys  # type: ignore
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"import_failed:{type(exc).__name__}: {exc}"
        return result
    if not cif_path.is_file():
        result["error"] = "no_solution_cif"
        return result
    try:
        structure = Structure.from_file(str(cif_path))
        condensed = StructureCondenser().condense_structure(structure)
        description_text = StructureDescriber().describe(condensed)
        result.update(
            {
                "robocrys_available": True,
                "description": str(description_text),
                "condensed_structure": condensed,
                "robocrys_version": str(getattr(robocrys, "__version__", "")) or None,
                "error": None,
            }
        )
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"describe_failed:{type(exc).__name__}: {exc}"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Describe a CIF with robocrys and print strict JSON.")
    parser.add_argument("--cif", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(describe(args.cif), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
