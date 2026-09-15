"""Lazy adapters for the supported Structured Crystal Analyser contract."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from typing import Any, Callable

from .models import BackendProvenance, TopologyValidationResult, ValidationError, ValidationResult


SUPPORTED_TOPOLOGY_POLICIES = frozenset(
    {
        "ARGYRODITE_ORDERED",
        "FLUORITE",
        "GENERIC_SCAFFOLD_ONLY",
        "HALIDE_PEROVSKITE_3D",
        "LAYERED_OXIDE",
        "NASICON_ORDERED",
        "OLIVINE",
        "PEROVSKITE_3D",
        "ROCKSALT",
        "SPINEL",
    }
)


def _load_general_backend() -> Callable[..., Any]:
    from sca.pipelines import evaluate_one_cif

    return evaluate_one_cif


def _load_topology_backend() -> Callable[..., Any]:
    from sca.evaluators.topology import family_topology_metrics

    return family_topology_metrics


def _backend_provenance() -> BackendProvenance:
    try:
        import sca

        version = getattr(sca, "__version__", None)
    except ImportError:
        try:
            version = metadata.version("sca")
        except metadata.PackageNotFoundError:
            version = None
    return BackendProvenance(version=version)


def _unavailable(exc: BaseException) -> tuple[ValidationError, ...]:
    return (ValidationError("backend_unavailable", f"{type(exc).__name__}: {exc}"),)


def _record_dict(record: Any) -> dict[str, Any]:
    if hasattr(record, "model_dump"):
        return dict(record.model_dump(mode="python"))
    if isinstance(record, dict):
        return dict(record)
    raise TypeError(f"Unsupported SCA record type: {type(record).__name__}")


def validate_cif(
    cif_path: str | Path,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> ValidationResult:
    """Evaluate one CIF through SCA without repairing it or writing artifacts."""

    provenance = _backend_provenance()
    try:
        evaluate_one_cif = _load_general_backend()
    except (ImportError, ModuleNotFoundError) as exc:
        return ValidationResult(
            status="backend_unavailable",
            parseable=False,
            valid=None,
            errors=_unavailable(exc),
            backend=provenance,
        )

    try:
        record, _structure = evaluate_one_cif(
            cif_path,
            target_formula=target_formula,
            target_space_group=target_space_group,
            method=method,
            query_id=query_id,
            require_spacegroup=require_spacegroup,
            run_alignn=run_alignn,
            reference_structures=reference_structures,
            run_id=run_id,
        )
        raw = _record_dict(record)
    except Exception as exc:
        return ValidationResult(
            status="evaluation_failure",
            parseable=False,
            valid=None,
            errors=(ValidationError("evaluation_failure", f"{type(exc).__name__}: {exc}"),),
            backend=provenance,
        )

    parseable = bool(raw.get("parse_ok"))
    error_type = raw.get("error_type")
    error_message = raw.get("error_message")
    errors = (
        (ValidationError(str(error_type or "evaluation_error"), str(error_message)),)
        if error_message
        else ()
    )
    warnings: list[str] = []
    warning_count = int(raw.get("geometry_warning_count") or 0)
    if warning_count:
        warnings.append(f"SCA reported {warning_count} geometry warning(s)")

    composition_keys = (
        "chemical_species_valid",
        "species",
        "invalid_species",
        "formula",
        "reduced_formula",
        "target_formula",
        "target_formula_match",
    )
    metric_keys = (
        "declared_space_group",
        "detected_space_group",
        "target_space_group",
        "space_group_consistent",
        "multiplicity_checked",
        "multiplicity_consistent",
        "bond_reasonableness_score",
        "bond_lengths_reasonable",
        "min_distance",
        "min_distance_pair",
        "num_bad_contacts",
        "volume",
        "volume_per_atom",
        "density",
        "density_error",
        "geometry_ok",
        "geometry_warning_count",
        "novelty_checked",
        "nearest_reference_id",
        "known_match",
        "novel_by_structure_matcher",
        "novelty_error",
        "alignn_ok",
        "alignn_model",
        "formation_energy_per_atom",
        "pre_dft_rank_score",
    )
    return ValidationResult(
        status="evaluated" if parseable else "parse_failure",
        parseable=parseable,
        valid=bool(raw.get("pre_dft_valid")) if parseable else False,
        composition={key: raw.get(key) for key in composition_keys},
        general_metrics={key: raw.get(key) for key in metric_keys},
        warnings=tuple(warnings),
        errors=errors,
        backend=provenance,
        details={"sca_record": raw},
    )


def validate_family_topology(structure: Any, family: str) -> TopologyValidationResult:
    """Evaluate a Pymatgen Structure using one SCA topology policy."""

    policy = str(family).upper()
    provenance = _backend_provenance()
    if policy not in SUPPORTED_TOPOLOGY_POLICIES:
        return TopologyValidationResult(
            status="unsupported_policy",
            family=policy,
            available=False,
            topology_status=None,
            matches=None,
            errors=(ValidationError("unsupported_policy", f"Unsupported topology policy '{policy}'"),),
            backend=provenance,
        )
    try:
        family_topology_metrics = _load_topology_backend()
    except (ImportError, ModuleNotFoundError) as exc:
        return TopologyValidationResult(
            status="backend_unavailable",
            family=policy,
            available=False,
            topology_status=None,
            matches=None,
            errors=_unavailable(exc),
            backend=provenance,
        )
    try:
        metrics, details = family_topology_metrics(structure, policy)
        metrics = dict(metrics)
        details = dict(details)
    except Exception as exc:
        return TopologyValidationResult(
            status="evaluation_failure",
            family=policy,
            available=True,
            topology_status=None,
            matches=None,
            errors=(ValidationError("evaluation_failure", f"{type(exc).__name__}: {exc}"),),
            backend=provenance,
        )

    topology_status = metrics.get("topology_status")
    matches = True if topology_status == "PASS" else None if topology_status == "NOT_APPLICABLE" else False
    return TopologyValidationResult(
        status="evaluated",
        family=policy,
        available=True,
        topology_status=topology_status,
        matches=matches,
        metrics=metrics,
        warnings=tuple(str(item) for item in metrics.get("topology_warnings", [])),
        backend=provenance,
        details=details,
    )
