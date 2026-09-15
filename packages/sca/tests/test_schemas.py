from sca.schemas import (
    BenchmarkEvaluatorResult,
    BenchmarkRecord,
    CifMetadata,
    CrystalEvaluationResult,
    EvaluatorResult,
)


def test_result_schema_serialization() -> None:
    cif = CifMetadata(
        input_path="sample.cif",
        file_name="sample.cif",
        parse_ok=True,
        formula="Na1 Cl1",
        reduced_formula="NaCl",
        n_sites=2,
        volume=179.4,
        density=2.16,
    )
    alignn = EvaluatorResult(
        ok=True,
        model="mock-alignn",
        values={"formation_energy_per_atom": -1.23},
    )

    result = CrystalEvaluationResult.from_parts(cif, alignn)
    payload = result.model_dump()

    assert payload["input_path"] == "sample.cif"
    assert payload["alignn_ok"] is True
    assert payload["formation_energy_per_atom"] == -1.23
    assert "formation_energy_per_atom" in result.model_dump_json()


def test_benchmark_record_flattens_evaluator_status() -> None:
    record = BenchmarkRecord(
        run_id="run",
        input_path="sample.cif",
        file_name="sample.cif",
        evaluator_outputs={
            "pre_dft_validity": BenchmarkEvaluatorResult(
                name="pre_dft_validity",
                ok=True,
                flags={"pre_dft_valid": True},
                metrics={"pre_dft_rank_score": 0.0},
            )
        },
        flattened={"parse_ok": True, "pre_dft_valid": True},
    )

    row = record.to_row()

    assert row["parse_ok"] is True
    assert row["pre_dft_valid"] is True
    assert row["evaluator_pre_dft_validity_ok"] is True
