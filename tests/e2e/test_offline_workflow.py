"""Public no-external-assets end-to-end installation smoke."""

from __future__ import annotations

import json

from llm_csp.cli.main import main


def test_public_offline_smoke_needs_no_scientific_assets(tmp_path, capsys) -> None:
    output = tmp_path / "public-smoke"

    assert main(["demo", "--output", str(output), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "installation_smoke_passed"
    assert payload["scientific_prediction"] is False
    assert payload["checks"]["configuration"] is True
    assert payload["checks"]["retrieval_fixture"] is True
    assert payload["checks"]["qlip_request_constructed"] is True
    assert payload["checks"]["validation_adapter_status"] in {
        "backend_unavailable", "evaluated", "parse_failure", "evaluation_failure"
    }
