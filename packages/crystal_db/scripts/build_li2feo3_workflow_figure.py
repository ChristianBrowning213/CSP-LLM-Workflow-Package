"""Build the Li2FeO3 Figure 1 bundle from frozen v4 artifacts.

This script is deliberately offline: it reads persisted retrieval, POT, QLIP
and SCA products, performs numerical audits, and invokes VESTA only for image
export.  It never calls retrieval, SPP fitting, QLIP, generation, or SCA.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from ase import Atoms
from ase.io import read as ase_read
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from PIL import Image
from scipy.interpolate import interp1d


CRYSTAL = Path(r"C:\Users\brown\Documents\GitHub\Crystal-DB")
SKILL = Path(r"C:\Users\brown\Documents\GitHub\Skill-Loop-CSP")
QLIP = Path(r"C:\Users\brown\Documents\GitHub\qlip")
SPP_MAKER = Path(r"C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP")
RESULTS = CRYSTAL / "artifacts" / "spp_only_oxide_benchmark_v4_taxonomy_fixed" / "results"
RUN = RESULTS / "runs" / "layered" / "layered-repaired-041"
BUNDLE = RESULTS / "paper_workflow_li2feo3"
CURVES = BUNDLE / "spp_curves"
FIGURE = RESULTS / "paper_figures" / "figure_1_li2feo3_workflow"
VESTA_ASSETS = FIGURE / "vesta_renders"
VESTA_EXE = Path(r"C:\Users\brown\Documents\VESTA-win64\VESTA-win64\VESTA.exe")
REQUEST_ROOT = QLIP / "gen_artifacts" / "skill_loop_csp" / "runs" / (
    "layered-repaired-041-87c9b45e47dd-attempt-001-pair-aware-01"
) / "attempts" / "spp-only-v1" / "request_spp" / "supported_pairs"
NA_REQUEST = QLIP / "gen_artifacts" / "skill_loop_csp" / "runs" / (
    "spinel-repaired-046-87c9b45e47dd-attempt-001-pair-aware-01"
) / "attempts" / "spp-only-v1" / "request_spp" / "supported_pairs" / "O-O" / "O-O.POT"
REGULATOR = QLIP / "data" / "spp" / "regulators" / "icsd_broad_regulator_v1"

PAIRS = ("Fe-Fe", "Fe-Li", "Fe-O", "Li-Li", "Li-O", "O-O")
DISPLAY_PAIRS = ("Li-Li", "Fe-Li", "Li-O", "Fe-Fe", "Fe-O", "O-O")
REQUEST_WEIGHT = 1.0
GLOBAL_WEIGHT = 2.0
OUTER_WEIGHT = 10.0
CELL_EDGE = 4.761047538838345

INK = "#17252E"
NAVY = "#173B57"
BLUE = "#2C6E9F"
TEAL = "#278A86"
GOLD = "#C48A20"
GREEN = "#34865A"
MUTED = "#61717B"
GRID = "#D9E2E6"
CARD = "#F7F9FA"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def pot_path(root: Path, pair: str) -> Path:
    token = pair.upper()
    return root / token / f"{token}.POT"


def load_pot(path: Path) -> tuple[np.ndarray, np.ndarray]:
    x: list[float] = []
    y: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        try:
            x.append(float(fields[0]))
            y.append(float(fields[1]))
        except ValueError:
            continue
    if len(x) < 4:
        raise ValueError(f"POT has fewer than four numeric points: {path}")
    return np.asarray(x), np.asarray(y)


def pot_function(path: Path):
    x, y = load_pot(path)
    return interp1d(x, y, kind="cubic", bounds_error=False, fill_value=0.0), x, y


def metrics(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(values.min()),
        "max": float(values.max()),
        "peak_to_peak": float(np.ptp(values)),
        "rms": float(np.sqrt(np.mean(values * values))),
        "mean_absolute": float(np.mean(np.abs(values))),
    }


def build_scale_audit() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    cases = [("NaTi2O4", "O-O", NA_REQUEST)] + [
        ("Li2FeO3", pair, pot_path(REQUEST_ROOT, pair)) for pair in PAIRS
    ]
    rows: list[dict[str, Any]] = []
    curve_data: dict[str, dict[str, Any]] = {}
    for system, pair, request_path in cases:
        global_path = pot_path(REGULATOR, pair)
        request_fn, request_x, _ = pot_function(request_path)
        global_fn, global_x, _ = pot_function(global_path)
        if system == "Li2FeO3":
            dense = np.linspace(0.0, 11.0, 2201)
            request = np.asarray(request_fn(dense), dtype=float)
            global_raw = np.asarray(global_fn(dense), dtype=float)
            curve_data[pair] = {
                "distance": dense,
                "request": request,
                "global": global_raw,
                "final": REQUEST_WEIGHT * request + GLOBAL_WEIGHT * global_raw,
                "request_path": request_path,
                "global_path": global_path,
            }
        for domain, lo, hi in (("physical_plot_interval", 1.75, 6.0), ("production_cutoff_domain", 0.0, 11.0)):
            distance = np.linspace(lo, hi, int(round((hi - lo) / 0.001)) + 1)
            request = np.asarray(request_fn(distance), dtype=float)
            global_raw = np.asarray(global_fn(distance), dtype=float)
            rm = metrics(request)
            gm = metrics(global_raw)
            weighted_request_rms = REQUEST_WEIGHT * rm["rms"]
            weighted_global_rms = GLOBAL_WEIGHT * gm["rms"]
            rows.append({
                "system": system,
                "pair": pair,
                "domain": domain,
                "distance_min_A": lo,
                "distance_max_A": hi,
                "sample_spacing_A": 0.001,
                "sample_count": len(distance),
                "request_weight": REQUEST_WEIGHT,
                "global_weight": GLOBAL_WEIGHT,
                "request_min": rm["min"],
                "request_max": rm["max"],
                "request_peak_to_peak": rm["peak_to_peak"],
                "raw_request_RMS": rm["rms"],
                "request_mean_absolute": rm["mean_absolute"],
                "global_min": gm["min"],
                "global_max": gm["max"],
                "global_peak_to_peak": gm["peak_to_peak"],
                "raw_global_RMS": gm["rms"],
                "global_mean_absolute": gm["mean_absolute"],
                "weighted_request_RMS": weighted_request_rms,
                "weighted_global_RMS": weighted_global_rms,
                "global_to_request_ratio": weighted_global_rms / weighted_request_rms,
                "request_grid_min_A": float(request_x.min()),
                "request_grid_max_A": float(request_x.max()),
                "request_grid_points": len(request_x),
                "global_grid_min_A": float(global_x.min()),
                "global_grid_max_A": float(global_x.max()),
                "global_grid_points": len(global_x),
                "request_pot_path": str(request_path.resolve()),
                "global_pot_path": str(global_path.resolve()),
            })
    return rows, curve_data


def periodic_sum_vector(frac_i: np.ndarray, frac_j: np.ndarray, potential, cell_edge: float) -> float:
    # Same depth and acceptance rule as qlip.interactions.spp.periodic_spp_sum.
    depth = int(math.ceil(11.0 / cell_edge) + 1)
    shifts = np.asarray(list(np.ndindex(*(2 * depth + 1,) * 3)), dtype=float) - depth
    distances = np.linalg.norm((frac_j + shifts - frac_i) * cell_edge, axis=1)
    keep = (distances > 1e-12) & (distances <= 11.0)
    return float(np.sum(potential(distances[keep])))


def build_coefficient_audit(curves: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    grid = np.asarray(list(np.ndindex(4, 4, 4)), dtype=float) / 4.0
    rows: list[dict[str, Any]] = []
    for pair in PAIRS:
        request_fn, _, _ = pot_function(curves[pair]["request_path"])
        global_fn, _, _ = pot_function(curves[pair]["global_path"])
        request_terms: list[float] = []
        global_terms: list[float] = []
        same = pair.split("-")[0] == pair.split("-")[1]
        for i in range(64):
            for j in range(i if same else i + 1, 64):
                request_terms.append(periodic_sum_vector(grid[i], grid[j], request_fn, CELL_EDGE))
                global_terms.append(periodic_sum_vector(grid[i], grid[j], global_fn, CELL_EDGE))
        request_values = np.asarray(request_terms)
        global_values = np.asarray(global_terms)
        if not same:
            # Allocation emits both chemical orientations for every i<j.
            request_values = np.repeat(request_values, 2)
            global_values = np.repeat(global_values, 2)
        request_derived = OUTER_WEIGHT * REQUEST_WEIGHT * request_values
        global_derived = OUTER_WEIGHT * GLOBAL_WEIGHT * global_values
        final = request_derived + global_derived
        rm, gm, fm = metrics(request_derived), metrics(global_derived), metrics(final)
        rows.append({
            "pair": pair,
            "recovery_status": "reconstructed_from_persisted_inputs_no_solver_run",
            "site_count": 64,
            "site_pair_objective_terms": len(final),
            "request_derived_min": rm["min"],
            "request_derived_max": rm["max"],
            "request_derived_RMS": rm["rms"],
            "global_derived_min": gm["min"],
            "global_derived_max": gm["max"],
            "global_derived_RMS": gm["rms"],
            "final_coefficient_min": fm["min"],
            "final_coefficient_max": fm["max"],
            "final_coefficient_RMS": fm["rms"],
            "global_to_request_coefficient_RMS_ratio": gm["rms"] / rm["rms"],
            "request_weight": REQUEST_WEIGHT,
            "global_weight": GLOBAL_WEIGHT,
            "outer_objective_weight": OUTER_WEIGHT,
        })
    return rows


def source_formula(hit: dict[str, Any]) -> str:
    text = str(hit.get("text_doc", {}).get("text", ""))
    match = re.match(r"([^ ]+) is ", text)
    return match.group(1) if match else ""


def bundle_inputs(scale_rows: list[dict[str, Any]], curves: dict[str, dict[str, Any]], coefficients: list[dict[str, Any]]) -> list[dict[str, Any]]:
    BUNDLE.mkdir(parents=True, exist_ok=True)
    CURVES.mkdir(parents=True, exist_ok=True)
    retrieval = load_json(RUN / "retrieval" / "results.json")
    exclusions = load_json(RUN / "retrieval" / "exclusions.json")
    summary = load_json(RUN / "run_summary.json")
    target = load_json(RUN / "target_manifest.json")
    preflight = load_json(RUN / "spp" / "artifact_preflight.json")
    sca = load_json(RUN / "sca" / "result.json")
    selected = retrieval["selected"]
    if len(selected) != 30 or [row["rank"] for row in selected[:6]] != [1, 2, 3, 5, 6, 7]:
        raise RuntimeError("Persisted retrieval selection differs from approved Li2FeO3 case")
    selected_by_id = {row["structure_id"]: row for row in selected}
    audit_rows = []
    for decision in exclusions:
        hit = selected_by_id.get(decision["structure_id"])
        audit_rows.append({
            "structure_id": decision["structure_id"],
            "decision": decision["decision"],
            "reason": decision["reason"],
            "selected_rank": "" if hit is None else hit["rank"],
            "score": "" if hit is None else hit["score"],
            "source_id": "" if hit is None else hit["provenance"]["source_id"],
            "formula": "" if hit is None else source_formula(hit),
            "entered_spp_maker": hit is not None,
        })
    write_csv(BUNDLE / "RETRIEVAL_AUDIT.csv", audit_rows)
    neighbour_rows = []
    retrieved_dir = RUN / "retrieval" / "retrieved_cifs"
    for display_index, hit in enumerate(selected[:6], 1):
        cif = retrieved_dir / f"{hit['structure_id']}.cif"
        formula = source_formula(hit)
        label = formula
        if formula == "Li2FeO3":
            label += f" polymorph {sum(source_formula(x) == 'Li2FeO3' for x in selected[:display_index])}"
        elif formula == "LiFeO2" and sum(source_formula(x) == "LiFeO2" for x in selected[:display_index]) > 1:
            label += " polymorph 2"
        neighbour_rows.append({
            "display_index": display_index,
            "retrieval_rank": hit["rank"],
            "source": hit["provenance"]["source"],
            "source_id": hit["provenance"]["source_id"],
            "structure_id": hit["structure_id"],
            "formula": formula,
            "display_label": label,
            "similarity_score": hit["score"],
            "source_cif_path": str(cif.resolve()),
            "source_cif_sha256": sha256(cif),
            "entered_spp_maker": True,
            "pair_contributions": ";".join(PAIRS),
            "distinct_database_structure": True,
        })
    write_csv(BUNDLE / "RETRIEVAL_NEIGHBOURS.csv", neighbour_rows)

    diagnostics = preflight["pair_diagnostics"]
    evidence_rows = [{
        "pair": row["pair"],
        "supporting_structure_count": row["local_structure_count"],
        "periodic_distance_observation_count": row["local_observation_count"],
        "request_pair_status": row["request_pair_status"],
        "distance_cutoff_A": 11.0,
        "corpus_structure_count": 30,
    } for row in diagnostics]
    write_csv(BUNDLE / "PAIR_DISTANCE_EVIDENCE.csv", evidence_rows)

    physical_metrics = {(r["system"], r["pair"]): r for r in scale_rows if r["domain"] == "physical_plot_interval"}
    provenance_rows = []
    for row in diagnostics:
        m = physical_metrics[("Li2FeO3", row["pair"])]
        provenance_rows.append({
            "pair": row["pair"],
            "request_source": "30 retrieved non-target Crystal-DB CIFs; periodic pair distances; per-pair Laplace-smoothed histogram potential; min-shifted; corpus lambda-scaled",
            "request_observations": row["local_observation_count"],
            "request_supporting_structures": row["local_structure_count"],
            "request_weight": row["local_weight"],
            "request_pot_path": row["request_pot_path"],
            "request_pot_sha256": row["request_pot_sha256"],
            "request_lambda": 0.0026530452898991244,
            "global_source": "legacy broad ICSD radial-distribution prior; shell-corrected AV; Gaussian-smoothed RDF; reverse/short-range POT construction",
            "global_weight": row["global_weight"],
            "global_pot_path": row["regulator_pot_path"],
            "global_pot_sha256": row["regulator_pot_sha256"],
            "final_source": row["final_source"],
            "weighted_global_to_request_RMS_1p75_6A": m["global_to_request_ratio"],
            "scale_classification": "C",
        })
    write_csv(BUNDLE / "SPP_PAIR_PROVENANCE.csv", provenance_rows)

    request_payload = {
        "benchmark_id": "layered-repaired-041",
        "formula": "Li2FeO3",
        "text_request": retrieval["config"]["text"],
        "candidate_retrieval_depth": 50,
        "selected_non_target_corpus_size": 30,
        "target_exclusion": {
            "structure_id": target["target"]["structure_id"],
            "candidate_key": target["target"]["candidate_key"],
            "excluded_before_generation": True,
        },
    }
    write_json(BUNDLE / "REQUEST.json", request_payload)
    generated_source = RUN / "qlip" / "generated.cif"
    generated_copy = BUNDLE / "GENERATED_RAW.cif"
    shutil.copy2(generated_source, generated_copy)
    if sha256(generated_source) != sha256(generated_copy):
        raise RuntimeError("Generated CIF copy is not byte-identical")
    solver = {
        "experiment_id": "layered-repaired-041",
        "formula": "Li2FeO3",
        "terminal_status": summary["qlip_status"],
        "solver_objective": summary["qlip_objective"],
        "runtime_seconds": summary["qlip_runtime"],
        "objective_type": "spp_energy",
        "request_weight": REQUEST_WEIGHT,
        "global_weight": GLOBAL_WEIGHT,
        "outer_objective_weight": OUTER_WEIGHT,
        "native_grid_density": 4,
        "native_grid_site_count": 64,
        "generated_cif_source": str(generated_source.resolve()),
        "generated_cif_sha256": sha256(generated_source),
        "compiled_component_terms_persisted": False,
        "compiled_component_audit": "reconstructed offline from persisted cell/grid/POT inputs; QLIP not rerun",
    }
    write_json(BUNDLE / "QLIP_SOLVER_SUMMARY.json", solver)
    volume = 6 * 17.986899303180298
    cell = {
        "cell_mode": "composition_scaled",
        "a_A": CELL_EDGE, "b_A": CELL_EDGE, "c_A": CELL_EDGE,
        "alpha_deg": 90.0, "beta_deg": 90.0, "gamma_deg": 90.0,
        "volume_A3": volume,
        "formula_atom_count": 6,
        "vpa_source": "global_vpa_frozen_constant",
        "vpa_A3_per_atom": 17.986899303180298,
        "vpa_corpus_id": "mp_stable_10k_v1",
        "vpa_corpus_included_count": 10000,
        "retrieval_controls_cell_dimensions": False,
        "physical_search_cell": True,
        "discretisation": "4x4x4",
        "candidate_positions": 64,
    }
    if not math.isclose(CELL_EDGE ** 3, volume, rel_tol=0, abs_tol=1e-9):
        raise RuntimeError("Persisted Li2FeO3 cell does not match composition_scaled contract")
    write_json(BUNDLE / "CELL_STRATEGY_SUMMARY.json", cell)
    write_json(BUNDLE / "SCA_SUMMARY.json", sca)
    write_csv(BUNDLE / "SPP_REGULATOR_EFFECTIVE_SCALE.csv", scale_rows)
    write_csv(BUNDLE / "QLIP_COMPILED_COEFFICIENT_AUDIT.csv", coefficients)

    for pair, data in curves.items():
        request = data["request"]
        global_raw = data["global"]
        req_norm = request / max(float(np.max(np.abs(request))), 1e-15)
        glob_norm = global_raw / max(float(np.max(np.abs(global_raw))), 1e-15)
        rows = [{
            "distance_A": d,
            "request_component_raw": r,
            "global_component_raw": g,
            "request_component_weighted": REQUEST_WEIGHT * r,
            "global_component_weighted": GLOBAL_WEIGHT * g,
            "final_qlip_spp_before_outer_weight": f,
            "final_objective_curve_after_outer_weight": OUTER_WEIGHT * f,
            "request_shape_normalized_for_display": rn,
            "global_shape_normalized_for_display": gn,
        } for d, r, g, f, rn, gn in zip(data["distance"], request, global_raw, data["final"], req_norm, glob_norm, strict=True)]
        write_csv(CURVES / f"{pair}.csv", rows)

    contract = f"""# SPP regulator scale contract

