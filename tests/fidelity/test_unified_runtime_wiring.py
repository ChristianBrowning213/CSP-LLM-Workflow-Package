from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SKILL_SRC = ROOT / "packages" / "skill_loop_csp" / "src"


def _skill_subprocess(expression: str) -> object:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(SKILL_SRC), env.get("PYTHONPATH", "")])
    completed = subprocess.run(
        [sys.executable, "-c", expression],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_original_public_namespaces_import() -> None:
    import crystal_db
    import qlip
    import sca
    import spp_maker
    import spp_maker_qlip

    assert all(
        module.__file__
        for module in (crystal_db, spp_maker, spp_maker_qlip, qlip, sca)
    )
    skill_file = _skill_subprocess("import json,sok_llm_orchestrator; print(json.dumps(sok_llm_orchestrator.__file__))")
    assert str(SKILL_SRC).casefold() in str(skill_file).casefold()


def test_skill_loop_defaults_launch_bundled_mcp_modules() -> None:
    values = _skill_subprocess(
        "import json; from sok_llm_orchestrator.config import Settings; "
        "s=Settings.from_sources(None); print(json.dumps([s.crystaldb_mcp_cmd,s.spp_mcp_cmd,"
        "s.qlip_mcp_cmd,s.crystaldb_mcp_cwd,s.spp_mcp_cwd,s.qlip_mcp_cwd]))"
    )
    assert values == [
        "python -m crystal_db.mcp.server",
        "python -m spp_maker_mcp.server",
        "python -m qlip.mcp.server",
        None,
        None,
        None,
    ]


def test_all_four_agent_prompts_are_packaged_and_loadable() -> None:
    result = _skill_subprocess(
        "import json; from sok_llm_orchestrator.agentic.prompting import load_agent_prompt,prompt_path_for_agent; "
        "agents=['planner','run_manager','evaluator','orchestrator']; "
        "print(json.dumps([[str(prompt_path_for_agent(a)),bool(load_agent_prompt(a).strip())] for a in agents]))"
    )
    assert all(Path(path).is_file() and loaded for path, loaded in result)
