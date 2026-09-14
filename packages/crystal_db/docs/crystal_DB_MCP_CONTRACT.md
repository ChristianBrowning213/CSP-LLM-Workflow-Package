# Crystal-DB API Contract

Last updated: 2026-03-06

This contract defines the stable API surface for:
- Python wrapper API (`crystal_db/api.py`)
- MCP server tools (`mcp_server/server.py`)

## Versioning

- All top-level API responses include `schema_version`.
- Response payloads must validate against the matching schema under `crystal_db/schemas/*.schema.json`.
- Current schema versions:
  - `text_search.v1`
  - `agent.v1`
  - `novelty_check.v1`
  - `csp_pack.v1`
  - `bench_retrieval.v1`
  - `backend_status.v1`

## Python API (Library Surface)

Module: `crystal_db.api`

### `retrieve_text(...) -> text_search.v1`
- Primary use: semantic retrieval over text embeddings.
- Core inputs: `db_path`, `query`, `k`, `embed_engine`, `model`, `model_version`, `text_engine`, `text_view`, `hybrid`, `w_text`, `w_fp`, `redacted`, `show_text_top`, `demo_export`.
- Contract: returns schema-validated payload with neighbors and structured `errors`.

### `make_csp_pack(...) -> csp_pack.v1`
- Primary use: CSP-facing retrieval bundle (hints, exemplars, optional CIF export).
- Core inputs: `db_path`, one of `query` or `structure_id`, plus retrieval settings, `out_dir`, `export_top`, `redacted`, `demo_export`.
- Contract: returns schema-validated payload preserving policy/export gating.

### `novelty_check(...) -> novelty_check.v1`
- Primary use: novelty decision for structure ID or CIF.
- Core inputs: `db_path`, one of `structure_id` or `cif_path`, retrieval/model settings, thresholds, `force`.
- Contract: returns schema-validated novelty payload with structured `errors`.

### `bench_retrieval(...) -> bench_retrieval.v1`
- Primary use: evaluate retrieval quality on JSONL benchmark cases.
- Core inputs: `db_path`, `cases_path`, retrieval settings, `redacted`, `out_dir`.
- Contract: returns schema-validated benchmark summary.

### `agent(...) -> agent.v1`
- Primary use: deterministic agent answer with evidence.
- Core inputs: `db_path`, `question`, `llm`, `run_name`.
- Contract: returns schema-validated payload. Empty question returns `errors.code=invalid_input`.

### `backend_status(...) -> backend_status.v1`
- Primary use: inspect CrystalDB backend readiness for a retrieval surface without running retrieval.
- Core inputs: `db_path`, `surface`, retrieval settings, optional `structure_id`.
- Contract: returns schema-validated readiness payload with DB path, schema/corpus counts, requested embedding space counts, and fingerprint-index state.

## MCP API (Tool Surface)

Server:
- Name: `crystal-db-mcp`
- Version: `1.0.0`
- Transport: stdio JSON-RPC (MCP-compatible)
- Entrypoint: `python -m mcp_server.server`

Exposed tool names:
- `crystal.text_search`
- `crystal.agent`
- `crystal.novelty_check`
- `crystal.csp_pack`
- `crystal.status`
- `crystal.bench_retrieval`

Tool-to-wrapper mapping:
- `crystal.text_search` -> `crystal_db.api.retrieve_text(...)`
- `crystal.agent` -> `crystal_db.api.agent(...)`
- `crystal.novelty_check` -> `crystal_db.api.novelty_check(...)`
- `crystal.csp_pack` -> `crystal_db.api.make_csp_pack(...)`
- `crystal.status` -> `crystal_db.api.backend_status(...)`
- `crystal.bench_retrieval` -> `crystal_db.api.bench_retrieval(...)`

Input aliases supported by MCP:
- `query` also accepted as `text` (where applicable)
- `structure_id` also accepted as `id`
- `cif_path` also accepted as `cif`
- `cases_path` also accepted as `cases`
- `out_dir` also accepted as `out`

## Environment and Defaults (MCP)

- `CRYSTALDB_PATH`: default `db_path` when omitted.
- `CRYSTALDB_CONFIG`: default retrieval config path (default: `configs/retrieval_defaults.json`).
- `CRYSTALDB_POLICY_MODE`: `safe` or `demo` (default: `safe`).
- Embedding backend env vars are passed through (`CRYSTALDB_EMBED_BASE_URL`, `CRYSTALDB_EMBED_API_KEY`, `CRYSTALDB_EMBED_TIMEOUT_S`).
- Relative MCP paths are resolved against the Crystal-DB repo root.

## Policy and Error Semantics

- CIF export is only allowed per item when:
  - provenance `allow_export=1`, or
  - `demo_export=true` and `CRYSTALDB_POLICY_MODE=demo`.
- If policy mode is not `demo`, MCP forces `demo_export=false`.
- If `redacted=true`, policy-redacted raw text is not emitted.

Hard failures (top-level) include codes like:
- `candidate_set_empty`
- `empty_corpus`
- `missing_embedding_space`
- `missing_index`
- `missing_db`
- `db_schema_missing`
- `query_tool_mismatch`

Behavior:
- Payload always includes structured `errors`.
- Retrieval payloads now also include top-level `status` and `backend_status`.
- For MCP `tools/call`, hard failures are returned as JSON-RPC `error` with payload under `error.data.payload`.
- Non-hard/per-item failures remain inside successful tool responses.
