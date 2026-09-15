from __future__ import annotations

from dataclasses import dataclass

from sok_llm_orchestrator.retrieval.result_schema import RetrievalBundle


@dataclass(slots=True)
class CellCandidate:
    candidate_id: str
    lattice: dict[str, float]
    source: str


def default_cell_candidates() -> list[CellCandidate]:
    return [
        CellCandidate(
            candidate_id="default_tetragonal",
            lattice={"a": 4.6, "b": 4.6, "c": 3.0, "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
            source="baseline_default",
        )
    ]


def select_cell_candidates(
    policy: str,
    retrieval: RetrievalBundle | None = None,
    fixed_candidates: list[CellCandidate] | None = None,
) -> list[CellCandidate]:
    if policy == "fixed_benchmark" and fixed_candidates:
        return list(fixed_candidates)
    candidates = default_cell_candidates()
    if policy == "retrieval_informed" and retrieval is not None:
        for item in retrieval.items[:2]:
            if not item.get("cell_hint"):
                continue
            candidates.append(
                CellCandidate(
                    candidate_id=f"retrieval_{item['structure_id']}",
                    lattice=item["cell_hint"],
                    source="retrieval",
                )
            )
    # Dedupe candidates by exact lattice tuple.
    seen: set[tuple[float, float, float, float, float, float]] = set()
    deduped: list[CellCandidate] = []
    for candidate in candidates:
        key = tuple(float(candidate.lattice[k]) for k in ("a", "b", "c", "alpha", "beta", "gamma"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped
