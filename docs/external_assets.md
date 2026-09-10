# External asset contract

No production scientific asset is downloaded automatically.

## Crystal-DB

| Asset | Status | Contract |
| --- | --- | --- |
| SQLite corpus/index | User supplied | Must contain the expected schema, text documents, embeddings, provenance, and exportable CIF records. |
| BGE-M3 embedding model | User supplied | Query vectors must use the same engine, model, version, and dimension as the stored index. |
| LM Studio-compatible endpoint | User supplied | Defaults to http://127.0.0.1:1234/v1 and must expose the configured embedding model. |
| Offline retrieval fixture | Bundled in code | Synthetic SrTiO3 evidence used only by llm-csp demo. |

An embedding identity or dimension mismatch is an incompatibility; retrieval
must stop before similarity calculation. Missing production data is reported
as backend unavailable. Crystal-DB currently opens its configured database in
read/write-create mode, so production users must point it at an intentional
database path.

## SPP

The six SrTiO3 regulator POT files needed by the offline demo are bundled.
Production chemistry requires a separate broad regulator/source POT root.
Every unordered elemental pair derived from the target formula must exist and
pass the POT quality audit. Missing or invalid pairs block QLIP.

Supply the root in workflow configuration (highest precedence) or through
SPP_SOURCE_POT_ROOT. No broad corpus is bundled or downloaded.

## QLIP

QLIP chemistry JSON, schemas, and the six demo POTs are bundled. Each request
must provide a finite explicit design space. Solving requires gurobipy, the
Gurobi native runtime, and a usable licence. There is no fallback solver.
Optional NASICON/scaffold corpora and generated motif catalogs are user-supplied
through explicit arguments (or QLIP_SCAFFOLD_CORPUS_ROOT for scaffold data);
sibling repositories are never discovered.

## Validation

The supported backend is SCA commit
e5b291312151f34949a5e6ef0f43bebfeb752bc9, installed by the validation extra.
SCA is not bundled in the wheel. ALIGNN is optional, its weights/runtime are
not bundled, and it is not used by the canonical validation path. With SCA
absent, llm_csp.validation still imports and returns a structured
backend_unavailable result; a generated candidate is preserved.

## Supported environment variables

| Name | Owner | Required | Default / precedence | Purpose |
| --- | --- | --- | --- | --- |
| CRYSTAL_DB_DATA_ROOT | Crystal-DB | No | Current-directory .crystal_db; below explicit paths | Base for relative DB paths |
| CRYSTAL_DB_PATH | Crystal-DB | Production unless config path supplied | Below explicit db_path; above CRYSTALDB_PATH | SQLite/index path |
| CRYSTALDB_PATH | Crystal-DB | No | Legacy alias, lowest DB-path precedence | SQLite/index path |
| CRYSTALDB_EMBED_BASE_URL | Crystal-DB | LM Studio mode | http://127.0.0.1:1234/v1 | OpenAI-compatible embedding base URL |
| CRYSTALDB_EMBED_API_KEY | Crystal-DB | Endpoint-dependent | lm-studio | Endpoint bearer value; do not commit real secrets |
| CRYSTALDB_EMBED_TIMEOUT_S | Crystal-DB | No | 60 | Request timeout |
| CRYSTALDB_EMBED_BATCH | Crystal-DB | No | 64 | Embedding batch limit |
| CRYSTALDB_EMBED_RETRIES | Crystal-DB | No | 3 | Retry count |
| CRYSTALDB_EMBED_BACKOFF_S | Crystal-DB | No | 0.5 | Retry backoff |
| CRYSTALDB_EMBED_MAX_CTX_TOKENS | Crystal-DB | No | 4096 | Context limit |
| CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS | Crystal-DB | No | 128 | Chunk overlap |
| CRYSTALDB_EMBED_MAX_ITEMS_PER_REQUEST | Crystal-DB | No | 8 | Endpoint item cap |
| CRYSTALDB_EMBED_MAX_TOTAL_TOKENS_PER_REQUEST | Crystal-DB | No | 12000 | Endpoint token cap |
| CRYSTALDB_EMBED_CHUNKING | Crystal-DB | No | true | Long-document chunking |
| SPP_SOURCE_POT_ROOT | SPP | Production unless config root supplied | Below explicit regulator_root | Broad POT root |
| QLIP_SOLVER | QLIP standalone | No | gurobi | Solver selector; integrated workflow accepts only gurobi |
| QLIP_BASE_DATA_DIR | QLIP standalone | No | Bundled base chemistry | Explicit chemistry-data override |
| QLIP_SPP_POT_DIR | QLIP standalone | No | Request context, then bundled demo POTs | Primary POT root |
| QLIP_SPP_REGULARISATION_DIR | QLIP standalone | No | Request context | Regulator POT root; REGULARIZATION spelling is a supported alias |
| QLIP_SCAFFOLD_CORPUS_ROOT | QLIP scaffold registry | Optional | None | Explicit external scaffold corpus |

Debug, MCP policy, path-sandbox, and diagnostic dump variables are internal
implementation controls and are not part of the first-release user contract.
