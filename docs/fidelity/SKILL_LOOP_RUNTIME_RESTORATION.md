# Ticket 31 — Skill-Loop-CSP runtime restoration

Status: `SKILL_LOOP_RUNTIME_RESTORED`.

Licensing revision `36f6280e47387643853ac0cfc510e20c5d595834` is scientific
revision `b2130661b4690623877e852dc03132506aa720dd` plus licensing metadata.
The original `sok_llm_orchestrator` namespace, `sokllm` CLI, execution chain,
planner, run manager, evaluator, orchestrator, prompts, schemas, gates,
policies, state/archive/tracing code, LM Studio client/discovery, Ollama
evidence-intent helpers, fixtures, and tests were copied. Prompt hashes are in
`SKILL_LOOP_PROMPT_HASHES.txt`.

The six source tool names are unchanged. Packaging-only defaults now launch
the bundled source servers: `crystal_db.mcp.server`,
`spp_maker_mcp.server`, and `qlip.mcp.server`. A live MCP discovery returned
all 16 underlying source tools, including the required six. Model-free
planner/manager/evaluator/orchestrator/chain replay selected tests passed
54/54; the one additionally selected source configuration test failed because
it explicitly requires the old sibling checkout path.

The final full imported suite produced 1,234 passed, 98 failed, and 22 skipped
across all 1,354 source tests. Remaining failure classes were absent external benchmark datasets/model
weights, deliberately excluded historical paper outputs, source tests that
assert sibling paths, and optional research dependencies—not missing core
runtime modules or altered scientific policies. External `benchmarks/external`
data and untracked OMatG were not copied.
