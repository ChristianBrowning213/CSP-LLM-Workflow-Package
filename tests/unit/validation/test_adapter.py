from __future__ import annotations

import json
import subprocess
import sys

import llm_csp.validation.adapter as adapter
from llm_csp.validation import SUPPORTED_TOPOLOGY_POLICIES, validate_cif, validate_family_topology


def test_validation_import_does_not_eagerly_import_sca() -> None:
    command = (
        "import json,sys; import llm_csp.validation; "
        "print(json.dumps(any(n == 'sca' or n.startswith('sca.') for n in sys.modules)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command], capture_output=True, text=True, check=True
    )
    assert json.loads(completed.stdout.strip()) is False


def test_general_backend_unavailable_is_structured(monkeypatch, tmp_path) -> None:
    def unavailable():
        raise ModuleNotFoundError("No module named 'sca'", name="sca")

    monkeypatch.setattr(adapter, "_load_general_backend", unavailable)
    result = validate_cif(tmp_path / "anything.cif")

    assert result.status == "backend_unavailable"
    assert result.parseable is False
    assert result.valid is None
    assert result.errors[0].kind == "backend_unavailable"
    assert result.backend.name == "Structured_Crystal_Analyser"
    assert result.backend.validated_revision


def test_topology_backend_unavailable_is_structured(monkeypatch) -> None:
    def unavailable():
        raise ImportError("SCA topology dependencies unavailable")

    monkeypatch.setattr(adapter, "_load_topology_backend", unavailable)
    result = validate_family_topology(object(), "ROCKSALT")

    assert result.status == "backend_unavailable"
    assert result.available is False
    assert result.errors[0].kind == "backend_unavailable"


def test_unsupported_topology_policy_is_explicit() -> None:
    result = validate_family_topology(object(), "not-a-policy")

    assert result.status == "unsupported_policy"
    assert result.available is False
    assert result.errors[0].kind == "unsupported_policy"


def test_supported_policy_catalog_matches_frozen_sca_contract() -> None:
    assert SUPPORTED_TOPOLOGY_POLICIES == {
        "ROCKSALT",
        "FLUORITE",
        "PEROVSKITE_3D",
        "SPINEL",
        "OLIVINE",
        "LAYERED_OXIDE",
        "ARGYRODITE_ORDERED",
        "HALIDE_PEROVSKITE_3D",
        "NASICON_ORDERED",
        "GENERIC_SCAFFOLD_ONLY",
    }


def test_unexpected_backend_exception_is_evaluation_failure(monkeypatch, tmp_path) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("backend crashed")

    monkeypatch.setattr(adapter, "_load_general_backend", lambda: broken)
    result = validate_cif(tmp_path / "anything.cif")

    assert result.status == "evaluation_failure"
    assert result.errors[0].kind == "evaluation_failure"
