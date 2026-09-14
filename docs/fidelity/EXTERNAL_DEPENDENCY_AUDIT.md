# External Dependency Audit

Audit date: 2026-09-14. This document distinguishes legitimate services and Python dependencies from assets that the source system actually held locally. It does not grant redistribution rights.

## Decision table

| Dependency or asset | Source evidence | Classification | Archive decision |
|---|---|---|---|
| Gurobi / `gurobipy` | QLIP solver selection and optimization call sites | `ALLOWED_EXTERNAL_RUNTIME` | Keep external; user supplies licence/runtime. |
| LM Studio OpenAI-compatible chat endpoint | Skill-Loop `LLMClient`, default `http://localhost:1234/v1` | `ALLOWED_EXTERNAL_RUNTIME` | Keep external. Preserve model discovery, retry, JSON-repair and timeout behavior. |
| Ollama | Skill-Loop intent-judge script and OpenAI-compatible agent configuration | `ALLOWED_EXTERNAL_RUNTIME` | Keep external. Preserve native `/api/chat` and `/api/tags` behavior where used. |
| BGE-M3 embedding model served by LM Studio | Crystal-DB embedding configuration (`CRYSTALDB_EMBED_BASE_URL`) | `ALLOWED_EXTERNAL_RUNTIME` | Keep model service external, but preserve the embedding client, model/version metadata and indexes. |
| Normal Python packages (`ase`, `numpy`, `pymatgen`, `scipy`, `smact`, `pyomo`, `jsonschema`, MCP SDK, etc.) | Source `pyproject.toml`/requirements and imports | `PYTHON_PACKAGE_DEPENDENCY` | Declare normally; pin only where reproducibility requires it. |
| Materials Project API | Crystal-DB/QLIP `MP_API_KEY` and API clients | `ORIGINAL_TRUE_EXTERNAL_DEPENDENCY` | Keep optional network feature external; offline operation must use archived snapshots. |
| Optional SCA MLIP integrations (CHGNet, ALIGNN, M3GNet/MatGL, MACE, SevenNet) and their weights | SCA optional backends and environment variables | `OPTIONAL_EXTERNAL_FEATURE` | Do not bundle weights by default; retain adapters and installation documentation. |
| CASTEP, Slurm and visualization executables | SCA/Skill-Loop command configuration | `OPTIONAL_EXTERNAL_FEATURE` | Keep optional external programs; retain the source adapters. |
| Crystal-DB operational DB/CIF/index corpus | Source used `data/phase6_mp_10k.db` (881,799,168 bytes), 10,001 `mp_stable_10k` files, 10,000 cache files and specialist databases | `SHOULD_BE_ARCHIVED` | Recover a provenance-cleared snapshot. The current archive's path-only configuration is not fidelity. |
| Skill-Loop retrieval corpus and run state | `data/corpora`: 1,745 files/74,736,622 bytes; `runs`: 526 files/80,671,699 bytes | `SHOULD_BE_ARCHIVED` | Archive the selected operational corpus and a minimal canonical trace set with checksums. |
| SPP fitted potentials and QLIP handoff packages | SPP repo has 27,041 `.pot` files/132,797,977 bytes and `QLIP_Outputs`: 9,056 files/93,864,738 bytes | `SHOULD_BE_ARCHIVED` | Recover the exact selected POT/package set after provenance review. |
| QLIP local SPP library | QLIP repo has 19,486 `.pot` files/96,334,782 bytes and `data/spp`: 20,328 files/263,829,560 bytes | `SHOULD_BE_ARCHIVED` | Restore a deduplicated, checksummed copy without changing QLIP lookup semantics. |
| Skill-Loop local potential holdings | 55,870 `.pot` files/207,440,669 bytes | `SHOULD_BE_ARCHIVED` | Reconcile with SPP/QLIP holdings and preserve the exact source-selected set. |
| Scaffold corpus/templates | QLIP and Skill-Loop local data/resources and scaffold builders | `SHOULD_BE_ARCHIVED` | `QLIP_SCAFFOLD_CORPUS_ROOT` must point to an approved in-archive corpus; it is not proven originally external. |
| SCA authored source | Supported Git revision currently installed via VCS URL | `SHOULD_BE_ARCHIVED` | Vendor the package source after approval; a network/VCS install is unnecessary for the unified target. |
| RoboCrys | Crystal-DB text-description integration/imports | `PYTHON_PACKAGE_DEPENDENCY` | Install normally where supported; preserve cached/generated descriptions separately. |
| Generated reports, broad benchmark outputs and failed/duplicate runs | Hundreds of thousands of local files | `UNKNOWN` | Retain outside the release until a human selects canonical evidence and confirms rights. |

## Environment contract

The complete occurrence-level inventory is in `evidence/ENVIRONMENT_VARIABLES.csv`. The operational contract includes:

- Skill-Loop: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, MCP command variables, allowed read/write roots, optimization settings, `SKILL_LOOP_*`, and VESTA configuration.
- Crystal-DB: `CRYSTAL_DB_PATH`, `CRYSTALDB_PATH`, `CRYSTALDB_CONFIG`, `CRYSTALDB_POLICY_MODE`, `CRYSTALDB_EMBED_BASE_URL`, and `MP_API_KEY`.
- SPP-Maker: `SPP_MCP_ALLOWED_READ_ROOTS`, `SPP_MCP_ALLOWED_WRITE_ROOTS`, limits, and FastMCP selection.
- QLIP: `QLIP_BASE_DATA_DIR`, allowed roots, solver/debug/error-dump settings, visualization directory, and SPP POT/regularisation roots.
- SCA: CASTEP and MLIP command/device/output settings.

An environment variable does not make an asset a legitimate external dependency. If the source runtime normally addressed a repository-local database, corpus, POT directory, index, prompt or schema through such a variable, that item remains `SHOULD_BE_ARCHIVED` unless an explicit provenance decision excludes it.

## Conclusion

The only intended primary runtime services are Gurobi, LM Studio and Ollama. Materials Project and SCA scientific backends are original optional features. The large Crystal-DB, SPP, QLIP and Skill-Loop local holdings are not interchangeable with external services and must not be described as merely user-supplied dependencies.
