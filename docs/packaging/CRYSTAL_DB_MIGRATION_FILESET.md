# Crystal-DB migration fileset

This pre-copy fileset was derived from the Ticket 2 manifest and import graph.
Authoritative source: `C:\Users\brown\Documents\GitHub\Crystal-DB`, branch
`mcp`, commit `e33d5cc55be01f800a7cf055cc1793d982deb5bc`, clean before copying.

## Core database

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/__init__.py` | `packages/crystal_db/src/crystal_db/__init__.py` | Package boundary, narrowed to supported exports. |
| `crystal_db/db.py` | `packages/crystal_db/src/crystal_db/db.py` | SQLite schema, connection, and portable path resolution. |
| `crystal_db/utils.py` | `packages/crystal_db/src/crystal_db/utils.py` | Shared parsing, hashes, and timestamps. |

## Schema/models

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/schema_validate.py` | `packages/crystal_db/src/crystal_db/schema_validate.py` | Response contract validation. |
| `crystal_db/schemas/text_search.v1.schema.json` | `packages/crystal_db/src/crystal_db/schemas/text_search.v1.schema.json` | Retrieval response schema. |
| `crystal_db/schemas/csp_pack.v1.schema.json` | `packages/crystal_db/src/crystal_db/schemas/csp_pack.v1.schema.json` | CSP-pack response schema. |
| `crystal_db/schemas/backend_status.v1.schema.json` | `packages/crystal_db/src/crystal_db/schemas/backend_status.v1.schema.json` | Readiness response schema. |

## Retrieval

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/api.py` | `packages/crystal_db/src/crystal_db/api.py` | Split to retrieval, CSP-pack, and status wrappers only. |
| `crystal_db/readiness.py` | `packages/crystal_db/src/crystal_db/readiness.py` | Truthful database/corpus/index diagnostics. |

## Text retrieval

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/retrieval.py` | `packages/crystal_db/src/crystal_db/retrieval.py` | Canonical `text_search`, unchanged ranking and policy behavior. |

## Embedding interface

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/embeddings.py` | `packages/crystal_db/src/crystal_db/embeddings.py` | OpenAI-compatible LM Studio client and deterministic test backend. |

## Similarity/index code

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/similarity.py` | `packages/crystal_db/src/crystal_db/similarity.py` | Hybrid structure similarity. |
| `crystal_db/sequence_index.py` | `packages/crystal_db/src/crystal_db/sequence_index.py` | CIF canonicalization imported by retrieval. |

## Structure/CIF access

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/csp_pack.py` | `packages/crystal_db/src/crystal_db/csp_pack.py` | Downstream evidence bundles and authorized CIF export. |

## Descriptors/fingerprints

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/fingerprint.py` | `packages/crystal_db/src/crystal_db/fingerprint.py` | Hybrid fingerprint calculation and identity. |

## Provenance/policy

| Source | Destination | Evidence |
| --- | --- | --- |
| `crystal_db/audit_log.py` | `packages/crystal_db/src/crystal_db/audit_log.py` | Transitive sequence-index audit provenance; source name retained. |
| `crystal_db/runlog.py` | `packages/crystal_db/src/crystal_db/runlog.py` | CSP-pack run/evidence provenance. |

Policy flags and source/source-ID fields remain in `db.py`, `retrieval.py`, and
`csp_pack.py`; `policy.py` is ingestion-only and is not on the supported graph.

## Configuration

| Source | Destination | Evidence |
| --- | --- | --- |
| `configs/retrieval_defaults.json` | `packages/crystal_db/src/crystal_db/configs/retrieval_defaults.json` | Packaged safe BGE-M3 defaults. |
| same sanitized values | `configs/crystal_db.default.json` | User-facing example without a machine path. |
| `mcp_server/server.py` | `packages/crystal_db/src/crystal_db/mcp/server.py` | Split MCP facade for retrieval, CSP-pack, and status. |
| package marker (new) | `packages/crystal_db/src/crystal_db/mcp/__init__.py` | Installed MCP namespace. |

## Tests

| Manifest source | Destination/adaptation |
| --- | --- |
| `tests/test_text_search.py` | `tests/unit/crystal_db/test_text_search.py` (direct API; mixed source CLI cases omitted) |
| `tests/test_text_search_reports_missing_db_or_empty_corpus_truthfully.py` | `tests/unit/crystal_db/test_readiness.py` |
| `tests/test_distinct_queries_return_nonempty_results_when_backend_seeded.py` | `tests/integration/crystal_db/test_retrieval.py` |
| `tests/test_csp_pack.py` | `tests/integration/crystal_db/test_csp_pack.py` (direct API; reporting/mixed CLI cases omitted) |
| `tests/test_csp_pack_semantic_chemistry_selection.py` | `tests/integration/crystal_db/test_chemistry_selection.py` |
| `tests/test_mcp_server.py` | `tests/integration/crystal_db/test_mcp.py` (supported three-tool facade) |

All destination tests build temporary SQLite databases with synthetic records.

## Examples

| Manifest source | Destination/resolution |
| --- | --- |
| `tests/fixtures/crystaldb_retrieval/` | Not copied: redistribution provenance was unresolved; replaced by synthetic records built in tests. |
| installed API example (new) | `examples/crystal_db/retrieval.py` |

## Explicit exclusions

- `data/`, `artifacts/`, `benchmarks/`, `tmp/`, `test_workdir/`, databases,
  corpora, stored embeddings, model files, and generated reports
- source demo CIFs whose identifiers do not establish redistribution permission
- benchmark, calibration, gate, paper, agent, novelty, ingestion, corpus-build,
  report, and mixed CLI modules
- sibling-repository loaders and repository-root data defaults

The CSV's original classifications remain historical inventory; Ticket 5 only
adds resolution notes.
