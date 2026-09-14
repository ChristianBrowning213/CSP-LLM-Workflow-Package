"""Build auditable next-method SPP artifacts without modifying frozen v4 results."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

from spp_maker.common_contract import (
    CONTRACT_ID, blend_contract_roots, build_local_supercell_artifact,
)
from spp_maker.pot_io import read_pot_like_qlip


CRYSTAL = Path(__file__).resolve().parents[1]
SKILL = CRYSTAL.parent / "Skill-Loop-CSP"
SPP = CRYSTAL.parent / "SPP-Maker-QLIP"
QLIP = CRYSTAL.parent / "qlip"
OUT = CRYSTAL / "artifacts" / "spp_methodology_dmytro_gr_v1"
V4_LI = CRYSTAL / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results" / "paper_workflow_li2feo3"
LI_RUN = QLIP / "gen_artifacts" / "skill_loop_csp" / "runs" / "layered-repaired-041-87c9b45e47dd-attempt-001-pair-aware-01" / "attempts" / "spp-only-v1"
REGULATOR = QLIP / "data" / "spp" / "regulators" / "icsd_broad_regulator_v1"
COAS_SOURCE = SPP / "out" / "coas2_source_cifs"
COAS_REFERENCE = SPP / "out" / "SPP_Runs" / "20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_89617d59" / "fit" / "spp_root"
COAS_SCALED = SPP / "QLIP_Outputs" / "SPP" / "runs" / "20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305" / "spp_root"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def pot(root: Path, pair: str) -> Path:
    for directory in root.iterdir():
        if directory.is_dir() and directory.name.casefold() == pair.casefold():
            candidates = sorted(directory.glob("*.POT"))
            if candidates:
                return candidates[0]
    raise FileNotFoundError(f"{pair} missing from {root}")


def rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    coas_root = OUT / "coas2_regression" / "rebuilt_local"
    coas_meta = build_local_supercell_artifact(cif_dir=COAS_SOURCE, out_root=coas_root,
                                                name="coas2_dmytro_gr_v1_regression")
    coas_rows = []
    for pair in ("As-As", "As-Co", "Co-Co"):
        rr, reference = read_pot_like_qlip(pot(COAS_REFERENCE, pair))
        rb, rebuilt = read_pot_like_qlip(pot(coas_root, pair))
        _, scaled = read_pot_like_qlip(pot(COAS_SCALED, pair))
        coas_rows.append({
            "pair": pair, "contract": CONTRACT_ID, "bins": len(rb),
            "grid_max_abs_error": float(np.max(np.abs(rr - rb))),
            "unscaled_potential_max_abs_error": float(np.max(np.abs(reference - rebuilt))),
            "unscaled_potential_rms_error": rms(reference - rebuilt),
            "minimum_position_error_A": abs(float(rr[np.argmin(reference)]) - float(rb[np.argmin(rebuilt)])),
            "repulsive_region_max_abs_error_0p025_1p5A": float(np.max(np.abs(reference[rr <= 1.5] - rebuilt[rb <= 1.5]))),
            "rebuilt_to_reference_amplitude_rms_ratio": rms(rebuilt) / rms(reference),
            "historical_scaled_to_unscaled_rms_ratio": rms(scaled) / rms(reference),
            "rebuilt_sha256": sha(pot(coas_root, pair)),
        })
    write_csv(OUT / "COAS2_DMYTRO_COMPATIBILITY_AUDIT.csv", coas_rows)
    (OUT / "COAS2_DMYTRO_COMPATIBILITY.md").write_text(
        "# CoAs2 Dmytro-contract regression\n\n"
        "The source CIF was rebuilt with the common contract and compared against the preserved, "
        "unscaled historical fit. The regression acceptance condition is a common 200-bin grid and "
        "maximum potential error <= 1e-8 for every pair. The later historical calibration scalar is "
        "reported separately and is not part of the common artifact contract.\n\n"
        f"Result: **{'PASS' if all(row['unscaled_potential_max_abs_error'] <= 1e-8 for row in coas_rows) else 'FAIL'}**.\n",
        encoding="utf-8",
    )

    with (V4_LI / "SPP_PAIR_PROVENANCE.csv").open(encoding="utf-8", newline="") as handle:
        provenance = list(csv.DictReader(handle))
    evidence = {row["pair"]: {"structures_contributing": int(row["request_supporting_structures"]),
                               "observations": int(row["request_observations"])} for row in provenance}
    li_local = OUT / "li2feo3_offline_rebuild" / "local_common_contract"
    li_meta = build_local_supercell_artifact(cif_dir=LI_RUN / "spp_evidence", out_root=li_local,
                                              name="li2feo3_offline_local_dmytro_gr_v1")
    li_blend = OUT / "li2feo3_offline_rebuild" / "blended_complete_root"
    blend_manifest = blend_contract_roots(
        local_root=li_local, regulator_root=REGULATOR, out_root=li_blend,
        required_pairs=[row["pair"] for row in provenance], pair_evidence=evidence,
        name="li2feo3_pair_level_blend_v1",
    )
    blend_by_pair = {row["pair"]: row for row in blend_manifest["pairs"]}
    li_rows = []
    centers = np.arange(0.025, 10.0, 0.05)
    comparison_window = (centers >= 1.75) & (centers <= 6.0)
    for row in provenance:
        pair = row["pair"]
        old_request_r, old_request_u = read_pot_like_qlip(Path(row["request_pot_path"]))
        old_global_r, old_global_u = read_pot_like_qlip(Path(row["global_pot_path"]))
        old_request = np.interp(centers, old_request_r, old_request_u, left=0.0, right=0.0)
        old_global = np.interp(centers, old_global_r, old_global_u, left=0.0, right=0.0)
        _, local_u = read_pot_like_qlip(pot(li_local, pair))
        global_common = OUT / "li2feo3_offline_rebuild" / "global_common_contract"
        _, global_u = read_pot_like_qlip(pot(global_common, pair))
        blend = blend_by_pair[pair]
        old_ratio = rms(2.0 * old_global[comparison_window]) / max(rms(old_request[comparison_window]), 1e-30)
        new_ratio = rms(float(blend["global_weight"]) * global_u[comparison_window]) / max(rms(local_u[comparison_window]), 1e-30)
        old_final = old_request + 2.0 * old_global
        new_final = local_u + float(blend["global_weight"]) * global_u
        li_rows.append({
            "pair": pair, "old_request_contract": "v4_shifted_histogram_lambda_scaled",
            "old_request_lambda": row["request_lambda"], "old_global_weight": row["global_weight"],
            "old_weighted_global_to_local_rms_ratio": old_ratio,
            "new_contract": CONTRACT_ID, "new_blend_mode": blend["mode"],
            "new_local_weight": blend["local_weight"], "new_global_weight": blend["global_weight"],
            "supporting_structures": evidence[pair]["structures_contributing"],
            "effective_observations": evidence[pair]["observations"],
            "evidence_confidence": blend["confidence"],
            "rms_comparison_window_A": "1.75-6.0",
            "old_request_component_rms": rms(old_request[comparison_window]),
            "old_global_component_weighted_rms": rms(2.0 * old_global[comparison_window]),
            "old_final_component_rms": rms(old_final[comparison_window]),
            "new_request_component_rms": rms(local_u[comparison_window]),
            "new_global_component_weighted_rms": rms(float(blend["global_weight"]) * global_u[comparison_window]),
            "new_final_component_rms": rms(new_final[comparison_window]),
            "new_weighted_global_to_local_rms_ratio": new_ratio,
            "dominance_ratio_reduction_factor": old_ratio / max(new_ratio, 1e-30),
        })
    write_csv(OUT / "LI2FEO3_SPP_BEFORE_AFTER_COMPARISON.csv", li_rows)
    (OUT / "LI2FEO3_SPP_BEFORE_AFTER_COMPARISON.md").write_text(
        "# Li2FeO3 offline before/after scale audit\n\n"
        "This rebuild uses the same 30 non-target retrieved CIFs but writes to a new methodology "
        "directory. All six pairs use the common unshifted supercell g(r) transform. Local evidence "
        "has unit weight; the common-grid broad prior has a deterministic 5--20% evidence-dependent "
        "weight. Global-only mode is permitted only when the local pair is absent or invalid. The "
        "frozen v4 request and regulator files were read-only inputs.\n\n"
        f"Pairs rebuilt: {len(li_rows)}; local-primary pairs: "
        f"{sum(row['new_blend_mode'].startswith('LOCAL_PRIMARY') for row in li_rows)}.\n",
        encoding="utf-8",
    )
    (OUT / "SPP_BLEND_POLICY.json").write_text(
        json.dumps(blend_manifest["blend_policy"] | {"artifact_contract": CONTRACT_ID}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(OUT / "SPP_BLEND_CALIBRATION.csv", [{
        "pair": row["pair"], "structures_contributing": row["structures_contributing"],
        "observations": row["observations"], "confidence": row["confidence"],
        "mode": row["mode"], "local_weight": row["local_weight"], "global_weight": row["global_weight"],
    } for row in blend_manifest["pairs"]])
    (OUT / "audit_manifest.json").write_text(json.dumps({
        "artifact_contract": CONTRACT_ID, "coas2": coas_meta, "li2feo3": li_meta,
        "frozen_v4_modified": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
