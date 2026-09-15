# Implementation Report

## Summary
- Implemented non-SoK local orchestrator package `sok_llm_orchestrator` with CLI commands:
  - `doctor`
  - `run`
  - `chat`
  - `skills list|show|validate`
- Implemented deterministic orchestration pipeline:
  - `crystal.csp_pack` (policy-aware defaults)
  - optional `spp.run_pipeline` + `spp.package_for_qlip` (tolerant normalization + sandbox/caps)
  - strict local QLIP `SolveRequest` validation before `qlip.validate_request` and `qlip.solve`
  - optional `crystal.novelty_check` if `cif_path` is produced by solve
- Implemented deterministic run artifacts and logging:
  - `runs/<run_id>/manifest.json`
  - `runs/<run_id>/tool_call_log.jsonl`
  - per-call request/response JSON + `.sha256`
- Added skillcard schema + 13 tool skillcards and prompt pack integration.
- Added offline fake MCP servers for CrystalDB/SPP/QLIP and complete offline tests.

## Commands Run
1. `python -m sok_llm_orchestrator.cli --help`  
   - PASS
2. `python -m sok_llm_orchestrator.cli skills validate`  
   - PASS
3. `pytest -q`  
   - PASS (`24 passed`)
4. `python -m sok_llm_orchestrator.cli --workspace .sokllm_workspace doctor --mode stub`  
   - PASS
5. `python -m sok_llm_orchestrator.cli --workspace .sokllm_workspace run --mode stub --query "TiO2 rutile-like" --with-spp true`  
   - PASS
6. `echo "exit" | python -m sok_llm_orchestrator.cli --workspace .sokllm_workspace chat --mode stub --with-spp true`  
   - PASS

## Status
- Definition-of-done targets for this non-SoK pass are implemented and verified offline.

## QLIP Contract Sync (Post-Add)
- Synced QLIP handling to the added contract:
  - canonical top-level `SolveRequest` shape: `version/problem/constraints/guidance/solver`
  - required `solver.name = "gurobi"`
  - strict `objective.energy_spp` plugin params schema (`additionalProperties=false`)
  - added `qlip.list_constraints` support in expected tool surface + fake server
- Added real local-LLM evaluation harness:
  - `sokllm eval live-llm --trials N --min-pass-rate X`
  - writes `.sokllm_workspace/evals/live_llm_report.json`
  - optional live pytest marker suite: `pytest -q -m live_llm`
