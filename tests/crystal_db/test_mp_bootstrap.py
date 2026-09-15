from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "crystal_db" / "grab_data.py"
SPEC = importlib.util.spec_from_file_location("crystaldb_grab_data", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_default_request_recovers_historical_query_semantics() -> None:
    requests = MODULE.parse_requests(ROOT / "data" / "crystal_db" / "requests" / "default_mp_requests.txt")
    assert len(requests) == 1
    request = requests[0]
    assert request.name == "phase6_mp_stable_10k"
    assert request.fields == ("material_id",)
    assert request.stable_only is True
    assert request.chemsys is None
    assert request.elements == ()
    assert request.limit == 10_000


def test_dry_run_makes_no_subprocess_or_network_call(monkeypatch, capsys) -> None:
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = MODULE.main([
        "--requests", str(ROOT / "data" / "crystal_db" / "requests" / "default_mp_requests.txt"),
        "--dry-run",
    ])
    assert result == 0
    assert '"api_version": "SOURCE_EVIDENCE_MISSING"' in capsys.readouterr().out
