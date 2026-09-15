"""Post-DFT structural validation using the same explicit SCA evidence tiers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sca.evaluators.relaxation_intent_retention import RelaxationIntentRetentionEvaluator
from sca.schemas import BenchmarkEvaluatorResult


class PostDftIntentRetentionEvaluator:
    name = "post_dft_intent_retention"
    description = "Generated-to-DFT-relaxed structural and intent retention."

    def evaluate_item(self, item: dict[str, Any]) -> BenchmarkEvaluatorResult:
        metrics = validate_post_dft_structure(
            item.get("initial_cif_path") or item.get("generated_cif") or item.get("path"),
            item.get("dft_relaxed_cif") or item.get("relaxed_cif_path"),
            converged=_as_bool(item.get("dft_converged") or item.get("converged")),
            target_family=item.get("target_family") or item.get("target_structure_family"),
            target_space_group=item.get("target_space_group"),
            require_space_group=_as_bool(item.get("require_space_group")),
        )
        status = metrics["dft_relaxation_status"]
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=status in {"DFT_ROBUST", "DFT_VALID_SYMMETRY_LOWERED"},
            skipped=status in {"DFT_NOT_RUN"},
            summary=status,
            metrics=metrics,
        )


def validate_post_dft_structure(
    generated_cif: str | Path,
    dft_relaxed_cif: str | Path | None,
    *,
    converged: bool,
    target_family: str | None = None,
    target_space_group: str | None = None,
    require_space_group: bool = False,
) -> dict[str, Any]:
    if dft_relaxed_cif is None:
        return {"dft_relaxation_status": "DFT_NOT_RUN"}
    if not converged:
        return {"dft_relaxation_status": "DFT_NOT_CONVERGED"}
    result = RelaxationIntentRetentionEvaluator().evaluate_item(
        {
            "initial_cif_path": str(generated_cif),
            "relaxed_cif_path": str(dft_relaxed_cif),
            "target_family": target_family,
            "target_space_group": target_space_group,
            "require_space_group": require_space_group,
        }
    )
    overall = result.metrics.get("overall_relaxation_status")
    if overall == "COLLAPSED":
        status = "DFT_TOPOLOGY_CHANGED" if result.metrics.get("family_retained") is False else "DFT_COLLAPSED"
    elif result.metrics.get("space_group_retained") is False:
        status = "DFT_VALID_SYMMETRY_LOWERED"
    else:
        status = "DFT_ROBUST"
    return {"dft_relaxation_status": status, **result.metrics}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}
