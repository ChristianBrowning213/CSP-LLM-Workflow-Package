# Local LLM Real Test Plan

This suite checks your real local LLM against strict QLIP request-generation requirements.

## Command

```powershell
$env:PYTHONPATH='src'
$env:LLM_BASE_URL='http://localhost:1234/v1'
$env:LLM_API_KEY='local-key'
$env:LLM_MODEL='your-model'
python -m sok_llm_orchestrator.cli --workspace .sokllm_workspace eval live-llm --trials 3 --min-pass-rate 0.80
```

## What it validates

- Response is valid JSON (no markdown wrappers needed by parser).
- JSON passes strict `validate_solve_request`:
  - top-level keys must be exactly `version/problem/constraints/guidance/solver`
  - `version == "1.0"`
  - `solver.name == "gurobi"`
  - strict `objective.energy_spp` plugin params contract when present
- Case logic:
  - baseline case must not include SPP guidance
  - SPP cases must include `guidance[].id == objective.energy_spp`

## Output

- Report file: `.sokllm_workspace/evals/live_llm_report.json`
- CLI returns non-zero if pass rate is below `--min-pass-rate`.
- If pass rate is low, inspect `response_preview` in the report rows to see what the model emitted.

## Optional live pytest

```powershell
$env:PYTHONPATH='src'
$env:RUN_LIVE_LLM_TESTS='1'
$env:LLM_BASE_URL='http://localhost:1234/v1'
$env:LLM_API_KEY='local-key'
$env:LLM_MODEL='your-model'
$env:LIVE_LLM_TIMEOUT_S='90'
$env:LIVE_LLM_TRIALS='2'
$env:LIVE_LLM_MIN_PASS_RATE='0.66'
pytest -q -m live_llm
```

## Real MCP + Pipeline E2E

This validates full live orchestration (doctor + guided run + paired run + benchmark run).

```powershell
$env:PYTHONPATH='src'
$env:RUN_LIVE_E2E_TESTS='1'
$env:LLM_BASE_URL='http://localhost:1234/v1'
$env:LLM_API_KEY='local-key'  # optional for localhost base_url
$env:LLM_MODEL='your-model'
$env:CRYSTALDB_MCP_CMD='python -m crystaldb_mcp.server'
$env:SPP_MCP_CMD='python -m spp_mcp.server'
$env:QLIP_MCP_CMD='python -m qlip_mcp.server'
python -m sok_llm_orchestrator.cli --workspace .sokllm_workspace_live eval e2e --mode live --query "TiO2 rutile-like" --cases docs/branch/benchmarks/internal_rediscovery_cases.json
```

Live pytest hook:

```powershell
pytest -q -m live_e2e
```