## Exact production operation

For a request-supported pair, the request histogram uses 0.05 A bins from 0.5 to 11.0 A.  If `n_k` is the pair count in bin `k`, SPP-Maker computes

`p_k = (n_k + 0.001) / (sum_j n_j + 0.001 * 210)`

`phi_k = -log(p_k)` and then `phi_k <- phi_k - min_j(phi_j)` independently per pair.  The production workflow calibrates the entire request corpus by scoring the 30 retrieved CIFs, selecting `lambda = 1 / median(structure score) = 0.0026530452898991244`, and stores `U_request,k = lambda * phi_k`.  No z-score, min-max scaling, clipping, capping, r^2 weighting, or kernel smoothing is applied to this request construction.

QLIP loads both stored POTs with cubic interpolation and zero fill outside each tabulated grid.  For each candidate-site pair `(i,j)`, it sums every periodic image with `0 < r <= 11 A`, including translated self-images and excluding the central zero-distance self-image:

`C_ij(pair) = sum_images [U_request(r_image) + 2 U_global(r_image)]`.

The `objective.energy_spp` plugin then multiplies the complete allocation objective by 10.  Thus each SPP objective coefficient is

`C_objective,ij = 10 * sum_images [U_request(r_image) + 2 U_global(r_image)]`.

The configured `request_coefficient=1.0` is recorded by the workflow but is not separately multiplied in `_qlip_spp_request_adapter`; its effective coefficient is the implicit 1 above.  There is no later component normalization, baseline alignment, capping, or cross-corpus calibration.

