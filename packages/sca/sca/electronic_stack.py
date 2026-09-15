"""Paper-manifest and MLIP campaign orchestration for the advanced stack."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any

import pandas as pd
from pymatgen.core import Composition, Structure
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sca.backends import verify_optional_backends
from sca.evaluators.bonds import evaluate_bonds
from sca.evaluators.geometry import evaluate_geometry
from sca.evaluators.registry import create_evaluator
from sca.evaluators.relaxation_intent_retention import RelaxationIntentRetentionEvaluator


PAPER_FORMULAS = (
    "MgO", "TiN", "ZrO2", "BaTiO3", "CaTiO3", "SrTiO3", "CsPbBr3", "CsPbCl3",
    "CsSnI3", "ZnFe2O4", "MgAl2O4", "CoFe2O4", "Li6PS5Cl", "LiCoO2", "LiFePO4", "Li2FeO3",
)
STATIC_MODELS = ("chgnet_static", "m3gnet_static", "mace_static", "sevennet_static")


def validate_paper_manifest(path: str | Path) -> dict[str, Any]:
    manifest = Path(path)
    frame = pd.read_csv(manifest, keep_default_na=False)
    required = {
        "candidate_id", "formula", "family", "cif_path", "cif_sha256", "target_formula",
        "target_space_group", "target_family", "intent_source",
    }
    missing_columns = sorted(required - set(frame.columns))
    problems: list[str] = []
    if missing_columns:
        problems.append("missing columns: " + ", ".join(missing_columns))
    if len(frame) != 16:
        problems.append(f"expected 16 rows, found {len(frame)}")
    if set(frame.get("formula", [])) != set(PAPER_FORMULAS):
        problems.append("formula roster differs from the authoritative paper-16 set")
    rows = []
    for record in frame.to_dict(orient="records"):
        cif = Path(record.get("cif_path", ""))
        intent = Path(record.get("intent_source", ""))
        actual = _sha256(cif) if cif.is_file() else None
        row_problems = []
        if not cif.is_file():
            row_problems.append("CIF missing")
        elif actual != str(record.get("cif_sha256", "")).lower():
            row_problems.append("CIF SHA256 mismatch")
        if not intent.is_file():
            row_problems.append("intent source missing")
        if any(token in " ".join(str(value) for value in record.values()).lower() for token in ("nasicon", "nzp")):
            row_problems.append("NASICON/NZP is forbidden")
        rows.append({"candidate_id": record.get("candidate_id"), "cif_exists": cif.is_file(), "intent_exists": intent.is_file(), "actual_sha256": actual, "problems": row_problems})
        problems.extend(f"{record.get('candidate_id')}: {problem}" for problem in row_problems)
    return {"valid": not problems, "row_count": len(frame), "problems": problems, "rows": rows}


def build_raw_baseline(manifest: str | Path, out_dir: str | Path) -> list[dict[str, Any]]:
    validation = validate_paper_manifest(manifest)
    if not validation["valid"]:
        raise ValueError("Invalid paper manifest: " + "; ".join(validation["problems"]))
    frame = pd.read_csv(manifest, keep_default_na=False)
    rows: list[dict[str, Any]] = []
    for item in frame.to_dict(orient="records"):
        path = Path(item["cif_path"])
        structure = Structure.from_file(path)
        symmetry = SpacegroupAnalyzer(structure)
        bonds = evaluate_bonds(structure)
        geometry = evaluate_geometry(structure)
        formula_ok = structure.composition.reduced_composition == Composition(item["target_formula"]).reduced_composition
        detected_sg = symmetry.get_space_group_symbol()
        requested_sg = item["target_space_group"] or None
        sg_ok = requested_sg is None or detected_sg.replace(" ", "") == requested_sg.replace(" ", "")
        intent_status = "PASS" if formula_ok and (sg_ok or not _as_bool(item.get("require_space_group"), True)) else "FAIL"
        rows.append(
            {
                "candidate_id": item["candidate_id"],
                "formula": structure.composition.reduced_formula,
                "site_count": len(structure),
                "space_group": detected_sg,
                "crystal_system": symmetry.get_crystal_system(),
                "volume": float(structure.volume),
                "minimum_distance": bonds.min_distance,
                "bad_contacts": bonds.num_bad_contacts,
                "geometry_valid": geometry.geometry_ok,
                "intent_status": intent_status,
                "target_formula": item["target_formula"],
                "target_space_group": requested_sg,
                "target_family": item["target_family"],
                "cif_path": str(path),
                "cif_sha256": _sha256(path),
                "intent_source": item["intent_source"],
            }
        )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "RAW_BASELINE.csv", index=False)
    _write_json(out / "RAW_BASELINE.json", {"schema_version": "sca.paper16.raw.v1", "rows": rows})
    _write_markdown_table(out / "RAW_BASELINE.md", "Paper-16 immutable raw baseline", rows)
    return rows


def write_backend_readiness(out_dir: str | Path, *, functional: bool = False) -> list[dict[str, Any]]:
    rows = verify_optional_backends(functional=functional)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "MLIP_BACKEND_READINESS.csv", index=False)
    _write_json(out / "MLIP_BACKEND_READINESS.json", {"rows": rows})
    _write_markdown_table(out / "MLIP_BACKEND_READINESS.md", "MLIP backend readiness", rows)
    return rows


def run_static_campaign(manifest: str | Path, out_dir: str | Path) -> list[dict[str, Any]]:
    validation = validate_paper_manifest(manifest)
    if not validation["valid"]:
        raise ValueError("Invalid paper manifest: " + "; ".join(validation["problems"]))
    items = pd.read_csv(manifest, keep_default_na=False).to_dict(orient="records")
    evaluators = {name: create_evaluator(name) for name in STATIC_MODELS}
    rows: list[dict[str, Any]] = []
    support: list[dict[str, Any]] = []
    for item in items:
        for name, evaluator in evaluators.items():
            started = time.perf_counter()
            result = evaluator.evaluate_path(item["cif_path"])
            runtime = time.perf_counter() - started
            prefix = name.removesuffix("_static")
            status = "SUCCESS" if result.ok else "SKIPPED" if result.skipped else "FAILED"
            row = {
                "candidate_id": item["candidate_id"],
                "formula": item["formula"],
                "status": status,
                "model_name": result.model or name,
                "model_version": result.version,
                "device": result.details.get("device") or "unknown",
                "energy_per_atom": result.metrics.get(f"{prefix}_energy_per_atom"),
                "max_force": result.metrics.get(f"{prefix}_forces_max"),
                "mean_force": result.metrics.get(f"{prefix}_forces_mean"),
                "stress_norm": result.metrics.get(f"{prefix}_stress_norm"),
                "runtime_seconds": runtime,
                "error_type": result.error_type,
                "error_message": result.error_message,
                "cif_sha256": item["cif_sha256"],
            }
            rows.append(row)
            support.append({"candidate_id": item["candidate_id"], "model": name, "status": status, "reason": result.error_message or result.summary})
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "MLIP_STATIC_RESULTS.csv", index=False)
    with (out / "MLIP_STATIC_RESULTS.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    pd.DataFrame(support).to_csv(out / "MODEL_SUPPORT_MATRIX.csv", index=False)
    build_ensemble_results(rows, out)
    return rows


def build_ensemble_results(static_rows: list[dict[str, Any]], out_dir: str | Path) -> list[dict[str, Any]]:
    frame = pd.DataFrame(static_rows)
    successes = frame[(frame["status"] == "SUCCESS") & frame["energy_per_atom"].notna()].copy()
    if not successes.empty:
        successes["energy_rank"] = successes.groupby("model_name")["energy_per_atom"].rank(method="average", pct=True)
    rows = []
    for candidate_id in sorted(frame["candidate_id"].unique()):
        available = successes[successes["candidate_id"] == candidate_id]
        ranks = [float(value) for value in available.get("energy_rank", [])]
        variance = statistics.pvariance(ranks) if len(ranks) >= 2 else None
        if len(ranks) < 2:
            label = "INSUFFICIENT_MODELS"
        elif variance is not None and variance > 0.08:
            label = "HIGH_DISAGREEMENT"
        elif variance is not None and variance > 0.02:
            label = "MODERATE_DISAGREEMENT"
        else:
            label = "CONSISTENT"
        rows.append(
            {
                "candidate_id": candidate_id,
                "models_available": ";".join(sorted(available["model_name"].astype(str).tolist())),
                "model_success_count": len(ranks),
                "energy_rank_consensus": statistics.mean(ranks) if ranks else None,
                "energy_rank_variance": variance,
                "force_rank_consensus": None,
                "disagreement_flag": label in {"MODERATE_DISAGREEMENT", "HIGH_DISAGREEMENT"} if len(ranks) >= 2 else None,
                "consensus_label": label,
                "explanation": "Within-model percentile ranks only; raw MLIP energies were not averaged.",
            }
        )
    out = Path(out_dir)
    pd.DataFrame(rows).to_csv(out / "MLIP_ENSEMBLE_RESULTS.csv", index=False)
    pd.DataFrame([row for row in rows if row["disagreement_flag"] is True]).to_csv(out / "MLIP_DISAGREEMENT_CASES.csv", index=False)
    return rows


def run_chgnet_relaxation_campaign(
    manifest: str | Path,
    out_dir: str | Path,
    *,
    max_steps: int = 200,
    fmax: float = 0.1,
    relax_cell: bool = True,
    device: str = "cpu",
) -> list[dict[str, Any]]:
    frame = pd.read_csv(manifest, keep_default_na=False)
    out = Path(out_dir)
    cif_dir = out / "mlip_relaxed" / "chgnet"
    cif_dir.mkdir(parents=True, exist_ok=True)
    config = {"backend": "chgnet", "max_steps": max_steps, "force_threshold_eV_A": fmax, "cell_relaxation": relax_cell, "device": device, "optimizer": "CHGNet StructOptimizer/FIRE", "timeout": None}
    _write_json(out / "CHGNET_RELAXATION_CONFIG.json", config)
    try:
        import chgnet
        from chgnet.model.dynamics import StructOptimizer
        from chgnet.model.model import CHGNet

        model = CHGNet.load()
        relaxer = StructOptimizer(model=model, use_device=device)
        unavailable = None
        version = getattr(chgnet, "__version__", None)
    except Exception as exc:
        model = relaxer = None
        version = None
        unavailable = f"{type(exc).__name__}: {exc}"
    rows: list[dict[str, Any]] = []
    for item in frame.to_dict(orient="records"):
        source = Path(item["cif_path"])
        raw_hash_before = _sha256(source)
        base = {"candidate_id": item["candidate_id"], "backend": "chgnet", "model": "CHGNet pretrained", "model_version": version, "device": device, "max_steps": max_steps, "force_threshold": fmax, "cell_relaxation": relax_cell, "raw_cif_path": str(source), "raw_cif_sha256": raw_hash_before}
        if unavailable:
            rows.append({**base, "status": "SKIPPED_DEPENDENCY", "converged": None, "error_type": "BackendUnavailable", "error_message": unavailable})
            continue
        structure = Structure.from_file(source)
        started = time.perf_counter()
        try:
            before = model.predict_structure(structure)
            result = relaxer.relax(structure, fmax=fmax, steps=max_steps, relax_cell=relax_cell, verbose=False)
            final = result["final_structure"]
            after = model.predict_structure(final)
            trajectory = result.get("trajectory")
            target = cif_dir / f"{item['candidate_id']}.cif"
            CifWriter(final).write_file(target)
            initial_energy = _prediction_energy(before, len(structure))
            final_energy = _prediction_energy(after, len(final))
            initial_force = _prediction_force(before)
            final_force = _prediction_force(after)
            steps = len(getattr(trajectory, "energies", []) or [])
            rows.append(
                {
                    **base,
                    "status": "SUCCESS",
                    "initial_energy_per_atom": initial_energy,
                    "relaxed_energy_per_atom": final_energy,
                    "delta_energy_per_atom": final_energy - initial_energy if initial_energy is not None and final_energy is not None else None,
                    "initial_max_force": initial_force,
                    "final_max_force": final_force,
                    "relax_steps": steps,
                    "converged": final_force is not None and final_force <= fmax,
                    "initial_volume": structure.volume,
                    "relaxed_volume": final.volume,
                    "volume_change_pct": (final.volume - structure.volume) / structure.volume * 100.0,
                    "relaxed_cif_path": str(target),
                    "relaxed_cif_sha256": _sha256(target),
                    "runtime_seconds": time.perf_counter() - started,
                    "error_type": None,
                    "error_message": None,
                }
            )
        except Exception as exc:
            rows.append({**base, "status": "FAILED", "converged": False, "runtime_seconds": time.perf_counter() - started, "error_type": type(exc).__name__, "error_message": str(exc)})
        if _sha256(source) != raw_hash_before:
            raise RuntimeError(f"Raw CIF was modified during relaxation: {source}")
    pd.DataFrame(rows).to_csv(out / "MLIP_RELAXATION_RESULTS.csv", index=False)
    _write_json(out / "MLIP_RELAXATION_RESULTS.json", {"configuration": config, "rows": rows})
    retention = build_relaxation_retention(frame.to_dict(orient="records"), rows, out)
    build_mlip_summary(static_path=out / "MLIP_STATIC_RESULTS.csv", relaxation_rows=rows, retention_rows=retention, out_dir=out)
    return rows


def build_relaxation_retention(manifest_rows: list[dict[str, Any]], relaxation_rows: list[dict[str, Any]], out_dir: str | Path) -> list[dict[str, Any]]:
    relaxation = {row["candidate_id"]: row for row in relaxation_rows}
    evaluator = RelaxationIntentRetentionEvaluator()
    rows = []
    for item in manifest_rows:
        run = relaxation.get(item["candidate_id"], {})
        if run.get("status") != "SUCCESS":
            rows.append({"candidate_id": item["candidate_id"], "overall_relaxation_status": "FAILED_RELAXATION" if run.get("status") == "FAILED" else "NOT_EVALUATED", "error_message": run.get("error_message")})
            continue
        result = evaluator.evaluate_item({**item, "initial_cif_path": item["cif_path"], "relaxed_cif_path": run["relaxed_cif_path"]})
        metrics = dict(result.metrics)
        if run.get("converged") is not True:
            metrics["structural_status_despite_nonconvergence"] = metrics["overall_relaxation_status"]
            metrics["overall_relaxation_status"] = "FAILED_RELAXATION"
        rows.append({"candidate_id": item["candidate_id"], **metrics, "error_message": result.error_message})
    out = Path(out_dir)
    pd.DataFrame(rows).to_csv(out / "RELAXATION_INTENT_RETENTION.csv", index=False)
    _write_json(out / "RELAXATION_INTENT_RETENTION.json", {"rows": rows})
    return rows


def build_mlip_summary(
    *, static_path: str | Path, relaxation_rows: list[dict[str, Any]], retention_rows: list[dict[str, Any]], out_dir: str | Path,
) -> dict[str, Any]:
    static = pd.read_csv(static_path) if Path(static_path).is_file() else pd.DataFrame()
    successful_candidates = int(static.loc[static.get("status") == "SUCCESS", "candidate_id"].nunique()) if not static.empty else 0
    attempted = [row for row in relaxation_rows if row.get("status") != "SKIPPED_DEPENDENCY"]
    successful = [row for row in relaxation_rows if row.get("status") == "SUCCESS"]
    converged = [row for row in successful if row.get("converged") is True]
    evaluated = [row for row in retention_rows if row.get("overall_relaxation_status") not in {"FAILED_RELAXATION", "NOT_EVALUATED"}]
    summary = {
        "paper_candidate_count": 16,
        "static_evaluable": {"numerator": successful_candidates, "denominator": 16},
        "relaxation_attempted": {"numerator": len(attempted), "denominator": 16},
        "relaxation_converged": {"numerator": len(converged), "denominator": len(successful)},
        "composition_retained": _count(evaluated, "composition_retained"),
        "site_count_retained": _count(evaluated, "site_count_retained"),
        "family_retained": _count(evaluated, "family_retained"),
        "space_group_retained": _count(evaluated, "space_group_retained"),
        "geometry_valid_after": _count(evaluated, "geometry_valid_after"),
        "zero_severe_bad_contacts_after": {"numerator": sum(row.get("bad_contacts_after") == 0 for row in evaluated), "denominator": len(evaluated)},
        "median_delta_energy_per_atom": _median(successful, "delta_energy_per_atom"),
        "median_volume_change_pct": _median(successful, "volume_change_pct"),
        "median_atomic_rms_displacement_A": _median(evaluated, "atomic_rms_displacement_A"),
        "limitations": "Missing optional-backend runs are excluded from scientific denominators.",
    }
    out = Path(out_dir)
    pd.DataFrame([_flatten_summary(summary)]).to_csv(out / "PAPER_16_MLIP_RELAXATION_SUMMARY.csv", index=False)
    _write_json(out / "PAPER_16_MLIP_RELAXATION_SUMMARY.json", summary)
    lines = ["# Paper-16 MLIP relaxation summary", "", "MLIP relaxation robustness is not thermodynamic stability.", ""]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    (out / "PAPER_16_MLIP_RELAXATION_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    generate_mlip_figure(relaxation_rows, retention_rows, out / "figures")
    return summary


def generate_mlip_figure(relaxation_rows: list[dict[str, Any]], retention_rows: list[dict[str, Any]], out_dir: str | Path) -> dict[str, Any]:
    usable = [row for row in relaxation_rows if row.get("status") == "SUCCESS" and row.get("delta_energy_per_atom") is not None]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    source = []
    retained = {row["candidate_id"]: row for row in retention_rows}
    for row in usable:
        source.append({"candidate_id": row["candidate_id"], "delta_energy_per_atom": row.get("delta_energy_per_atom"), "volume_change_pct": row.get("volume_change_pct"), "atomic_rms_displacement_A": retained.get(row["candidate_id"], {}).get("atomic_rms_displacement_A"), "relaxation_intent_status": retained.get(row["candidate_id"], {}).get("overall_relaxation_status")})
    pd.DataFrame(source).to_csv(out / "FIGURE_MLIP_RELAXATION_VALIDATION_SOURCE_DATA.csv", index=False)
    if len(source) < 2:
        reason = "At least two real successful relaxation results are required; no synthetic values were plotted."
        (out / "FIGURE_MLIP_RELAXATION_VALIDATION_NOT_AVAILABLE.md").write_text("# Figure not available\n\n" + reason + "\n", encoding="utf-8")
        return {"status": "NOT_AVAILABLE", "reason": reason}
    import matplotlib.pyplot as plt

    labels = [row["candidate_id"] for row in source]
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    axes[0, 0].barh(labels, [row["delta_energy_per_atom"] for row in source])
    axes[0, 0].set_xlabel("Delta surrogate energy (eV/atom)")
    axes[0, 1].barh(labels, [row["volume_change_pct"] for row in source])
    axes[0, 1].set_xlabel("Volume change (%)")
    rms = [float("nan") if row["atomic_rms_displacement_A"] is None else row["atomic_rms_displacement_A"] for row in source]
    axes[1, 0].barh(labels, rms)
    axes[1, 0].set_xlabel("RMS atomic displacement (A)")
    statuses = pd.Series([row["relaxation_intent_status"] for row in source]).value_counts()
    axes[1, 1].bar(statuses.index.astype(str), statuses.values)
    axes[1, 1].set_ylabel("Candidates")
    axes[1, 1].tick_params(axis="x", rotation=25)
    figure.suptitle("Generated structures remain crystallographically coherent under MLIP relaxation")
    png = out / "FIGURE_MLIP_RELAXATION_VALIDATION.png"
    pdf = out / "FIGURE_MLIP_RELAXATION_VALIDATION.pdf"
    figure.savefig(png, dpi=300)
    figure.savefig(pdf)
    plt.close(figure)
    return {"status": "CREATED", "png": str(png), "pdf": str(pdf)}


def _prediction_energy(prediction: Any, sites: int) -> float | None:
    value = prediction.get("e") if isinstance(prediction, dict) else None
    if value is None:
        return None
    scalar = float(value.item() if hasattr(value, "item") else value)
    return scalar if abs(scalar) < 100 else scalar / sites


def _prediction_force(prediction: Any) -> float | None:
    value = prediction.get("f") if isinstance(prediction, dict) else None
    if value is None:
        return None
    rows = value.detach().cpu().numpy() if hasattr(value, "detach") else value
    return max((math.sqrt(sum(float(component) ** 2 for component in row)) for row in rows), default=None)


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    eligible = [row for row in rows if row.get(key) is not None]
    return {"numerator": sum(row.get(key) is True for row in eligible), "denominator": len(eligible)}


def _median(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [float(row[key]) for row in rows if row.get(key) is not None and not pd.isna(row[key])]
    return statistics.median(values) if values else None


def _flatten_summary(value: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, item in value.items():
        if isinstance(item, dict) and {"numerator", "denominator"} <= set(item):
            result[f"{key}_numerator"] = item["numerator"]
            result[f"{key}_denominator"] = item["denominator"]
        else:
            result[key] = item
    return result


def _write_markdown_table(path: Path, title: str, rows: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(rows)
    path.write_text(f"# {title}\n\n" + frame.to_markdown(index=False) + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
