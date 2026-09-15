"""Load and inspect traceable CSP run bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from sca.traceability.schema import BundleInspectionResult, TraceableRunBundle


ARTIFACT_FILES: dict[str, str] = {
    "prompt": "prompt.txt",
    "structured_intent": "structured_intent.json",
    "retrieval_trace": "retrieval_trace.json",
    "constraint_trace": "constraint_trace.json",
    "spp_trace": "spp_trace.json",
    "solver_trace": "solver_trace.json",
    "generated_candidates": "generated_candidates.json",
    "validation_trace": "validation_trace.json",
    "relaxation_trace": "relaxation_trace.json",
    "diagnostics_trace": "diagnostics_trace.json",
    "final_decision": "final_decision.json",
    "environment": "environment.json",
    "generator_config": "generator_config.json",
    "retrieval_config": "retrieval_config.json",
    "solver_config": "solver_config.json",
}

REQUIRED_ARTIFACTS = (
    "prompt",
    "structured_intent",
    "retrieval_trace",
    "constraint_trace",
    "solver_trace",
    "generated_candidates",
    "validation_trace",
    "diagnostics_trace",
    "final_decision",
)

REPRODUCIBILITY_ARTIFACTS = (
    "environment",
    "generator_config",
    "retrieval_config",
    "solver_config",
)


def load_run_bundle(run_dir: str | Path, manifest_row: dict[str, Any] | None = None) -> TraceableRunBundle:
    """Load a run bundle from standard artifact names."""

    inspection = inspect_run_bundle(run_dir, manifest_row=manifest_row, include_bundle=True)
    if inspection.bundle is None:
        errors = "; ".join(inspection.parse_errors or inspection.missing_artifacts)
        raise ValueError(f"Could not load run bundle: {errors}")
    return inspection.bundle


def inspect_run_bundle(
    run_dir: str | Path,
    manifest_row: dict[str, Any] | None = None,
    include_bundle: bool = True,
) -> BundleInspectionResult:
    root = Path(run_dir)
    manifest_row = manifest_row or {}
    presence = {name: (root / filename).exists() for name, filename in ARTIFACT_FILES.items()}
    missing = [name for name in REQUIRED_ARTIFACTS if not presence[name]]
    parse_errors: list[str] = []
    crosslink_errors: list[str] = []
    loaded: dict[str, Any] = {}

    prompt_text = _read_text(root / ARTIFACT_FILES["prompt"], parse_errors)
    for name, filename in ARTIFACT_FILES.items():
        if name == "prompt":
            continue
        path = root / filename
        if path.exists():
            loaded[name] = _read_json(path, parse_errors)

    candidates = loaded.get("generated_candidates") or {}
    for candidate in candidates.get("candidates", []) if isinstance(candidates, dict) else []:
        cif_path = candidate.get("cif_path")
        if cif_path and not _resolve(root, cif_path).exists():
            crosslink_errors.append(f"generated candidate CIF not found: {cif_path}")

    run_id = str(manifest_row.get("run_id") or root.name)
    prompt_id = _optional_str(manifest_row.get("prompt_id")) or _optional_str(loaded.get("structured_intent", {}).get("prompt_id"))
    files = {
        name: str(root / filename)
        for name, filename in ARTIFACT_FILES.items()
        if (root / filename).exists()
    }
    checksums = {name: _sha256(Path(path)) for name, path in files.items()}
    bundle = None
    if include_bundle:
        try:
            bundle = TraceableRunBundle(
                run_id=run_id,
                prompt_id=prompt_id,
                input_text=prompt_text or str(manifest_row.get("input_text") or ""),
                timestamp=_optional_str(manifest_row.get("timestamp")),
                run_dir=str(root),
                manifest_row=manifest_row,
                files=files,
                checksums=checksums,
                structured_intent=loaded.get("structured_intent"),
                retrieval_trace=loaded.get("retrieval_trace"),
                constraint_trace=loaded.get("constraint_trace"),
                spp_trace=loaded.get("spp_trace"),
                solver_trace=loaded.get("solver_trace"),
                generated_candidates=loaded.get("generated_candidates"),
                validation_trace=loaded.get("validation_trace"),
                relaxation_trace=loaded.get("relaxation_trace"),
                diagnostics_trace=loaded.get("diagnostics_trace"),
                final_decision=loaded.get("final_decision"),
            )
        except ValidationError as exc:
            parse_errors.append(str(exc))

    missing_repro = [name for name in REPRODUCIBILITY_ARTIFACTS if not presence[name]]
    missing_repro.extend(name for name in ("prompt", "generated_candidates") if not presence[name])
    bundle_valid = not missing and not parse_errors and not crosslink_errors
    return BundleInspectionResult(
        run_id=run_id,
        prompt_id=prompt_id,
        run_dir=str(root),
        bundle_valid=bundle_valid,
        missing_artifacts=missing,
        parse_errors=parse_errors,
        crosslink_errors=crosslink_errors,
        artifact_presence=presence,
        reproducibility_metadata_present=not missing_repro,
        missing_reproducibility_fields=missing_repro,
        bundle=bundle,
    )


def _read_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return {}
    if isinstance(value, dict):
        return value
    errors.append(f"{path.name}: expected JSON object")
    return {}


def _read_text(path: Path, errors: list[str]) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _optional_str(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value)