## Source locations

- Request distance extraction and histogram fit: `{SPP_MAKER / 'src/spp_maker_qlip/required_pair_extraction.py'}`.
- Laplace probability and minimum shift: `{SPP_MAKER / 'src/spp_maker/fit_phi.py'}`.
- Request corpus score calibration and lambda selection: `{SKILL / 'src/sok_llm_orchestrator/workflow/runner.py'}` lines 700-710; `{SPP_MAKER / 'src/spp_maker/calibration.py'}` lines 247-360.
- Literal POT multiplication by lambda: `{SPP_MAKER / 'src/spp_maker/calibration.py'}` lines 363-443.
- Request/global weights and QLIP adapter: `{SKILL / 'src/sok_llm_orchestrator/workflow/runner.py'}` lines 261-318 and 430-441.
- Cubic interpolation and periodic sum: `{QLIP / 'src/qlip/interactions/spp.py'}` lines 62-140.
- Request-plus-regulator matrix: `{QLIP / 'src/qlip/interactions/spp.py'}` lines 411-443.
- Objective-level factor 10: `{QLIP / 'src/qlip/plugins/registry.py'}` lines 175-217.
- Unordered solver term convention: `{QLIP / 'src/qlip/allocation.py'}` lines 267-301.

## Numerical-scale conclusion

