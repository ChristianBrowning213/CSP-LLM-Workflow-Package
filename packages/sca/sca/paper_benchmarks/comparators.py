"""Built-in contextual comparator values for paper-comparable benchmark summaries."""

from __future__ import annotations

from sca.paper_benchmarks.schema import PaperComparator


BUILT_IN_COMPARATORS = [
    PaperComparator(
        "pre_dft_validity_rate",
        "crystal_text_llm_physical_constraints",
        0.90,
        "higher_is_better",
        notes="around 90% physically constrained samples; contextual comparator",
    ),
    PaperComparator("match_rate", "DiffCSP_MP20", 0.5149, "higher_is_better"),
    PaperComparator("match_rate", "FlowMM_MP20", 0.6139, "higher_is_better"),
    PaperComparator("match_rate", "CrystalFlow_MP20", 0.6202, "higher_is_better"),
    PaperComparator("match_rate", "Lang2Str_MP20", 0.6392, "higher_is_better"),
    PaperComparator("match_rate", "Uni3DAR_MP20", 0.6548, "higher_is_better"),
    PaperComparator("structure_rmse", "Lang2Str_MP20", 0.076, "lower_is_better"),
    PaperComparator("structure_rmse_relaxed", "Lang2Str_MP20_relaxed", 0.055, "lower_is_better"),
    PaperComparator("match_rate", "Lang2Str_MPTS52", 0.2836, "higher_is_better"),
    PaperComparator("match_rate", "Uni3DAR_MPTS52", 0.3244, "higher_is_better"),
    PaperComparator(
        "predicted_metastable_rate_ehull_0_15",
        "CDVAE_crystal_text_llm_comparator",
        0.28,
        "higher_is_better",
    ),
    PaperComparator(
        "predicted_metastable_rate_ehull_0_15",
        "finetuned_LLaMA2_70B_crystal_text_llm",
        0.49,
        "higher_is_better",
    ),
    PaperComparator(
        "metastability_threshold",
        "Chemeleon_ZnTiO_metastable_threshold",
        0.15,
        "lower_is_better",
        unit="eV/atom",
    ),
    PaperComparator(
        "rmse_improvement_after_relaxation",
        "Lang2Str_MP20_relaxation_improvement",
        0.021,
        "higher_is_better",
        notes="0.076 -> 0.055",
    ),
    PaperComparator("relaxed_rmse", "Lang2Str_MP20_relaxed", 0.055, "lower_is_better"),
    PaperComparator("unique_rate", "internal_first_target", 0.90, "higher_is_better"),
    PaperComparator("sun_rate", "internal_first_target", 0.28, "higher_is_better"),
    PaperComparator("sun_rate", "internal_strong_target", 0.40, "higher_is_better"),
]


def built_in_comparators() -> list[PaperComparator]:
    return list(BUILT_IN_COMPARATORS)
