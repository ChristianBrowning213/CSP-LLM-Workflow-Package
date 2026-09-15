from pathlib import Path

from sca.batch import evaluate_many, evaluate_one
from sca.evaluators.alignn import AlignnEvaluator


FIXTURES = Path(__file__).parent / "fixtures"


def test_alignn_evaluator_with_mock_predictor() -> None:
    evaluator = AlignnEvaluator(model_name="mock-alignn", predictor=lambda structure, path: -2.5)

    result = evaluate_one(FIXTURES / "tiny_valid.cif", evaluator)

    assert result.parse_ok is True
    assert result.alignn_ok is True
    assert result.alignn_model == "mock-alignn"
    assert result.formation_energy_per_atom == -2.5
    assert result.error_type is None


def test_alignn_failure_is_structured() -> None:
    def failing_predictor(structure, path):
        raise RuntimeError("model unavailable")

    evaluator = AlignnEvaluator(model_name="mock-alignn", predictor=failing_predictor)

    result = evaluate_one(FIXTURES / "tiny_valid.cif", evaluator)

    assert result.parse_ok is True
    assert result.alignn_ok is False
    assert result.error_type == "RuntimeError"
    assert result.error_message == "model unavailable"


def test_batch_returns_partial_results_for_failed_parse() -> None:
    evaluator = AlignnEvaluator(model_name="mock-alignn", predictor=lambda structure, path: -2.5)

    results = evaluate_many(
        [FIXTURES / "tiny_valid.cif", FIXTURES / "malformed.cif"],
        evaluator,
        show_progress=False,
    )

    assert [result.parse_ok for result in results] == [True, False]
    assert [result.alignn_ok for result in results] == [True, False]
