from __future__ import annotations

import os

import pytest

from sok_llm_orchestrator.evals.live_llm import default_eval_cases, run_live_llm_eval
from sok_llm_orchestrator.llm.client import LLMClient


pytestmark = pytest.mark.live_llm


def _require_live_env() -> None:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to run live LLM tests.")
    for key in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        if not os.environ.get(key):
            pytest.skip(f"Missing {key} for live LLM tests.")


def test_local_llm_strict_contract_pass_rate() -> None:
    _require_live_env()
    timeout_s = int(os.environ.get("LIVE_LLM_TIMEOUT_S", "90"))
    max_retries = int(os.environ.get("LIVE_LLM_MAX_RETRIES", "1"))
    min_pass_rate = float(os.environ.get("LIVE_LLM_MIN_PASS_RATE", "0.66"))
    trials = int(os.environ.get("LIVE_LLM_TRIALS", "2"))
    client = LLMClient(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ["LLM_MODEL"],
        timeout_s=timeout_s,
        max_retries=max_retries,
    )
    report = run_live_llm_eval(client=client, cases=default_eval_cases(), trials_per_case=trials, out_path=None)
    assert report["pass_rate"] >= min_pass_rate
