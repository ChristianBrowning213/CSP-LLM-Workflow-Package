"""Run the frozen NASICON/NZP framework topology proxy for one CIF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pymatgen.core import Structure

from build_nasicon_specialist_corpus import framework_metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cif", type=Path, required=True)
    args = parser.parse_args()
    structure = Structure.from_file(args.cif)
    metrics = framework_metrics(structure)
    passed = bool(
        structure.is_ordered
        and metrics["coordination_all_expected"]
        and metrics["framework_components"] == 1
        and metrics["framework_dimensionality"] == 3
    )
    print(json.dumps({"topology_status": "PASS" if passed else "FAIL", "topology_policy": "nasicon_ordered_coordination_single_component_rank3_proxy_v1", "metrics": metrics}, sort_keys=True))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
