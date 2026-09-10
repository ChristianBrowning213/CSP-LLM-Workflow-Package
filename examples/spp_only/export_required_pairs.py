"""Export the six canonical SrTiO3 POTs from packaged QLIP resources."""

import argparse
import json
from pathlib import Path

from llm_csp.spp import export_required_pot_subset
from qlip.resources import bundled_spp_root


parser = argparse.ArgumentParser()
parser.add_argument("output_root", type=Path, help="Empty writable output directory")
parser.add_argument("--source-pot-root", type=Path, default=bundled_spp_root())
args = parser.parse_args()

result = export_required_pot_subset(
    formula="SrTiO3",
    source_pot_root=args.source_pot_root,
    output_root=args.output_root,
)
print(json.dumps({
    "status": result["status"],
    "required_pairs": result["required_pairs"],
    "missing_pairs": result["missing_pairs"],
    "output_root": result["output_root"],
}, indent=2))
