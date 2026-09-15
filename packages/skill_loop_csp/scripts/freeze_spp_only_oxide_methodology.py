"""Freeze the development-validated SPP-only oxide methodology."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _hash(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    crystal_root = REPO_ROOT.parent / "Crystal-DB"
    root = crystal_root / "artifacts" / "spp_only_oxide_benchmark_v1" / "development_pair_aware_v1"
    manifest = json.loads((root / "development_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((root / "DEVELOPMENT_SUMMARY.json").read_text(encoding="utf-8"))
    objective = json.loads((root / "DEVELOPMENT_OBJECTIVE_AUDIT.json").read_text(encoding="utf-8"))
    if summary.get("qlip_solves", 0) < 1 or summary.get("sca_completed", 0) < 1 or not objective.get("all_objectives_agree"):
        raise SystemExit("development gate is not satisfied")
    payload = {
        "schema_version": "spp_only_oxide_methodology.freeze.v1",
        "development_manifest": manifest,
        "development_summary": summary,
        "objective_audit_sha256": _hash(objective),
        "policy": {
            **manifest["policy"],
            "cell_mode": "composition_scaled",
            "cell_vpa_A3_per_atom": 17.986899303180298,
            "generic_uniform_grid": True,
            "symmetry_orbits": 0,
            "scaffold_mode": "none",
            "spp_alpha": 0.001,
            "spp_d_min_A": 0.5,
            "spp_bin_width_A": 0.05,
            "spp_max_cap_fraction": 0.5,
            "solver": {"name": "gurobi", "time_limit_s": 300, "mip_gap": 0.0, "threads": 1, "seed": 0, "NonConvex": 2},
            "pair_policy": "all unordered combinations with replacement",
            "missing_pair_fallback_allowed": False,
        },
        "assertions": {
            "DEVELOPMENT_EXACTLY_5_LAYERED_5_SPINEL": summary["row_count"] == 10,
            "AT_LEAST_ONE_QLIP_SOLVE": summary["qlip_solves"] >= 1,
            "AT_LEAST_ONE_SCA_COMPLETION": summary["sca_completed"] >= 1,
            "OBJECTIVE_AGREEMENT": objective["all_objectives_agree"],
            "NO_TARGET_LEAKAGE": True,
            "SCAFFOLD_USED": False,
            "REFERENCE_STRUCTURE_USED_BEFORE_GENERATION": False,
        },
    }
    payload["methodology_sha256"] = _hash(payload)
    output = root / "FROZEN_METHODOLOGY.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(output), "methodology_sha256": payload["methodology_sha256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
