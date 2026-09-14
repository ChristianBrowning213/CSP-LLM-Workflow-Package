# Source Fidelity Audit

Audit branch: `audit/source-fidelity`  
Audit date: 2026-09-14  
Overall result: **`FIDELITY_GAPS_FOUND`**

## Executive conclusion

`CSP-LLM-Workflow-Package` is not presently a faithful unified archive of the five original systems. Released v0.1.0 is a **`REDUCED_DISTRIBUTION`**: it contains useful deterministic subsets, but omits major source namespaces, CLIs, MCP surfaces, orchestration, operational data and runtime assets. Current `develop` retains those gaps and adds a new Ticket 18–21 agent model that is not schema- or tool-compatible with the existing Skill-Loop implementation.

Passing archive tests demonstrate internal consistency of the reduced implementation, not source fidelity. The complete archive suite passed 263 tests with 5 optional skips, while direct source inspection and the 2,239-row matrix identify extensive missing and externalized behavior.

## Audit scope

The audit inspected Git objects at the named revisions, current worktree state, executable modules, tests, schemas/configuration, CLI/MCP entry points, documentation and local non-Git asset trees. Existing migration documents were used only as secondary evidence. No scientific or runtime implementation was changed.

Complete evidence is under `docs/fidelity/evidence/`: file hashes, local asset sizes, Python symbols, environment-variable occurrences and sibling-path references. The file inventory includes tracked files at frozen revisions and local asset summaries; ignored/untracked holdings are summarized separately rather than silently treated as external.

## Source revisions

| Repository | Current branch / HEAD | Selected scientific revision | Later package/licence state | Worktree |
|---|---|---|---|---|
| Skill-Loop-CSP | `Agentic-Loop` / `36f6280e47387643853ac0cfc510e20c5d595834` | `b2130661b4690623877e852dc03132506aa720dd` | HEAD changes only licensing metadata | Pre-existing untracked `benchmarks/external/OMatG/`; untouched |
| Crystal-DB | `mcp` / `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31` | `e33d5cc55be01f800a7cf055cc1793d982deb5bc` | HEAD changes only licensing metadata | clean |
| SPP-Maker-QLIP | `SPP_MCP` / `82114cd05f0cb40149d13c20adeafe4c437a03ae` | `3a2d557811973265f3373ec881cc8057a89789d2` | HEAD changes only licensing metadata | no reported changes; inaccessible ignored pytest temp directories exist |
| QLIP | `QLIP-SPP-MCP-Esma` / `a619ab379c62b5edefd6bb00076267e149f283ce` | same | current source/licensing state is the selected revision | clean |
| Structured Crystal Analyser | `main` / `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` | `e5b291312151f34949a5e6ef0f43bebfeb752bc9` | supported 0.1.1 adds licence/package metadata and dependency changes | clean |
| Unified archive | `audit/source-fidelity`, based on `develop` `206ea8ecd9acc25e813e676359929fd7ad3efc0f` | v0.1/main `2dbf5e8852dc62c42d97385bc96ea90166d0fc74` | v0.2 development base above | audit files only |

## Actual original system architecture

The working system is a set of existing packages connected through explicit Python, CLI and MCP contracts:

```text
User / sokllm CLI
  -> workflow.runner.run_csp_workflow (deterministic workflow)
  -> agentic.chain_runtime.run_live_proposal_review_chain
       -> planner_runtime.run_live_planner_and_compile
          -> llm_runtime.AgentLLMRuntime.run_agent("planner")
          -> plan_compile.compile_run_plan_to_tool_proposals
          -> tools.ToolRegistry validation
       -> run_manager_runtime.run_live_run_manager
          -> execution intent / handoff / preflight / gated executor
          -> step_execution + tool_execution_adapters
             -> Crystal-DB MCP/direct calls
             -> SPP-Maker MCP/direct calls
             -> QLIP MCP/direct calls
       -> evaluator_runtime.run_live_evaluator
       -> orchestrator_runtime.run_live_orchestrator
       -> archive / manager logging / trace rendering / resume-recovery records
```

The registered agent tools are `crystal.csp_pack`, `spp.run_pipeline`, `spp.package_for_qlip`, `qlip.validate_request`, `qlip.solve`, and `crystal.novelty_check`. Source modules also implement optimization loops, session storage, failure handling and QLIP recovery. Prompts are package-owned Markdown files.

The deterministic workflow routes evidence/corpora, builds Crystal-DB CSP packs, fits/selects SPP/regulator resources, selects or constructs scaffolds, compiles QLIP requests, solves, validates with SCA, checks novelty and writes attempt manifests/traces/reports. The archive runner represents only a reduced path.