The request and global POTs are **not guaranteed to share a statistical transformation, histogram construction, smoothing, bin grid, baseline convention, or amplitude convention**.  The request is a per-pair discrete probability potential with Laplace smoothing, per-pair minimum shifting, and a request-corpus median-score lambda.  The legacy regulator artifacts document an ICSD AV shell correction (`AV/r^2 * 1.59154943`), a Gaussian-smoothed RDF, and a reverse/short-range POT construction.  Their grids are also different (request: 210 centers, 0.525-10.975 A; regulator: 222 points, 0-11 A with a special first interval).  Both are dimensionless stored objective values, but a numeric value of 2.0 is not proven to have the same pre-weight objective meaning across the two corpora.

**Classification C: they are combined without sufficient cross-corpus scale calibration.**  The frozen v4 method is unchanged.  The figure therefore plots the actual final curve on its own amplitude axis and shows request/global components only as separately shape-normalized traces, with the raw weighted RMS ratio disclosed.
"""
    (BUNDLE / "SPP_REGULATOR_SCALE_CONTRACT.md").write_text(contract, encoding="utf-8")

    caption = [
        "# Figure 1 caption facts", "",
        "- Case: layered-repaired-041, Li2FeO3.",
        f"- Request: {request_payload['text_request']}",
        "- Retrieval: 50 candidates requested; held-out target removed; 30 non-target Crystal-DB structures entered SPP-Maker.",
        "- Six displayed neighbours are the first six retained non-target entries; same-formula entries are distinct database polymorphs.",
        "- Periodic distance evidence supports all six Li-Fe-O required pairs.",
        "- Request/global POT amplitudes are not cross-corpus calibrated (classification C). Component inset traces are independently shape-normalized for display; the main trace is the unmodified QLIP objective SPP before the common outer factor 10.",
        f"- Cell: composition_scaled, a=b=c={CELL_EDGE:.12f} A, angles 90 deg, V={volume:.12f} A3; frozen target-independent VPA=17.986899303180298 A3/atom.",
        "- The 4x4x4 object is a discretisation of the physical cell, giving 64 candidate positions; it is not the unit-cell size.",
        f"- QLIP: {summary['qlip_status']}, objective {summary['qlip_objective']:.12f}, runtime {summary['qlip_runtime']:.12f} s.",
        f"- Generated raw CIF SHA-256: `{sha256(generated_copy)}`.",
        f"- SCA: topology {sca['topology_status']}; valid CIF/composition; {sca['num_bad_contacts']} bad contacts; minimum distance {sca['min_distance']:.12f} A ({sca['min_distance_pair']}).", "",
    ]
    (BUNDLE / "CAPTION_FACTS.md").write_text("\n".join(caption), encoding="utf-8")
    return neighbour_rows


def wait_for_file(path: Path, timeout: float, image: bool = False) -> None:
    deadline = time.monotonic() + timeout
    old = -1
    stable = 0
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            size = path.stat().st_size
            stable = stable + 1 if size == old else 0
            old = size
            if stable >= 2:
                if image:
                    try:
                        with Image.open(path) as opened:
                            opened.verify()
                    except Exception:
                        pass
                    else:
                        return
                else:
                    return
        time.sleep(0.25)
    raise TimeoutError(path)


def vesta_launch(args: list[str]) -> int:
    process = subprocess.Popen(
        [str(VESTA_EXE), *args], cwd=str(VESTA_EXE.parent),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return int(process.pid)


def polish(raw: Path, output: Path) -> None:
    with Image.open(raw) as opened:
        rgba = opened.convert("RGBA")
    data = np.asarray(rgba).copy()
    h, w = data.shape[:2]
    data[np.all(data[:, :, :3] >= 247, axis=2), 3] = 0
    data[int(h * 0.62):, :int(w * 0.27), 3] = 0
    image = Image.fromarray(data, "RGBA")
    bbox = image.getbbox()
    if bbox is None:
        raise RuntimeError(f"Blank VESTA export: {raw}")
    image = image.crop(bbox)
    scale = min(1100 / image.width, 780 / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (1200, 850), (255, 255, 255, 0))
    canvas.alpha_composite(image, ((1200 - image.width) // 2, (850 - image.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(300, 300))


def render_vesta(source: Path, render_id: str, role: str, formula: str) -> dict[str, Any]:
    staged = VESTA_ASSETS / "staged_cifs" / f"{render_id}.cif"
    scene = VESTA_ASSETS / "scenes" / f"{render_id}.vesta"
    raw = VESTA_ASSETS / "raw_exports" / f"{render_id}.png"
    output = VESTA_ASSETS / "polished" / f"{render_id}.png"
    for parent in (staged.parent, scene.parent, raw.parent, output.parent):
        parent.mkdir(parents=True, exist_ok=True)
    source_hash = sha256(source)
    shutil.copy2(source, staged)
    if sha256(staged) != source_hash:
        raise RuntimeError("VESTA staged CIF hash mismatch")
    for path in (scene, raw, output):
        if path.exists():
            path.unlink()
    save_pid = vesta_launch(["-open", str(staged.resolve()).replace("\\", "/"), "-rotate_x", "18", "-rotate_y", "-28", "-rotate_z", "8", "-save", str(scene.resolve()).replace("\\", "/"), "-close", str(staged.resolve()).replace("\\", "/")])
    wait_for_file(scene, 60)
    export_pid = vesta_launch(["-open", str(scene.resolve()).replace("\\", "/"), "-export_img", "scale=3", str(raw.resolve()).replace("\\", "/"), "-close", str(scene.resolve()).replace("\\", "/")])
    wait_for_file(raw, 90, image=True)
    polish(raw, output)
    if sha256(source) != source_hash:
        raise RuntimeError("Source CIF changed during VESTA render")
    return {
        "render_id": render_id, "role": role, "formula": formula, "renderer": "VESTA",
        "source_cif": str(source.resolve()), "source_cif_sha256": source_hash,
        "staged_cif": str(staged.resolve()), "staged_cif_sha256": sha256(staged),
        "scene": str(scene.resolve()), "scene_sha256": sha256(scene),
        "raw_export": str(raw.resolve()), "raw_export_sha256": sha256(raw),
        "polished_render": str(output.resolve()), "polished_render_sha256": sha256(output),
        "rotation_degrees": {"x": 18, "y": -28, "z": 8},
        "vesta_save_pid": save_pid, "vesta_export_pid": export_pid,
    }


def card(ax, color: str = CARD) -> None:
    ax.set_axis_off()
    ax.add_patch(FancyBboxPatch((0, 0), 1, 1, transform=ax.transAxes, boxstyle="round,pad=.012,rounding_size=.02", facecolor=color, edgecolor=GRID, linewidth=.8, clip_on=False, zorder=-10))


def heading(ax, letter: str, title: str) -> None:
    ax.text(0.01, 1.025, letter, transform=ax.transAxes, color=BLUE, fontsize=11, fontweight="bold", va="bottom")
    ax.text(0.12, 1.025, title, transform=ax.transAxes, color=INK, fontsize=9.5, fontweight="bold", va="bottom")


def image_axis(ax, path: Path) -> None:
    with Image.open(path) as opened:
        ax.imshow(opened.convert("RGBA"))
    ax.set_axis_off()


def draw_grid(ax) -> None:
    pts = np.asarray(list(np.ndindex(4, 4, 4)), dtype=float) - 1.5
    a, e = math.radians(35), math.radians(22)
    rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(e), -math.sin(e)], [0, math.sin(e), math.cos(e)]])
    p = pts @ (rx @ rz).T
    order = np.argsort(p[:, 2])
    ax.scatter(p[order, 0], p[order, 1], s=6, c=np.linspace(.25, .9, 64)[order], cmap="Blues", edgecolors="none")
    ax.set_axis_off(); ax.set_aspect("equal")


def render_figure(neighbours: list[dict[str, Any]], curves: dict[str, dict[str, Any]], scale_rows: list[dict[str, Any]], renders: list[dict[str, Any]]) -> None:
    FIGURE.mkdir(parents=True, exist_ok=True)
    scale = {(r["system"], r["pair"]): r for r in scale_rows if r["domain"] == "physical_plot_interval"}
    fig = plt.figure(figsize=(25.5, 7.6), facecolor="white")
    gs = fig.add_gridspec(1, 7, width_ratios=(1.3, 3.45, 1.85, 5.0, 2.2, 2.35, 1.85), left=.012, right=.992, bottom=.08, top=.83, wspace=.22)
    fig.suptitle("Retrieved crystal evidence becomes numerical guidance for crystal optimisation", y=.965, fontsize=18, fontweight="bold", color=INK)
    fig.text(.5, .905, "Li$_2$FeO$_3$ · persisted v4 case layered-repaired-041", ha="center", fontsize=9.5, color=MUTED)

    a = fig.add_subplot(gs[0, 0]); card(a, "#F3F8FB"); heading(a, "A", "Request")
    a.text(.5, .73, "Li$_2$FeO$_3$", ha="center", fontsize=20, fontweight="bold", color=NAVY, transform=a.transAxes)
    a.text(.5, .61, "layered oxide", ha="center", fontsize=9, fontweight="bold", color=TEAL, transform=a.transAxes)
    a.text(.5, .38, "Generate a plausible\nlayered battery oxide\ncrystal structure", ha="center", va="center", fontsize=8, linespacing=1.5, color=INK, transform=a.transAxes)

    b = fig.add_subplot(gs[0, 1]); card(b); heading(b, "B", "30 retrieved Crystal-DB structures")
    sub = gs[0, 1].subgridspec(2, 3, hspace=.08, wspace=.04)
    for idx, (row, render) in enumerate(zip(neighbours, renders[:6], strict=True)):
        ax = fig.add_subplot(sub[idx // 3, idx % 3]); ax.set_axis_off()
        ia = ax.inset_axes([.03, .20, .94, .70]); image_axis(ia, Path(render["polished_render"]))
        label = row["display_label"].replace("Li2FeO3", "Li$_2$FeO$_3$").replace("LiFeO2", "LiFeO$_2$").replace("LiFe3O4", "LiFe$_3$O$_4$").replace("Li4WFe3O8", "Li$_4$WFe$_3$O$_8$")
        ax.text(.5, .95, label, ha="center", va="top", fontsize=7.2, fontweight="bold", color=INK, transform=ax.transAxes)
        ax.text(.5, .12, f"rank {row['retrieval_rank']} · {float(row['similarity_score']):.3f}", ha="center", fontsize=5.6, color=BLUE, transform=ax.transAxes)
        ax.text(.5, .055, row["structure_id"].replace("materials_project-", "MP "), ha="center", fontsize=5.0, color=MUTED, transform=ax.transAxes)
    b.text(.5, .015, "+24 additional retrieved structures entered SPP-Maker", ha="center", fontsize=6.4, fontweight="bold", color=TEAL, transform=b.transAxes)

    c = fig.add_subplot(gs[0, 2]); card(c, "#F7FBFA"); heading(c, "C", "Pair-distance evidence")
    c.text(.5, .92, "30 periodic CIFs", ha="center", fontsize=8.3, fontweight="bold", color=NAVY, transform=c.transAxes)
    c.text(.5, .865, "↓  r ≤ 11 Å", ha="center", fontsize=7, color=MUTED, transform=c.transAxes)
    evidence = {r["pair"]: r for r in load_csv(BUNDLE / "PAIR_DISTANCE_EVIDENCE.csv")}
    c.text(.08, .79, "pair", fontsize=6.1, color=MUTED, transform=c.transAxes)
    c.text(.53, .79, "structures", fontsize=6.1, color=MUTED, transform=c.transAxes)
    c.text(.93, .79, "distances", ha="right", fontsize=6.1, color=MUTED, transform=c.transAxes)
    for index, pair in enumerate(DISPLAY_PAIRS):
        row = evidence[pair]
        y = .72 - index * .095
        c.text(.08, y, pair.replace("Fe-Li", "Li-Fe"), fontsize=7.3, fontweight="bold", color=INK, transform=c.transAxes)
        c.text(.66, y, row["supporting_structure_count"], ha="center", fontsize=7.1, color=TEAL, transform=c.transAxes)
        c.text(.93, y, f"{int(row['periodic_distance_observation_count']):,}", ha="right", fontsize=7.1, color=INK, transform=c.transAxes)
        c.plot([.07, .94], [y-.035, y-.035], color=GRID, lw=.45, transform=c.transAxes)
    c.text(.5, .09, "six request-conditioned SPPs", ha="center", fontsize=7, fontweight="bold", color=TEAL, transform=c.transAxes)

    d = fig.add_subplot(gs[0, 3]); card(d, "#FCFBF7"); heading(d, "D", "Six pair SPPs used by QLIP")
    d.text(.99, 1.025, "actual final curve + independently shape-normalized components", ha="right", va="bottom", fontsize=5.8, color=MUTED, transform=d.transAxes)
    positions = [(0.04, .54), (.36, .54), (.68, .54), (.04, .08), (.36, .08), (.68, .08)]
    for pair, (x0, y0) in zip(DISPLAY_PAIRS, positions, strict=True):
        ax = d.inset_axes([x0, y0, .27, .36])
        data = curves[pair]; dist = data["distance"]; mask = (dist >= 1.75) & (dist <= 6)
        final = data["final"]
        ax.plot(dist[mask], final[mask], color=NAVY, lw=1.25)
        ax.axhline(0, color="#AAB5BB", lw=.4); ax.grid(True, color=GRID, lw=.35)
        ax.tick_params(labelsize=4.7, length=1.6, pad=1, colors=MUTED)
        for spine in ax.spines.values(): spine.set_color("#BAC5CA"); spine.set_linewidth(.45)
        ax.set_xlim(1.75, 6); ax.set_title(pair.replace("Fe-Li", "Li-Fe"), fontsize=7.2, fontweight="bold", pad=2, color=INK)
        inset = ax.inset_axes([.48, .54, .48, .40])
        req = data["request"][mask]; glob = data["global"][mask]
        inset.plot(dist[mask], req / max(np.max(np.abs(req)), 1e-15), color=TEAL, lw=.65)
        inset.plot(dist[mask], glob / max(np.max(np.abs(glob)), 1e-15), color=GOLD, lw=.65)
        inset.set_xlim(1.75, 6); inset.set_ylim(-1.1, 1.1); inset.set_xticks([]); inset.set_yticks([])
        for spine in inset.spines.values(): spine.set_color("#CAD2D6"); spine.set_linewidth(.35)
        ratio = scale[("Li2FeO3", pair)]["global_to_request_ratio"]
        ax.text(.02, .03, f"2G/R RMS {ratio:.0f}×", fontsize=4.8, color=MUTED, transform=ax.transAxes)
    d.text(.04, .025, "QLIP objective SPP (raw stored values; before common ×10 objective weight)", fontsize=5.8, color=NAVY, transform=d.transAxes)
    d.text(.61, .025, "shape-only inset: teal = retrieved-neighbour · gold = global prior", fontsize=5.5, color=MUTED, transform=d.transAxes)

    e = fig.add_subplot(gs[0, 4]); card(e, "#F6F7FB"); heading(e, "E", "QLIP CSP")
    e.text(.5, .87, "Physical search cell", ha="center", fontsize=8.2, fontweight="bold", color=NAVY, transform=e.transAxes)
    e.text(.5, .79, "composition-scaled frozen VPA", ha="center", fontsize=6.3, color=MUTED, transform=e.transAxes)
    e.text(.5, .72, "a = b = c = 4.761 Å", ha="center", fontsize=7.3, color=INK, transform=e.transAxes)
    e.text(.5, .655, "↓ discretisation", ha="center", fontsize=6.2, color=MUTED, transform=e.transAxes)
    ga = e.inset_axes([.24, .42, .52, .22]); draw_grid(ga)
    e.text(.5, .39, "4×4×4 = 64 positions", ha="center", fontsize=8.2, fontweight="bold", color=NAVY, transform=e.transAxes)
    e.text(.5, .29, "SPP objective", ha="center", fontsize=6.7, color=INK, transform=e.transAxes)
    e.text(.5, .245, "exact composition", ha="center", fontsize=6.7, color=INK, transform=e.transAxes)
    e.text(.5, .20, "atomic-radii proximity", ha="center", fontsize=6.7, color=INK, transform=e.transAxes)
    e.text(.5, .105, "OPTIMAL", ha="center", fontsize=10, fontweight="bold", color=GREEN, transform=e.transAxes)
    e.text(.5, .055, "objective 969.0273 · 246.917 s", ha="center", fontsize=5.9, color=MUTED, transform=e.transAxes)

    f = fig.add_subplot(gs[0, 5]); card(f); heading(f, "F", "Actual generated crystal")
    ia = f.inset_axes([.04, .18, .92, .70]); image_axis(ia, Path(renders[6]["polished_render"]))
    f.text(.5, .11, "QLIP-generated Li$_2$FeO$_3$", ha="center", fontsize=8.6, fontweight="bold", color=INK, transform=f.transAxes)
    f.text(.5, .055, "raw persisted CIF · VESTA", ha="center", fontsize=6.2, color=MUTED, transform=f.transAxes)

    g = fig.add_subplot(gs[0, 6]); card(g, "#F4FAF6"); heading(g, "G", "SCA validation")
    g.text(.5, .76, "TOPOLOGY PASS", ha="center", fontsize=10.5, fontweight="bold", color=GREEN, transform=g.transAxes)
    for idx, (label, value) in enumerate((("CIF / composition", "valid"), ("Bad contacts", "0"), ("Min. distance", "2.062 Å"))):
        y = .57 - idx * .15
        g.text(.08, y, label, fontsize=6.6, color=MUTED, transform=g.transAxes)
        g.text(.92, y, value, ha="right", fontsize=7.4, fontweight="bold", color=INK, transform=g.transAxes)
        if idx < 2: g.plot([.08, .92], [y-.05, y-.05], color=GRID, lw=.5, transform=g.transAxes)

    axes = [a, b, c, d, e, f, g]
    for left, right in zip(axes, axes[1:]):
        lb, rb = left.get_position(), right.get_position()
        fig.add_artist(FancyArrowPatch((lb.x1+.001, .46), (rb.x0-.001, .46), transform=fig.transFigure, arrowstyle="-|>", mutation_scale=10, lw=1, color="#819099", clip_on=False))
    pdf = FIGURE / "FIGURE_1_LI2FEO3_WORKFLOW.pdf"
    png = FIGURE / "FIGURE_1_LI2FEO3_WORKFLOW.png"
    fig.savefig(pdf, metadata={"Title": "Li2FeO3 retrieval-to-optimisation workflow"})
    fig.savefig(png, dpi=300, facecolor="white")
    plt.close(fig)


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    required = [RUN / "target_manifest.json", RUN / "run_summary.json", RUN / "qlip" / "generated.cif", RUN / "sca" / "result.json", REQUEST_ROOT, REGULATOR, VESTA_EXE]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(missing)
    frozen_files = [path for path in RUN.rglob("*") if path.is_file()]
    frozen_hashes = {path: sha256(path) for path in frozen_files}
    scale_rows, curves = build_scale_audit()
    coefficients = build_coefficient_audit(curves)
    neighbours = bundle_inputs(scale_rows, curves, coefficients)
    specs = [(Path(row["source_cif_path"]), f"retrieved_{i:02d}", "retrieved_neighbour", row["formula"]) for i, row in enumerate(neighbours, 1)]
    specs.append((BUNDLE / "GENERATED_RAW.cif", "generated_li2feo3", "raw_generated", "Li2FeO3"))
    renders = [render_vesta(*spec) for spec in specs]
    write_json(FIGURE / "VESTA_RENDER_MANIFEST.json", {
        "renderer": "VESTA", "vesta_executable": str(VESTA_EXE.resolve()), "vesta_executable_sha256": sha256(VESTA_EXE),
        "render_count": len(renders), "renders": renders,
        "retrieval_rerun": False, "spp_fit_rerun": False, "qlip_rerun": False, "generation_rerun": False, "sca_rerun": False,
    })
    render_figure(neighbours, curves, scale_rows, renders)
    changed = [str(path) for path, digest in frozen_hashes.items() if sha256(path) != digest]
    if changed:
        raise RuntimeError(f"Frozen source artifacts changed: {changed}")
    png = FIGURE / "FIGURE_1_LI2FEO3_WORKFLOW.png"
    with Image.open(png) as image:
        image.verify()
        dpi = image.info.get("dpi", (0, 0))
    if min(float(value) for value in dpi) < 299:
        raise RuntimeError(f"PNG below 300 dpi: {dpi}")
    print(json.dumps({"bundle": str(BUNDLE), "figure": str(FIGURE), "vesta_renders": len(renders), "png_dpi": dpi}, indent=2))


if __name__ == "__main__":
    main()
