"""Emit a stable SPP source/package parity signature on a synthetic CIF corpus."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from ase import Atoms
from ase.io import write


if os.getenv("SPP_PARITY_IMPL") == "source":
    from spp_maker.score import score_atoms
    from spp_maker.spp_model import load_spp_model
    from spp_maker_qlip.required_pair_extraction import export_required_pair_spp_root
else:
    from llm_csp.spp import export_required_pair_spp_root, score_atoms
    from llm_csp.spp.model import load_spp_model


def main() -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        corpus = root / "cifs"
        corpus.mkdir()
        atoms = Atoms(
            "NaCl", scaled_positions=[[0, 0, 0], [0.5, 0.5, 0.5]],
            cell=[5.6, 5.6, 5.6], pbc=True,
        )
        write(corpus / "synthetic.cif", atoms, format="cif")
        output = root / "spp_root"
        result = export_required_pair_spp_root(
            cif_dir=corpus, formula="NaCl", out_root=output, name="parity",
            cutoff=6.0, supercell=(1, 1, 1), max_distances_per_pair=128,
        )
        hashes = {
            str(path.relative_to(output)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.rglob("*.POT"))
        }
        model = load_spp_model(output)
        score = score_atoms(atoms, model, r_cut=6.0, use_bandpass=False)
        signature = {
            "required_pairs": result["required_pairs"],
            "fitted_pairs": result["fitted_pairs"],
            "missing_pairs": result["missing_pairs"],
            "pair_stats": result["pair_stats"],
            "pot_hashes": hashes,
            "score": {
                "total": round(score.total, 12),
                "num_edges": score.num_edges,
                "num_scored_edges": score.num_scored_edges,
                "skipped_missing_pair": score.skipped_missing_pair,
            },
        }
        print(json.dumps(signature, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
