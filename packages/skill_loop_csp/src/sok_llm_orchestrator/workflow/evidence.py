"""Deterministic, target-blind retrieval-to-SPP evidence assembly."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from pymatgen.core import Composition, Structure


def canonical_pair(left: str, right: str) -> str:
    return "-".join(sorted((left, right), key=str.lower))


def required_pairs_for_formula(formula: str) -> list[str]:
    """Return QLIP's unordered element-pair domain with self pairs included."""
    elements = sorted(
        (str(element) for element in Composition(str(formula)).elements),
        key=str.lower,
    )
    return [
        canonical_pair(left, right)
        for left, right in itertools.combinations_with_replacement(elements, 2)
    ]


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    structure_id: str
    retrieval_rank: int
    retrieval_score: float
    cif_path: str
    cif_sha256: str
    inclusion_reason: str
    species_pairs_contributed: tuple[str, ...]
    source_id: str | None = None
    family: str | None = None


@dataclass(frozen=True, slots=True)
class SPPEvidenceBundle:
    corpus_id: str
    corpus_hash: str
    selection_policy: str
    required_pairs: tuple[str, ...]
    pair_structure_counts: dict[str, int]
    pair_evidence_status: dict[str, dict[str, Any]]
    selected: tuple[EvidenceItem, ...]
    exclusion_audit: tuple[dict[str, Any], ...]
    bundle_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pairs_in_cif(path: Path) -> set[str]:
    structure = Structure.from_file(path)
    elements = sorted({site.specie.symbol for site in structure}, key=str.lower)
    return {canonical_pair(left, right) for left in elements for right in elements}


