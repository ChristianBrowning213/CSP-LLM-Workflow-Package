# Crystal-DB Operational Asset Audit

## Decision

Ticket 25 identified the exact operational snapshot but did not copy it. The
required database is derived from Materials Project API/CIF records and the
repository contains no human approval granting redistribution in this public
archive. The database's own policy rows prohibit export. The mandatory hard
gate therefore yields `CRYSTAL_DB_BLOCKED_PROVENANCE`.

This is not a decision to externalize or replace the data. No synthetic corpus,
network downloader, schema migration, regenerated embedding, or alternate
retrieval implementation was introduced.

## Canonical database proof

The canonical general database is:

| Property | Value |
|---|---|
| Source path | `Crystal-DB/data/phase6_mp_10k.db` |
| Size | 881,799,168 bytes |
| SHA-256 | `572448fbcb7716d315246f24dd427064715fd56839d0b4450cc6a8231a0e5dc0` |
| SQLite integrity | `ok` |
| SQLite `user_version` | `0` (the source has no separate numeric schema version) |
| Schema hash | `3eb48d373761368d22b572178cc478f10d49266bf3133448502cf7f40eced58c` |
| Tables / indexes | 24 operational tables / 56 indexes |
| Foreign-key check | zero violations |

This selection is not based on file size. At the scientific revision,
`mcp_server.server.DEFAULT_DB_PATH` points to `data/phase6_mp_10k.db`.
Skill-Loop invokes `crystal.csp_pack` without a database override and therefore
uses that server default. Its production/audit scripts independently name the
same file as the general Crystal-DB and the production BGE-M3/RoboCrys corpus.
Historical rows in the database also contain the original Skill-Loop Crystal
tool calls.

Principal row counts are:

| State | Count |
|---|---:|
| Structures / metadata / provenance | 10,000 each |
| Embedded CIFs | 10,000 |
| Descriptors / fingerprints | 10,000 each |
| Structure embeddings | 10,293 |
| Structure texts | 9,992 |
| Text documents / embeddings | 12,000 / 10,024 |
| Query embeddings | 200 |
| Runs / run steps / tool calls | 3,179 / 30,494 / 23,715 |

The persisted text space is LM Studio `text-embedding-bge-m3`, version
`lmstudio_v1`, dimension 1024. The complete per-table inventory, schema,
indexes, integrity results and provenance summaries for all 20 candidate
SQLite databases are in
`evidence/CRYSTAL_DB_DATABASE_INVENTORY.json`.

## Runtime dependency trace

The database embeds every canonical CIF and all metadata, descriptions,
fingerprints and retrieval vectors used by stored-data operations. Real-data
probes showed that query, precomputed-vector text search, ID-mode CSP-pack,
ID-mode novelty and readiness use the SQLite file plus packaged schemas and
policies. They do not dereference `mp_stable_10k` or `cache_mp_10k`.

The database contains old absolute Skill-Loop output paths in candidate/run
audit state. They are historical provenance and proposed-input records, not
paths opened by retrieval. The bytes were not edited.

The minimum operational asset set is therefore the single byte-exact database.
The raw `mp_stable_10k` corpus is useful for acquisition/reconstruction
provenance, but is not required to run the persisted snapshot. The acquisition
cache is regenerable and is not runtime state.

## Provenance and redistribution

All 10,000 provenance rows have:

- source `mp`;
- retrieval timestamps from `2026-02-13T13:01:38Z` through
  `2026-02-13T13:01:48Z`;
- policy `local_cif`;
- `license_notes = "local CIF; check source license before export"`;
- `allow_export = 0`.

The database combines raw CIF text and API-derived metadata with project-
generated descriptions, fingerprints, embeddings, query cache and audit
state. Project authorship of the software and derived calculations does not
establish permission to redistribute the underlying Materials Project records.
The recovery plan also explicitly requires a human redistribution decision.

Consequently:

- `phase6_mp_10k.db`: `REQUIRED_BUT_PROVENANCE_BLOCKED`;
- `mp_stable_10k`: `THIRD_PARTY_REVIEW`, not runtime-required;
- `cache_mp_10k`: `CACHE_ONLY`, not selected;
- specialist Materials Project-derived databases: `BENCHMARK_ONLY`, not
  selected and not implicitly cleared.

## Excluded holdings

The 36-row asset manifest classifies 23 benchmark-only entries, six generated
output entries, four stale/temporary entries, one cache, one optional
third-party corpus, and the one blocked required database. The approximately
802 MB artifact tree consists of generated reports, plots, paper/evaluation
outputs and specialist database products; it is not a default runtime index.
No portion was copied merely because it was locally present.

## Storage and reconstruction

No storage transformation was selected because provenance approval must
precede packaging. The raw database, compressed form, chunks, materialized
duplicate and CIF corpus are all absent from the archive. There is therefore no
materializer, network dependency, `.gitignore` change or wheel payload change.

If a human later clears the exact database, a later ticket may deterministically
compress/chunk it below 95 MiB per tracked object and reconstruct it only after
verifying the source SHA-256. That future action is not authorized here.

## Real-data parity and offline behavior

Two temporary copies initially matched the source SHA-256. The frozen source
code and restored archive code returned identical IDs, ordering and scores for
a persisted-vector text search, ID-mode CSP-pack and novelty check. Readiness
was `backend_ready` on both. Exact results are recorded in
`evidence/CRYSTAL_DB_REAL_DATA_PARITY.json`.

Archive CLI and MCP probes against a temporary copy passed for query, ID-mode
CSP-pack, ID-mode novelty and status. With LM Studio deliberately unavailable,
free-text CLI/MCP search correctly reported `query_embedding_failed` while
still reporting the persisted backend as ready. Persisted representations can
be read offline, but arbitrary new text queries genuinely require the external
BGE-M3 embedding endpoint.

These are compatibility probes, not an archive-contained snapshot test. A
fresh tracked-only clone remains unable to materialize the canonical database,
because including its bytes without approval would violate the hard gate.

## Repository-size impact

At Ticket 25 start the tracked working-tree blobs totalled 6,968,387 bytes.
After the audit commit they total 7,248,537 bytes, an increase of 280,150 bytes.
The required materialized runtime would be 881,799,168 bytes, but zero runtime
asset bytes and zero compressed/chunk bytes were added. The increase consists
only of audit manifests, evidence and this report.

## Remaining action

A human must explicitly approve or reject redistribution of the exact
Materials Project-derived database snapshot. Until then the software remains
restored, the canonical asset gap is named and hash-pinned, and overall
Crystal-DB recovery is provenance-blocked.
