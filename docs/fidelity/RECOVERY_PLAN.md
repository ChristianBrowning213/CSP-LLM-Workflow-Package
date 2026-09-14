# Source-Fidelity Recovery Plan

This is a recovery sequence, not authorization to perform migration or redistribution. Every stage requires preserved source revisions and provenance review.

## Priority 0 — Freeze evidence and rights decisions

1. Record the five frozen scientific revisions and the later licence-only revisions. Preserve `FILE_INVENTORY.csv`, hashes, environment inventory and this matrix.
2. Obtain a human decision for databases, CIF corpora, POT files, element/radius data, prompts and third-party fixtures. Do not infer redistribution rights from local possession.
3. Choose exact canonical subsets from duplicate run/output trees. Produce SHA-256 manifests and provenance records.

Exit criterion: every selected asset is either approved for archive inclusion or has a named, documented exclusion with an impact statement.

## Priority 1 — Isolate non-source agent development

Keep the Ticket 18–21 agent layer isolated and labelled `NEW_NOT_IN_SOURCE`; do not extend it while fidelity recovery is underway.

Exit criterion: no archive-native abstraction can be mistaken for a migrated source implementation.

## Priority 2 — Restore operational Crystal-DB

Import the complete `crystal_db` and `mcp_server` surfaces: CLI, API, ingestion, database/query/cache, embeddings, text/sequence indexes, retrieval/configuration, CSP packs, novelty/gates, family classification, snapshots, reporting, benchmarking and all schemas. Preserve `python -m crystal_db` and MCP contracts. Add the approved operational DB/CIF/index snapshot; do not replace it with an empty path contract.

Exit criterion: original CLI/API/MCP tests pass against the archived snapshot and representative retrieval/CSP-pack outputs match.

## Priority 3 — Restore SPP-Maker and QLIP handoff

Import `spp_maker`, `spp_maker_mcp` and `spp_maker_qlip` under their source namespaces. Restore the `spp-maker` and `spp-maker-mcp` entry points, four MCP tools, calibration/fit/score/run orchestration, compatibility, publication, package/index contracts and approved POT/QLIP-output assets.

Exit criterion: exact source fixtures produce equivalent POT metadata, compatibility results, QLIP packages and published indexes.

## Priority 4 — Complete QLIP

Restore missing constraints/guidance, scaffold CLI, SPP utilities, paper-diversity/visualization modules, source JSON resources and approved bundled POTs. Preserve `python -m qlip`, `python -m qlip.scaffolds`, the five actual MCP tools (`shapes`, `list_constraints`, `list_guidance`, `validate_request`, `solve`), solver status/error shapes and output artifacts.

Exit criterion: frozen source and archive pass the same unit/integration suite with serialized request/result equivalence and solver-tolerant numerical comparisons.

## Priority 5 — Vendor the supported SCA boundary

Import SCA 0.1.1 at `3ede1ee2ad1a972b7c0a0809a9ec7bdab9b1b6af` under its `sca` namespace. Preserve its CLI, parsers, composition/geometry/symmetry/topology/uniqueness/novelty/intent analyses, batch/reporting/traceability, DFT workflows and optional MLIP adapters. External model weights and proprietary executables remain optional.

Exit criterion: install from wheel without VCS/network access and pass SCA's source suite plus unified workflow validation.

## Priority 6 — Restore the real orchestration system

Import frozen `sok_llm_orchestrator` under its original namespace, including CLI, settings, workflow, optimization, MCP clients/shims, agentic modules, prompts, schemas, trace/archive machinery, recovery logic and tests. Preserve the six-tool registry and planner → compile → run manager → tool adapters → evaluator → orchestrator call graph. Rewire only sibling paths/imports to the recovered in-repository packages and assets; restore LM Studio/Ollama configuration exactly.

Exit criterion: source and archive run the same deterministic fixtures and emit schema-equivalent plans, proposals, logs, evaluations, decisions, traces and artifact references.

## Priority 7 — End-to-end proof and release

Build wheels/sdists in an isolated environment; install offline from built artifacts plus declared Python wheels; run original source tests, archive tests and fixed cross-repository fixtures. Record outputs, versions, seeds, solver tolerances, service/model identifiers and hashes. Only then reconsider the release gate.

Minimum release evidence:

- exact namespace/import/entry-point inventory;
- schema and MCP contract snapshots;
- representative byte equality where deterministic, otherwise documented scientific tolerances;
- local-asset manifest and licence/provenance approval;
- full test totals and reasons for every skip/failure;
- no dependency on sibling repository paths.