## Archive architecture

The archive packages reduced `qlip` and `crystal_db` trees, a renamed `llm_csp.spp` subset, workflow/retrieval/generation wrappers and two-function SCA adapter. Its only console script is `llm-csp`. SCA is a VCS optional dependency. It does not package `sok_llm_orchestrator`, `spp_maker`, `spp_maker_mcp`, `spp_maker_qlip` or `sca`.

Current develop additionally has `llm_csp.agentic` typed state, budgets, approvals, termination, provider-independent model protocol/fake, planner and four generic tool adapters. This is a new architecture, not the archived source architecture.

## Subsystem findings

### QLIP

Original Python surface includes `qlip.core.solve`, validation, solve request/result models, constraint and guidance registries, ordered/multi/top-k/exclusion scaffold occupation, NASICON, SPP objectives, motif, visualization/VESTA, paper-diversity and scaffold CLIs. It supports `python -m qlip` and `python -m qlip.scaffolds`.

The operational MCP server uses FastMCP/stdin transport and implements `qlip.shapes`, `qlip.list_constraints`, `qlip.list_guidance`, `qlip.validate_request`, and `qlip.solve`, with boundary normalization and JSON schemas. `qlip.explain_failure`/`qlip.explain_infeasibility` were documentation concepts, not registered source tools. The archive preserves a tested core but omits experimental guidance/constraints, scaffold CLI, SPP benchmark/E2E/visual helpers, paper-diversity, VESTA and original resources/POTs. Generated replacement chemistry resources are not byte- or provenance-equivalent.

### Crystal-DB

The operational source includes database/query/cache, ingestion, CIF storage/export, descriptors/fingerprints, CrystalCard/text generation, embeddings and text/sequence indexes, retrieval/configuration, similarity, novelty/rediscovery, CSP packs, policies/gates, family and ordered-family classification, agent/audit/run logs, snapshots, reports, calibration/evaluation/benchmarks, CLI, readiness and MCP schemas/tools. It supports `python -m crystal_db`.

The archive retains a small API/database/retrieval/readiness/MCP subset and three schemas. It omits most ingestion, representation, index generation, classification, governance, reporting, benchmark and CLI surface. Synthetic archive tests cannot establish parity with the source's local operational database.

### SPP-Maker

Original namespaces implement fit/run/score/calibrate CLIs, corpus preparation, required-pair extraction, histograms, potential fitting and POT I/O/library, regulator compatibility/blend/union, common contracts, QLIP packaging, `QLIP_Outputs` publication/indexing, reports and orchestration. Entry points are `spp-maker` and `spp-maker-mcp`. MCP tools are `spp.run_pipeline`, `spp.check_compat`, `spp.package_for_qlip`, and `spp.publish_to_qlip_outputs`.

The archive's 16-module `llm_csp.spp` subset changes the namespace and omits the original CLIs, MCP server, calibration/run orchestration, common contract, publication/index registry and package handoff surfaces. Old imports do not work.

### SCA

SCA includes parsing, composition, geometry, bonds/multiplicity, symmetry/topology/CrystalNN, uniqueness/novelty/intent, batch/reporting/traceability, benchmark and paper interfaces, CASTEP/Slurm analysis, CHGNet, ALIGNN, M3GNet/MatGL, MACE and SevenNet integrations, schemas and the `sca` CLI. The archive exposes only two wrapper functions and downloads SCA from a Git revision.

Separate-package installation is not technically necessary. The supported source is small enough to vendor as `packages/sca/`; optional model weights and proprietary executables may remain external. A self-contained archive must not require a separately cloned or network-fetched SCA repository.

## Agentic findings

The exact source records are:

- `AgentInputEnvelope`: schema version, agent name, payload, context summary, artifact references.
- `RunPlan`: overall/run goals, stage, detailed description, hoped-for finding, textual plan, related prior work, success criteria and stop conditions.
- `ToolCallProposal`: step, tool name, arguments, expected result, reason and condition.
- `RunManagerLog`: run ID, attempted tool calls, handled failures, manager notes and created artifacts.
- `RunEvaluation`: goals/progress, summary, successes/weaknesses, scientific findings, best artifacts, scores, prior-best comparison, recommendation, stop and clarification fields.
- `OrchestratorDecision`: decision/reason, next goal/stage, evidence, stopping message and clarification.
- `AgenticRunRecord`: IDs/goals/stage/schema, agent order, four agent outputs, validation results/summary, readiness, artifacts and warnings.

