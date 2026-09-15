"""High-level DFT prepare/submit/status/collect orchestration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from sca.dft.backends import get_backend
from sca.dft.io import read_mapping, write_json
from sca.dft.schema import DFTCalculationSpec, DFTExecutionRecord
from sca.dft.slurm import SlurmConfig, query_status, render_slurm_script, submit_calculation


def prepare_manifest(
    manifest: str | Path,
    backend_name: str,
    config_path: str | Path,
    out_dir: str | Path,
    *,
    slurm_config_path: str | Path | None = None,
) -> list[Path]:
    frame = pd.read_csv(manifest, keep_default_na=False)
    config = read_mapping(config_path)
    backend = get_backend(backend_name)
    slurm = SlurmConfig.model_validate(read_mapping(slurm_config_path)) if slurm_config_path else None
    prepared = []
    for row in frame.to_dict(orient="records"):
        source = Path(row["cif_path"])
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        expected = str(row.get("cif_sha256", "")).lower()
        if expected and digest != expected:
            raise ValueError(f"Input hash mismatch for {row['candidate_id']}")
        calculation_id = f"{row['candidate_id']}-{str(config['calculation_type']).lower()}-v1"
        spec = DFTCalculationSpec(
            calculation_id=calculation_id,
            candidate_id=row["candidate_id"],
            input_cif_path=str(source),
            input_cif_sha256=digest,
            engine=backend_name,
            calculation_type=config["calculation_type"],
            xc_functional=config["xc_functional"],
            dispersion=config.get("dispersion"),
            pseudopotential_family=config["pseudopotential_family"],
            cutoff_energy=config["cutoff_energy"],
            kpoint_scheme=config["kpoint_scheme"],
            kpoint_spacing=config["kpoint_spacing"],
            spin_polarized=config["spin_polarized"],
            initial_magnetic_moments=config.get("initial_magnetic_moments", {}),
            hubbard_u=config.get("hubbard_u", {}),
            energy_tolerance=config["energy_tolerance"],
            force_tolerance=config.get("force_tolerance"),
            stress_tolerance=config.get("stress_tolerance"),
            max_steps=config["max_steps"],
            charge=config["charge"],
            smearing=config.get("smearing", {}),
            correction_scheme=config.get("correction_scheme"),
            metadata={
                "manifest": str(Path(manifest).resolve()),
                "config": str(Path(config_path).resolve()),
                "formula": row.get("formula"),
                "target_family": row.get("target_family"),
                "target_space_group": row.get("target_space_group"),
            },
        )
        target = backend.prepare(spec, out_dir)
        if slurm:
            script = render_slurm_script(slurm, calculation_id, calculation_id)
            (target / "submit.slurm").write_text(script, encoding="utf-8", newline="\n")
            write_json(target / "slurm_config.json", slurm)
        prepared.append(target)
    return prepared


def submit_prepared(calculations: str | Path) -> list[DFTExecutionRecord]:
    rows = []
    for root in _calculation_dirs(calculations):
        spec = DFTCalculationSpec.model_validate_json((root / "calculation.json").read_text(encoding="utf-8"))
        backend = get_backend(spec.engine)
        problems = backend.validate_inputs(root)
        if problems:
            rows.append(DFTExecutionRecord(calculation_id=spec.calculation_id, calculation_dir=str(root), message="; ".join(problems)))
        elif not (root / "submit.slurm").is_file():
            rows.append(DFTExecutionRecord(calculation_id=spec.calculation_id, calculation_dir=str(root), message="submit.slurm is missing"))
        else:
            rows.append(submit_calculation(root))
    return rows


def status_prepared(calculations: str | Path) -> list[DFTExecutionRecord]:
    rows = []
    for root in _calculation_dirs(calculations):
        execution_path = root / "execution.json"
        if execution_path.is_file():
            record = DFTExecutionRecord.model_validate_json(execution_path.read_text(encoding="utf-8"))
            record = query_status(record)
            write_json(execution_path, record)
        else:
            spec = DFTCalculationSpec.model_validate_json((root / "calculation.json").read_text(encoding="utf-8"))
            record = DFTExecutionRecord(calculation_id=spec.calculation_id, calculation_dir=str(root))
        rows.append(record)
    return rows


def collect_results(calculations: str | Path, out_dir: str | Path) -> list[dict[str, Any]]:
    results = []
    for root in _calculation_dirs(calculations):
        spec = DFTCalculationSpec.model_validate_json((root / "calculation.json").read_text(encoding="utf-8"))
        result = get_backend(spec.engine).parse(root)
        write_json(root / "result.json", result)
        results.append(result.model_dump(mode="json"))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(results).to_csv(out / "DFT_RESULTS.csv", index=False)
    with (out / "DFT_RESULTS.jsonl").open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return results


def _calculation_dirs(path: str | Path) -> list[Path]:
    root = Path(path)
    if (root / "calculation.json").is_file():
        return [root]
    return sorted(item.parent for item in root.glob("*/calculation.json"))

