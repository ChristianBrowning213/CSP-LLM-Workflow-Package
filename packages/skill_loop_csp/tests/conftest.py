from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PYTHONUTF8", "1")


@pytest.fixture(autouse=True)
def isolate_agentic_pipeline_import_boundary(request: pytest.FixtureRequest):
    """Make agentic import-boundary assertions independent of test order.

    The full suite legitimately imports the production pipeline before the
    agentic tests are collected.  Tests named ``*_does_not_import_pipeline_code``
    verify that their own action does not import that module, so start those
    tests with the relevant module absent and restore the prior interpreter
    state afterwards.
    """

    module_name = "sok_llm_orchestrator.orchestrator.pipeline"
    is_agentic_pipeline_boundary = (
        "test_agentic" in str(request.node.path).replace("\\", "/")
        and "pipeline" in request.node.name
    )
    if "pipeline_code" not in request.node.name and not is_agentic_pipeline_boundary:
        yield
        return

    previous = sys.modules.pop(module_name, None)
    try:
        yield
    finally:
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous


@pytest.fixture
def workdir() -> Path:
    base = ROOT / "test_workdir"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"run_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