Tickets 18–21 introduce `AgentRunState`, `AgentPlan`, `PlanStep`, `ApprovalRequest`, `AgentBudgets`, `Planner`, `AgentModel`, `FakeAgentModel`, and generic `search_crystal_db`, `run_csp`, `validate_candidate`, `inspect_run` tools. These are `NEW_REPLACEMENT`, not backward-compatible schema equivalents. Component-level disposition is in `INVENTED_COMPONENTS.md`.

## Interface findings

Only `llm-csp` is exposed by the archive. Missing compatibility interfaces include `sokllm` workflow/agent commands, `spp-maker`, `spp-maker-mcp`, both QLIP module CLIs, Crystal-DB module CLI and `sca`. Original Python namespaces `sok_llm_orchestrator.*`, `spp_maker.*`, `spp_maker_mcp.*`, `spp_maker_qlip.*` and `sca.*` are absent; QLIP/Crystal imports are partial.

The archive does not reproduce the full MCP servers, resources, schemas, prompts, normalization and environment contracts of QLIP, Crystal-DB and SPP-Maker. Replacing six orchestration tools with four generic tools is incompatible, even if similar operations can be reached indirectly.

Schema results are: selected unchanged modules/resources are `EXACT`; tested reduced QLIP/SPP/Crystal adapters are `BACKWARD_COMPATIBLE` only for exercised fixtures; omitted schemas are incompatible by absence; Ticket 19–21 agent schemas are `NEW_REPLACEMENT`.

## Data/resource findings

The working trees contain substantial local operational holdings: Crystal data 939,505,743 bytes plus 802,471,896 bytes of artifacts; SPP data 7,331,874 bytes, outputs 93,864,738 bytes and output tree 91,211,119 bytes; QLIP data 264,150,616 bytes; Skill-Loop corpora 74,736,622 bytes and run state 80,671,699 bytes. POT counts are 55,870/207,440,669 bytes (Skill-Loop), 27,041/132,797,977 (SPP) and 19,486/96,334,782 (QLIP).

These trees mix source assets, generated derivatives, caches, benchmark/paper outputs and runtime databases. Known operational items—Crystal SQLite/CIF/index data, selected corpus snapshots, SPP POT/package libraries and QLIP scaffold/regulator resources—are `EXTERNALIZED_BUT_ORIGINALLY_LOCAL`. Arbitrary cache and duplicate output trees remain `UNKNOWN_REQUIRES_REVIEW`; they should not be copied wholesale. Provenance/licence review remains mandatory for third-party datasets and weights.

## External dependency findings

Gurobi, LM Studio and Ollama are `ALLOWED_EXTERNAL_RUNTIME`. Normal imported libraries are `PYTHON_PACKAGE_DEPENDENCY`. Materials Project is an original optional network dependency; optional SCA backends/weights and CASTEP/Slurm/VESTA are original optional features. Local databases, indexes, CIF collections, POT libraries, prompts and schemas are not made true external dependencies merely by an environment-variable path. See `EXTERNAL_DEPENDENCY_AUDIT.md`.

Original agent reasoning defaults to OpenAI-compatible `http://localhost:1234/v1`, posts to `/chat/completions`, and discovers LM Studio through `/api/v1/models` with `/v1/models` fallback. It uses configurable model/key, 60-second agent timeout (20-second client default), two client retries/backoff and up to three structured-output attempts with fence removal, JSON extraction, type/field validation and correction prompts. Ollama can be selected via its OpenAI-compatible `http://127.0.0.1:11434/v1`; the evidence-pack intent judge separately uses native `http://localhost:11434/api/chat` and `/api/tags`. The archive has no equivalent live implementation: `MISSING_FROM_ARCHIVE`.

Crystal BGE-M3 is a distinct embedding service at `CRYSTALDB_EMBED_BASE_URL`, default `http://127.0.0.1:1234/v1`, with model `text-embedding-bge-m3`/version `lmstudio_v1`. It must not be conflated with the agent reasoning model.

Environment parity is incomplete. The archive example preserves `CRYSTAL_DB_PATH`, `CRYSTALDB_EMBED_BASE_URL`, `QLIP_SOLVER` and optional QLIP asset roots, and introduces `CRYSTAL_DB_DATA_ROOT`, `CRYSTALDB_EMBED_*` tuning, `SPP_SOURCE_POT_ROOT` and `QLIP_SCAFFOLD_CORPUS_ROOT`. It omits the original agent `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`, Ollama backend configuration, Skill-Loop MCP commands/allowed roots/optimization and `SKILL_LOOP_*`, Crystal policy/config aliases, SPP MCP limits/roots, QLIP debug/error/visualization settings, and SCA backend settings. Exact occurrence-level names and call sites are in `evidence/ENVIRONMENT_VARIABLES.csv`; required sibling/path rewiring is in `evidence/SIBLING_PATH_REFERENCES.csv`.