def assemble_spp_evidence(
    *,
    retrieval: dict[str, Any],
    required_pairs: Iterable[str],
    excluded_structure_ids: Iterable[str] = (),
    minimum_structures_per_pair: int = 1,
    max_ranked_structures: int = 40,
    allow_partial_pair_coverage: bool = False,
) -> SPPEvidenceBundle:
    if minimum_structures_per_pair < 1:
        raise ValueError("minimum_structures_per_pair must be at least one")
    if max_ranked_structures < 1:
        raise ValueError("max_ranked_structures must be at least one")
    required = tuple(dict.fromkeys(str(pair) for pair in required_pairs))
    excluded = {str(item) for item in excluded_structure_ids}
    counts = {pair: 0 for pair in required}
    selected: list[EvidenceItem] = []
    exclusion_audit: list[dict[str, Any]] = []
    def consider(item: dict[str, Any], *, reason: str, require_new_pair: bool = False) -> bool:
        structure_id = str(item.get("structure_id", ""))
        if structure_id in excluded:
            exclusion_audit.append({"structure_id": structure_id, "decision": "excluded", "reason": "structure_holdout_id"})
            return False
        export = item.get("cif_export") if isinstance(item.get("cif_export"), dict) else {}
        raw_path = export.get("path") or item.get("internal_spp_cif_path")
        path = Path(str(raw_path)) if raw_path else None
        if path is None or not path.is_file():
            exclusion_audit.append({"structure_id": structure_id, "decision": "excluded", "reason": "no_exportable_cif"})
            return False
        contributed = sorted(_pairs_in_cif(path) & set(required), key=str.lower)
        uncovered = [pair for pair in contributed if counts[pair] < int(minimum_structures_per_pair)]
        if require_new_pair and not uncovered:
            exclusion_audit.append({"structure_id": structure_id, "decision": "not_selected", "reason": "required_pair_coverage_already_satisfied"})
            return False
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        selected.append(
            EvidenceItem(
                structure_id=structure_id,
                retrieval_rank=int(item.get("rank", len(selected) + 1)),
                retrieval_score=float(item.get("score", item.get("retrieval_score", 0.0))),
                cif_path=str(path.resolve()),
                cif_sha256=digest,
                inclusion_reason=reason,
                species_pairs_contributed=tuple(contributed),
                source_id=str(
                    item.get("source_id")
                    or (item.get("provenance") or {}).get("source_id")
                    or ""
                ) or None,
                family=str(item.get("family") or "") or None,
            )
        )
        for pair in contributed:
            counts[pair] += 1
        return True

    ranked = sorted(
        retrieval.get("selected", []),
        key=lambda item: (int(item.get("rank", 10**9)), str(item.get("structure_id", ""))),
    )
    eligible_selected = 0
    for item in ranked:
        if eligible_selected >= int(max_ranked_structures):
            exclusion_audit.append(
                {
                    "structure_id": str(item.get("structure_id", "")),
                    "decision": "not_selected",
                    "reason": "fixed_ranked_cohort_limit",
                }
            )
            continue
        if consider(item, reason="fixed_ranked_exportable_cohort"):
            eligible_selected += 1

    missing = [pair for pair, count in counts.items() if count < int(minimum_structures_per_pair)]
    expansion = retrieval.get("pair_coverage_expansion")
    if missing and isinstance(expansion, dict):
        corpus = retrieval.get("corpus", {})
        corpus_id = str(corpus.get("corpus_id") or retrieval.get("corpus_id") or "")
        expansion_corpus_id = str(expansion.get("corpus_id") or "")
        if expansion_corpus_id != corpus_id:
            raise ValueError(
                "SPP pair-coverage expansion must use the same corpus: "
                f"primary={corpus_id!r}, expansion={expansion_corpus_id!r}"
            )
        already_selected = {item.structure_id for item in selected}
        expansion_ranked = sorted(
            expansion.get("selected", []),
            key=lambda item: (int(item.get("rank", 10**9)), str(item.get("structure_id", ""))),
        )
        for item in expansion_ranked:
            if str(item.get("structure_id", "")) in already_selected:
                continue
            if consider(item, reason="same_corpus_required_pair_coverage", require_new_pair=True):
                already_selected.add(str(item.get("structure_id", "")))
            if all(value >= int(minimum_structures_per_pair) for value in counts.values()):
                break
    missing = [pair for pair, count in counts.items() if count < int(minimum_structures_per_pair)]
    if missing and not allow_partial_pair_coverage:
        raise ValueError(f"SPP evidence missing required pair coverage: {', '.join(missing)}")
    pair_status = {
        pair: {
            "pair": pair,
            "local_evidence_present": counts[pair] >= int(minimum_structures_per_pair),
            "structures_contributing": counts[pair],
            "observations": None,
            "request_pot_attempted": False,
            "request_pot_quality": "not_attempted",
        }
        for pair in required
    }
    corpus = retrieval.get("corpus", {})
    corpus_hash = str(corpus.get("hash") or corpus.get("database_hash") or "")
    payload = {
        "corpus_id": str(corpus.get("corpus_id") or retrieval.get("corpus_id") or ""),
        "corpus_hash": corpus_hash,
        "max_ranked_structures": int(max_ranked_structures),
        "minimum_structures_per_pair": int(minimum_structures_per_pair),
        "required_pairs": required,
        "counts": counts,
        "pair_evidence_status": pair_status,
        "allow_partial_pair_coverage": bool(allow_partial_pair_coverage),
        "selected": [asdict(item) for item in selected],
        "exclusions": exclusion_audit,
    }
    bundle_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return SPPEvidenceBundle(
        corpus_id=payload["corpus_id"],
        corpus_hash=corpus_hash,
        selection_policy="ranked_exportable_fixed_cohort_then_same_corpus_pair_expansion.partial_local.v3" if allow_partial_pair_coverage else "ranked_exportable_fixed_cohort_then_same_corpus_pair_expansion.v2",
        required_pairs=required,
        pair_structure_counts=counts,
        pair_evidence_status=pair_status,
        selected=tuple(selected),
        exclusion_audit=tuple(exclusion_audit),
        bundle_hash=bundle_hash,
    )
