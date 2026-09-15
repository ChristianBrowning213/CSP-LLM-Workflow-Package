from sok_llm_orchestrator.orchestrator.pipeline import stable_run_id


def test_stable_run_id() -> None:
    inputs = {"mode": "stub", "policy_mode": "safe", "query": "TiO2", "with_spp": True}
    assert stable_run_id(inputs) == stable_run_id(inputs)
