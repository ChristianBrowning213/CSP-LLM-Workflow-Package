"""Validate exported POT files for QLIP-style compatibility."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow running this script without editable install.
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

from spp_maker.pot_compat import check_pot_root, render_compat_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check POT files for QLIP compatibility.")
    parser.add_argument("--spp_root", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    spp_root = args.spp_root
    if not spp_root.is_dir():
        print(f"Error: --spp_root is not a directory: {spp_root}")
        return 1

    report = check_pot_root(spp_root, strict=args.strict)
    print(render_compat_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
