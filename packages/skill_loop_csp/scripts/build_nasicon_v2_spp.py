"""Generate frozen-parameter 6 Å SPP diagnostics for NASICON v2 corpora."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FORMULA = "Na3Zr2Si2PO12"
CONDITIONS = {
    "full": "nasicon_specialist_v2",
    "leave_target_out": "nasicon_specialist_leave_target_out_v2",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spp-repo",
        type=Path,
        default=REPO_ROOT.parent / "SPP-Maker-QLIP",
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=REPO_ROOT / "artifacts" / "nasicon_spp_v2_frozen",
    )
    args = parser.parse_args()
    sys.path.insert(0, str((args.spp_repo.resolve() / "src")))
    from spp_maker_qlip.required_pair_extraction import export_required_pair_spp_root

    summaries: dict[str, object] = {}
    for short_name, corpus_id in CONDITIONS.items():
        condition_root = args.out_root / short_name
        spp_root = condition_root / "spp_root"
        if spp_root.exists():
            raise FileExistsError(f"Refusing to overwrite frozen output: {spp_root}")
        result = export_required_pair_spp_root(
            cif_dir=REPO_ROOT / "data" / "corpora" / corpus_id / "cifs",
            formula=FORMULA,
            out_root=spp_root,
            name=f"{corpus_id}_6a",
            cutoff=6.0,
            supercell=None,
            alpha=1e-3,
            d_min=1.0,
            bin_width=0.05,
            max_distances_per_pair=None,
            max_cap_fraction_threshold=0.5,
        )
        (condition_root / "generation_result_6a.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        quality = result["spp_pot_quality"]
        summaries[short_name] = {
            "corpus_id": corpus_id,
            "corpus_cif_count": result["corpus_cif_count"],
            "required_pair_count": len(result["required_pairs"]),
            "missing_pairs": result["missing_pairs"],
            "sparse_pairs": result["sparse_pairs"],
            "spp_pot_quality_status": quality.get("spp_pot_quality_status"),
            "failing_pairs": [
                row["pair"]
                for row in quality.get("pairs", [])
                if row.get("pot_quality") != "usable"
            ],
            "generation_ok": result["ok"],
        }
    args.out_root.mkdir(parents=True, exist_ok=True)
    (args.out_root / "summary.json").write_text(
        json.dumps(summaries, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summaries, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
