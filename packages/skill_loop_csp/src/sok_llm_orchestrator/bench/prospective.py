"""Leakage-safe plumbing for prospective benchmark preflight and execution.

This module deliberately wraps, rather than modifies, the frozen production
workflow.  Reference coordinates are used only for post-retrieval exclusion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Structure

from sok_llm_orchestrator.workflow.runner import ProductionWorkflowStages
from sok_llm_orchestrator.workflow.spp import REQUEST_INSUFFICIENT, REQUEST_MISSING, REQUEST_USABLE


@dataclass(frozen=True, slots=True)
class FrozenReference:
    case_id: str
    formula: str
    reference_id: str
    source_structure_id: str
    cif_path: Path
    raw_sha256: str
    canonical_sha256: str

    @classmethod
    def from_cif(
        cls,
        *,
        case_id: str,
        formula: str,
        reference_id: str,
        source_structure_id: str,
        cif_path: Path,
    ) -> "FrozenReference":
        path = Path(cif_path).resolve()
        return cls(
            case_id=case_id,
            formula=formula,
            reference_id=reference_id,
            source_structure_id=source_structure_id,
            cif_path=path,
            raw_sha256=sha256_file(path),
            canonical_sha256=canonical_structure_sha256(Structure.from_file(path)),
        )


@dataclass(frozen=True, slots=True)
class ExclusionAuditRow:
    structure_id: str
    retrieval_rank: int
    retrieval_source: str
    exclusion_checked: bool
    reference_id_match: bool
    raw_hash_match: bool
    canonical_hash_match: bool
    structurematcher_equivalent: bool
    included_in_request_spp: bool
    exclusion_reason: str


@dataclass(frozen=True, slots=True)
class ExclusionResult:
    retrieval: dict[str, Any]
    audit: tuple[ExclusionAuditRow, ...]
    reference_equivalent_evidence_count: int

    def audit_dicts(self) -> list[dict[str, Any]]:
        return [asdict(row) for row in self.audit]


@dataclass(frozen=True, slots=True)
class PairGuidanceAuditRow:
    species_pair: str
    local_request_status: str
    regulator_available: bool
    regulator_quality: str
    regulator_pot_path: str | None
    guidance_available: bool
    preflight_pair_mode: str


@dataclass(frozen=True, slots=True)
class Option1Coverage:
    rows: tuple[PairGuidanceAuditRow, ...]
    required_pair_count: int
    locally_supported_pair_count: int
    regulator_fallback_pair_count: int
    unsupported_pair_count: int
    local_support_fraction: float


def _regulator_pair_path(root: Path, pair: str) -> Path | None:
    left, right = pair.split("-", 1)
    for name in (f"{left.upper()}-{right.upper()}", f"{right.upper()}-{left.upper()}"):
        for candidate in (root / name / f"{name}.POT", root / f"{name}.POT"):
            if candidate.is_file():
                return candidate.resolve()
    return None


def audit_option1_pair_coverage(
    *,
    required_pairs: Iterable[str],
    local_pair_statuses: Mapping[str, str],
    regulator_root: Path,
) -> Option1Coverage:
    """Audit local-or-regulator guidance without fitting or changing any POT."""
    from spp_maker_qlip.pot_quality import audit_pot_file

    rows: list[PairGuidanceAuditRow] = []
    for pair in dict.fromkeys(str(value) for value in required_pairs):
        request_status = str(local_pair_statuses.get(pair, REQUEST_MISSING))
        if request_status not in {REQUEST_USABLE, REQUEST_INSUFFICIENT, REQUEST_MISSING}:
            raise ValueError(f"invalid local request status for {pair}: {request_status}")
        pot_path = _regulator_pair_path(Path(regulator_root), pair)
        quality = audit_pot_file(pot_path, max_cap_fraction_threshold=0.5) if pot_path else None
        quality_name = str(quality.get("pot_quality", "missing")) if quality else "missing"
        regulator_available = bool(pot_path and quality_name == "usable")
        if not regulator_available:
            mode = "UNSUPPORTED_REQUIRED_PAIR"
        elif request_status == REQUEST_USABLE:
            mode = "LOCAL_SUPPORT_AVAILABLE"
        elif request_status == REQUEST_INSUFFICIENT:
            mode = "LOCAL_SUPPORT_INSUFFICIENT_REGULATOR_AVAILABLE"
        else:
            mode = "LOCAL_SUPPORT_MISSING_REGULATOR_AVAILABLE"
        rows.append(PairGuidanceAuditRow(
            species_pair=pair,
            local_request_status=request_status,
            regulator_available=regulator_available,
            regulator_quality=quality_name,
            regulator_pot_path=str(pot_path) if pot_path else None,
            guidance_available=request_status == REQUEST_USABLE or regulator_available,
            preflight_pair_mode=mode,
        ))
    local = sum(row.local_request_status == REQUEST_USABLE for row in rows)
    fallback = sum(row.preflight_pair_mode.startswith("LOCAL_SUPPORT_") and row.preflight_pair_mode != "LOCAL_SUPPORT_AVAILABLE" for row in rows)
    unsupported = sum(row.preflight_pair_mode == "UNSUPPORTED_REQUIRED_PAIR" for row in rows)
    return Option1Coverage(
        rows=tuple(rows),
        required_pair_count=len(rows),
        locally_supported_pair_count=local,
        regulator_fallback_pair_count=fallback,
        unsupported_pair_count=unsupported,
        local_support_fraction=(local / len(rows)) if rows else 0.0,
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_structure_sha256(structure: Structure) -> str:
    """Hash the same deterministic lattice/site payload used by the V1 freeze."""
    payload = {
        "lattice": [round(float(value), 10) for row in structure.lattice.matrix for value in row],
        "sites": sorted(
            (str(site.specie), *[round(float(value) % 1.0, 10) for value in site.frac_coords])
            for site in structure
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate_cif_path(item: Mapping[str, Any]) -> Path | None:
    export = item.get("cif_export") if isinstance(item.get("cif_export"), Mapping) else {}
    value = export.get("path") or item.get("internal_spp_cif_path") or item.get("cif_path")
    path = Path(str(value)).resolve() if value else None
    return path if path is not None and path.is_file() else None


def _reason(*, id_match: bool, raw_match: bool, canonical_match: bool, matcher_match: bool) -> str:
    reasons = []
    if id_match:
        reasons.append("reference_id_match")
    if raw_match:
        reasons.append("raw_hash_match")
    if canonical_match:
        reasons.append("canonical_hash_match")
    if matcher_match:
        reasons.append("structurematcher_equivalent")
    return ";".join(reasons) if reasons else "eligible_non_equivalent"


def exclude_reference_equivalents(
    retrieval: Mapping[str, Any],
    reference: FrozenReference,
    *,
    matcher: StructureMatcher | None = None,
) -> ExclusionResult:
    """Filter a frozen reference from primary and pair-expansion candidates.

    Candidate order, ranks and retrieval scores are never changed.  Every
    candidate in both paths receives an audit row.
    """
    reference_structure = Structure.from_file(reference.cif_path)
    structure_matcher = matcher or StructureMatcher()
    reference_ids = {reference.reference_id, reference.source_structure_id}
    audit: list[ExclusionAuditRow] = []

    def filter_items(items: Iterable[Mapping[str, Any]], source: str) -> list[dict[str, Any]]:
        kept: list[dict[str, Any]] = []
        for fallback_rank, original in enumerate(items, start=1):
            item = dict(original)
            structure_id = str(item.get("structure_id", ""))
            rank = int(item.get("rank", fallback_rank))
            path = _candidate_cif_path(item)
            id_match = structure_id in reference_ids
            raw_match = False
            canonical_match = False
            matcher_match = False
            if path is not None:
                raw_match = sha256_file(path) == reference.raw_sha256
                candidate = Structure.from_file(path)
                canonical_match = canonical_structure_sha256(candidate) == reference.canonical_sha256
                matcher_match = bool(structure_matcher.fit(reference_structure, candidate))
            excluded = id_match or raw_match or canonical_match or matcher_match
            included = not excluded and path is not None
            audit.append(
                ExclusionAuditRow(
                    structure_id=structure_id,
                    retrieval_rank=rank,
                    retrieval_source=source,
                    exclusion_checked=True,
                    reference_id_match=id_match,
                    raw_hash_match=raw_match,
                    canonical_hash_match=canonical_match,
                    structurematcher_equivalent=matcher_match,
                    included_in_request_spp=included,
                    exclusion_reason=_reason(
                        id_match=id_match,
                        raw_match=raw_match,
                        canonical_match=canonical_match,
                        matcher_match=matcher_match,
                    ),
                )
            )
            if not excluded:
                kept.append(item)
        return kept

    filtered = dict(retrieval)
    filtered["selected"] = filter_items(retrieval.get("selected", ()), "primary")
    expansion = retrieval.get("pair_coverage_expansion")
    if isinstance(expansion, Mapping):
        filtered_expansion = dict(expansion)
        filtered_expansion["selected"] = filter_items(expansion.get("selected", ()), "pair_coverage_expansion")
        filtered["pair_coverage_expansion"] = filtered_expansion
    filtered["reference_exclusion"] = {
        "case_id": reference.case_id,
        "reference_id": reference.reference_id,
        "source_structure_id": reference.source_structure_id,
        "raw_sha256": reference.raw_sha256,
        "canonical_sha256": reference.canonical_sha256,
        "audit": [asdict(row) for row in audit],
        "reference_equivalent_evidence_count": 0,
    }
    return ExclusionResult(filtered, tuple(audit), 0)


def assert_reference_safe_for_spp(evidence: Any, exclusion: ExclusionResult) -> None:
    excluded_ids = {
        row.structure_id
        for row in exclusion.audit
        if row.reference_id_match or row.raw_hash_match or row.canonical_hash_match or row.structurematcher_equivalent
    }
    evidence_ids = {str(item.structure_id) for item in evidence.selected}
    leaked = sorted(evidence_ids & excluded_ids)
    if leaked or exclusion.reference_equivalent_evidence_count != 0:
        raise RuntimeError(f"reference-equivalent evidence reached request-SPP fitting: {leaked}")


class ProspectiveBenchmarkStages(ProductionWorkflowStages):
    """Benchmark-only adapter around the frozen production stage implementation."""

    def __init__(self, *, tasks: Mapping[str, Mapping[str, Any]], reference: FrozenReference) -> None:
        self._benchmark_tasks = {str(key): dict(value) for key, value in tasks.items()}
        self.reference = reference
        self.last_exclusion: ExclusionResult | None = None

    def normalise(self, request: str) -> dict[str, Any]:
        compact = str(request).replace(" ", "").lower()
        for formula, task in self._benchmark_tasks.items():
            if formula.lower() in compact:
                return dict(task)
        return super().normalise(request)

    def retrieve(self, request: str, task: dict[str, Any], config: Any, run_root: Path) -> dict[str, Any]:
        retrieval = super().retrieve(request, task, config, run_root)
        self.last_exclusion = exclude_reference_equivalents(retrieval, self.reference)
        return self.last_exclusion.retrieval

    def fit_request_spp(self, evidence: Any, task: dict[str, Any], config: Any, run_root: Path) -> dict[str, Any]:
        if self.last_exclusion is None:
            raise RuntimeError("reference exclusion audit missing before request-SPP fitting")
        assert_reference_safe_for_spp(evidence, self.last_exclusion)
        return super().fit_request_spp(evidence, task, config, run_root)


__all__ = [
    "ExclusionAuditRow",
    "ExclusionResult",
    "FrozenReference",
    "Option1Coverage",
    "PairGuidanceAuditRow",
    "ProspectiveBenchmarkStages",
    "assert_reference_safe_for_spp",
    "audit_option1_pair_coverage",
    "canonical_structure_sha256",
    "exclude_reference_equivalents",
    "sha256_file",
]
