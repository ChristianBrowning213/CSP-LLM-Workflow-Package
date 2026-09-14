"""Print a copy/paste QLIP integration snippet for a chosen SPP root."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Print a ready-to-copy QLIP SPP snippet.")
    parser.add_argument(
        "--spp_root",
        type=Path,
        default=Path("out/demo_prop_spp/demo/spp_all"),
        help="SPP root directory to point QLIP to.",
    )
    parser.add_argument(
        "--var_name",
        default="spp_dir",
        help="Variable name used for the SPP root path in the snippet.",
    )
    args = parser.parse_args()

    spp_root = args.spp_root.as_posix()
    var_name = args.var_name.strip() or "spp_dir"

    print(f'{var_name} = "{spp_root}"')
    print(f"collection = SPPCollection({var_name})")
    print("collection.load(task.pairs)")
    print("allocation.spp_collection = collection   # if your QLIP integration exposes this slot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
