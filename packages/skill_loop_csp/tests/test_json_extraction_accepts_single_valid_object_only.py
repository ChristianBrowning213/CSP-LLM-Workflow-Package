from __future__ import annotations

from sok_llm_orchestrator.optimization.controller_json import extract_single_json_object


def test_json_extraction_accepts_single_valid_object_only() -> None:
    ok = extract_single_json_object("prefix {\"a\":1,\"b\":\"x\"} suffix", max_chars=2000)
    assert ok.ok is True
    assert ok.payload == {"a": 1, "b": "x"}

    repeated = extract_single_json_object("{\"a\":1}{\"a\":2}", max_chars=2000)
    assert repeated.ok is False
    assert repeated.reason == "repeated_json_payload"

    fenced = extract_single_json_object("```json\n{\"a\":1}\n```", max_chars=2000)
    assert fenced.ok is False
    assert fenced.reason == "contains_code_fence"
