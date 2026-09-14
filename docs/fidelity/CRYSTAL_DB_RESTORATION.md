# Crystal-DB Software Restoration

## Authority and scope

- Scientific source: `e33d5cc55be01f800a7cf055cc1793d982deb5bc`
- Later licensing revision: `f8b087896eb5a5b3a8ea6d0fffcf53e927d93f31`
- Destination: `packages/crystal_db/`
- Production assets: deferred to Ticket 25

The source was read through the frozen Git object, not copied from an
uncommitted source worktree. `CRYSTAL_DB_SOURCE_MANIFEST.csv` records all 248
tracked source files and hashes. Of the 60 runtime package/MCP files, 57 are
source-identical after newline normalization. Only `crystal_db/db.py`,
`crystal_db/policy.py`, and `mcp_server/server.py` contain documented
repository-layout changes.

## Restored software surface

The original `crystal_db` namespace now includes database/schema management,
ingestion, folder/CIF handling, query/get, descriptions, fingerprints,
similarity, CrystalCard, text generation/indexing, sequence encoding/indexing,
structure retrieval, text/sequence/structure/hybrid search, query caching,
CSP-pack creation, novelty and rediscovery checks, readiness, policy,
provenance, run/audit logging, candidate proposal, snapshots, exports,
reporting, calibration, gates, evaluation/benchmarks, family/ordered-family
classification and validation, and the Phase 2 agent.

All 11 operational JSON schemas were restored. Source scripts, tests,
benchmark fixtures, gold fixtures, demo CIFs, policies and configuration were
retained. Generated paper/report outputs and prebuilt production data were not
copied.

## Database and provenance behavior

The source SQLite schema and incremental `_ensure_columns` behavior are
unchanged. Tables preserve structure/CIF, metadata, descriptors,
fingerprints, text documents/embeddings, sequence representations,
provenance, runs, audit/tool records, candidates, indexes and calibration
metadata. No ORM, schema, ID, hash, canonicalization, ranking, similarity or
novelty algorithm was introduced or changed.

## CLI

`python -m crystal_db` preserves these source commands:

`ingest`, `ingest-folder`, `query`, `get`, `describe`, `fingerprint`,
`similar`, `agent`, `audit`, `novelty`, `novelty-check`, `bench`, `export-run`,
`report-run`, `snapshot`, `propose`, `report`, `calibrate-novelty`,
`cases-normalize`, `cases-sample`, `calibrate-retrieval`, `gate-retrieval`,
`gen-text`, `embed-text`, `similar-text`, `text-search`, `csp-pack`,
`bench-retrieval`, `similar-struct`, `encode-seq`, `embed-seq`, `similar-seq`,
`similar-hybrid`, and `crystalcard`.

The `crystal-db` console entry point delegates to that unchanged CLI.

## MCP

The original `mcp_server.server` stdio implementation and exact registry were
restored:

- `crystal.text_search`
- `crystal.agent`
- `crystal.novelty_check`
- `crystal.csp_pack`
- `crystal.status`
- `crystal.bench_retrieval`

It uses FastMCP when installed and retains the JSON-RPC stdio fallback. There
are no source MCP resources or prompts. Full input/output schemas are recorded
in `crystal_db_mcp_surface.json`. `crystal_db.mcp.server` is a compatibility
alias and does not maintain a second implementation.

## Configuration and dependencies

Preserved source configuration:

| Variable | Source default/meaning |
|---|---|
| `CRYSTAL_DB_PATH`, `CRYSTALDB_PATH` | Explicit SQLite path; first name takes precedence in the database API |
| `CRYSTALDB_CONFIG` | MCP retrieval configuration path |
| `CRYSTALDB_POLICY_MODE` | `safe`; `demo` permits requested demo export |
| `CRYSTALDB_EMBED_BASE_URL` | `http://127.0.0.1:1234/v1` |
| `CRYSTALDB_EMBED_API_KEY` | `lm-studio` |
| `CRYSTALDB_EMBED_TIMEOUT_S` | `60` in embedding code |
| `CRYSTALDB_EMBED_BATCH` | `64` |
| `CRYSTALDB_EMBED_RETRIES` | `3` |
| `CRYSTALDB_EMBED_BACKOFF_S` | `0.5` |
| `CRYSTALDB_EMBED_MAX_CTX_TOKENS` | `4096` |
| `CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS` | `128` |
| `CRYSTALDB_EMBED_MAX_ITEMS_PER_REQUEST` | `8` |
| `CRYSTALDB_EMBED_MAX_TOTAL_TOKENS_PER_REQUEST` | `12000` |
| `CRYSTALDB_EMBED_CHUNKING` | `true` |
| `MP_API_KEY`, `MP-API-KEY`, `MATERIALS_PROJECT_API_KEY` | Optional acquisition scripts |

`CRYSTAL_DB_DATA_ROOT` is retained only as the v0.1 compatibility setting.
Core package dependencies are `pymatgen` and `monty`; MCP and schema support
remain optional extras. Matplotlib reporting and MP/RoboCrys acquisition are
optional extras. LM Studio is an external embedding service and is not merged
with the later Skill-Loop reasoning runtime.

## Layout-only changes

1. Default database paths moved from the Crystal-DB repository `data/` folder
   to unified `data/crystal_db/`.
2. The MCP default config resolves to the packaged
   `packages/crystal_db/configs/retrieval_defaults.json`.
3. The default policy file is package data at
   `crystal_db/configs/policies.yaml`, so installed ingestion is independent of
   the process working directory.
4. The NASICON source test's sibling Skill-Loop reference was copied exactly
   to `tests/fixtures/nasicon/reference.cif` (SHA-256
   `5f1b7b14e6c1abf3a209c8d9557948ac67282de47283f4af2ee409e23ca228b8`).
5. `crystal_db.mcp.server` delegates to the restored source MCP namespace for
   v0.1 import compatibility.

## Deferred assets and minimum operational dataset

The canonical Skill-Loop retrieval path requires:

- `phase6_mp_10k.db`, containing schema, structures/CIF text, metadata,
  provenance, text documents/embeddings, fingerprints and index identity;
- the corresponding `mp_stable_10k` CIF corpus for rebuild/export provenance;
- compatible BGE-M3 embedding/model-version metadata;
- query/vector caches only for performance, not semantic completeness.

Specialist databases, calibration outputs, benchmark cases and report trees
are workflow-specific. The 36-row `CRYSTAL_DB_ASSET_MANIFEST.csv` records
content/tree hashes and dispositions. Nothing from the production snapshot was
copied in this ticket.

## Tests and parity

The migrated unchanged source suite passes 175 tests with one explicit skip:
the skipped test requires the deferred local `phase6_mp_10k.db`. The Ticket 22
baseline of 176 passes had that production database available in the sibling
source worktree. Assertions were not weakened.

Representative source-vs-archive probes cover canonicalization/hashing,
database query, fingerprint/similarity, text retrieval, CSP pack, novelty,
readiness and MCP contracts. Results and commands are recorded in
`evidence/CRYSTAL_DB_PARITY_RESULTS.json`.

The final package was built as both sdist and wheel. In a clean environment,
the non-editable wheel resolved `crystal_db` and `mcp_server` exclusively from
`site-packages`, contained all operational schemas and packaged policies,
exposed the full CLI, discovered all six MCP tools, and passed the migrated
suite with 175 passed and one production-snapshot skip. The whole unified
archive passed with 344 tests and seven explicit skips.

## Scientific behavior statement

`NO_SCIENTIFIC_BEHAVIOR_CHANGE`