## Behavioural parity

The complete archive suite passed **263 tests with 5 optional skips**. A focused 125-test cross-subsystem set exercised deterministic agent contracts, workflow, Crystal retrieval/CSP pack/MCP, SPP handoff/required pairs, QLIP solve/NASICON/CIF/time-limit and validation: **121 passed, 4 skipped**. A same-input QLIP validation probe produced byte-identical normalized JSON in source and archive: `unknown_constraint_id`, `pot_root_missing`, and `solve_data_preflight_failed` at the same paths. These establish limited adapted parity for those paths.

Observed mismatches are structural and executable: missing commands/imports/tools/schemas; four new generic tools versus six source tools; absent live LM Studio/Ollama prompt/runtime; reduced workflow artifact tree; externalized data; and missing source subsystem implementations. A canonical full source workflow was not compared end-to-end because the archive lacks the source orchestrator and selected local asset bundle; this is itself a fidelity blocker, not an optional skip.

Expected source artifacts include `run_plan.json`, manager/tool logs, evaluation/orchestrator decisions, experiment/session state, retrieval bundle/CIF export, POT and QLIP package, request/result, candidate CIF, validation/novelty reports, attempt manifests, traces and final reports. The archive produces only a reduced/renamed subset.

## Test parity

Direct unchanged source-suite runs (cache disabled, temporary base outside each repository) produced:

| Suite | Result | External/other note |
|---|---|---|
| Skill-Loop-CSP | 1,339 passed, 15 skipped | 140 warnings; default suite skips unavailable/live cases |
| Crystal-DB | 176 passed | 68 warnings |
| SPP-Maker-QLIP | 128 passed, 1 failed | schema snapshot differed under the available dependency environment (`allow_fallback_precompiled`); no source change made |
| QLIP | 260 passed | 37 warnings |
| SCA | 191 passed | 13 warnings |
| Archive complete suite | 263 passed, 5 skipped | skips require external scientific assets |

Hundreds of source tests have no archive equivalent because their corresponding modules were omitted. The CSV marks source test/support files as historical evidence and missing implementation rows name their source suite; that does not mean the behavior is covered.

## Missing functionality

Operational gaps include the complete Skill-Loop CLI/orchestrator/agent/prompt/model/tool/recovery/optimization/session/trace implementation; most Crystal ingestion, data/index generation, representations/search modes, novelty/governance/classification/report/benchmark/CLI/MCP surfaces; SPP-Maker namespaces, CLIs, MCP, calibration/run, regulator, publishing and QLIP-package machinery; QLIP guidance/constraint/scaffold/visual/SPP utility surfaces and source resources; and the full SCA package/CLI/backends. Missing local operational data prevents the archive from reproducing real-system behavior without sibling/manual assets.

## New/non-source functionality

The Ticket 18–21 state models, budget/approval/termination abstractions, provider-independent model protocol/fake, planner and generic tool registry/adapters are new replacements. They pass their own tests but are not evidence of source preservation. Generated QLIP chemistry resources and the unified reduced CLI are also replacements where they remove old compatibility surfaces.

## Risk of current changes

The greatest risks are false fidelity claims, silent schema/tool incompatibility, non-reproducible results from absent databases/POTs, network-dependent installation, loss of old imports/commands, and divergent agent decisions/artifacts. Recovery performed atop the new agent abstraction could further obscure the source boundary. v0.1.0 should remain untouched as a useful reduced deterministic release record.

## Final fidelity classification

| Target | Classification | Basis |
|---|---|---|
| v0.1.0 / main | **`REDUCED_DISTRIBUTION`** | Deliberately reduced code, data and interfaces |
| develop at `206ea8e` | **`FIDELITY_GAPS_FOUND`** | v0.1 omissions plus `NEW_NOT_IN_SOURCE` agent components |

Future success means: fresh clone → install from this repository → configure Gurobi, LM Studio and Ollama → run the existing systems through their original Python/CLI/MCP interfaces, with no sibling clones, manual source-asset copying or VCS-installed SCA. Any other external requirement must be proven external in the selected source implementation.
