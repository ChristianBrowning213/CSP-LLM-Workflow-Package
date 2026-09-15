"""Benchmark adapter for the existing CrystaLLM-style pre-DFT pipeline."""

from __future__ import annotations

from sca.schemas import BenchmarkEvaluatorResult, CrystalEvalRecord


class PreDftValidityBenchmarkEvaluator:
    name = "pre_dft_validity"
    description = "CrystaLLM-style pre-DFT validity checks."

    def from_record(self, record: CrystalEvalRecord) -> BenchmarkEvaluatorResult:
        flags = {
            "parse_ok": record.parse_ok,
            "target_formula_match": record.target_formula_match,
            "space_group_consistent": record.space_group_consistent,
            "multiplicity_consistent": record.multiplicity_consistent,
            "bond_lengths_reasonable": record.bond_lengths_reasonable,
            "geometry_ok": record.geometry_ok,
            "pre_dft_valid": record.pre_dft_valid,
            "is_duplicate": record.is_duplicate,
            "is_unique_representative": record.is_unique_representative,
            "novelty_checked": record.novelty_checked,
            "known_match": record.known_match,
            "novel_by_structure_matcher": record.novel_by_structure_matcher,
        }
        metrics = {
            "bond_reasonableness_score": record.bond_reasonableness_score,
            "min_distance": record.min_distance,
            "num_bad_contacts": record.num_bad_contacts,
            "volume": record.volume,
            "volume_per_atom": record.volume_per_atom,
            "density": record.density,
            "geometry_warning_count": record.geometry_warning_count,
            "pre_dft_rank_score": record.pre_dft_rank_score,
            "formation_energy_per_atom": record.formation_energy_per_atom,
        }
        details = {
            key: value
            for key, value in record.model_dump().items()
            if key not in {"run_id", "method", "query_id", "input_path", "file_name"}
        }
        return BenchmarkEvaluatorResult(
            name=self.name,
            ok=record.pre_dft_valid,
            summary="valid" if record.pre_dft_valid else "invalid",
            metrics=metrics,
            flags=flags,
            details=details,
            error_type=record.error_type,
            error_message=record.error_message,
        )

