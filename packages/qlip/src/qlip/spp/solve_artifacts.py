from __future__ import annotations

from pathlib import Path

from qlip.spp.io import export_structure_to_cif


def decomposition_to_list(payload: dict[str, float]) -> list[dict]:
    return [
        {"term": str(term), "value": float(value)}
        for term, value in sorted(payload.items(), key=lambda item: item[0])
    ]


def decomposition_sum(rows: list[dict]) -> float:
    return float(sum(float(row["value"]) for row in rows))


def write_solution_cif(outcome, path, *, mode: str, task_key: str, extra_comment: str | None = None) -> Path:
    comment = f"mode={mode} task_key={task_key}"
    if extra_comment:
        comment = f"{comment} {extra_comment}"
    return export_structure_to_cif(outcome.final_structure, Path(path), header_comment=comment)
