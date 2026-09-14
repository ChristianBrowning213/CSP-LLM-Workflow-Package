# REPO_EXPLAINED (Crystal-DB)

## What This Repo Is

Crystal-DB is a deterministic, policy-aware structure retrieval database for crystallography and CSP workflows. It stores CIFs plus provenance and licensing rules, computes descriptors and fingerprints, supports similarity and novelty checks, and logs tool usage for auditability. Phase 4 adds candidate workflows and reporting for CSP runs, and Phase 5 adds crystallographer-grade semantics via CrystalCard.

## Core Concepts Glossary

- `structure_id`: Stable ID for a structure record in the DB.
- `provenance`: Source metadata (source, source_id, retrieved_at, license/policy flags).
- `policy`: Rules that control CIF storage, return, derivatives, and export.
- `fingerprint`: Vector summary of a structure for similarity/novelty.
- `similarity`: kNN over fingerprints with feature-delta explanations.
- `novelty`: Decision based on best-match distance vs threshold.
- `run_id`: Audit run ID; groups tool calls, evidence, and reports.
- `candidate_id`: Proposed CSP candidate identifier linked to run_id.

## Folder Map

- `crystal_db/__main__.py`: CLI entrypoint for all commands.
- `crystal_db/db.py`: SQLite schema and connection utilities.
- `crystal_db/query.py`: Query and get operations.
- `crystal_db/describe.py`: Text descriptors from metadata.
- `crystal_db/fingerprint.py`: Deterministic fingerprint generator.
- `crystal_db/similarity.py`: kNN similarity with why deltas.
- `crystal_db/novelty.py`: Novelty checks with timings.
- `crystal_db/agent.py`: Phase 2 agent runner + evidence.
- `crystal_db/audit_log.py`: Tool-call logging and audit fetch.
- `crystal_db/policy.py`: Policy parsing + enforcement helpers.
- `crystal_db/ingest.py`: Synthetic ingest.
- `crystal_db/ingest_folder.py`: Folder ingest (Phase 3).
- `crystal_db/bench.py`: Benchmarks.
- `crystal_db/export_run.py`: Export run bundle with redaction.
- `crystal_db/snapshot.py`: Snapshot DB and manifests.
- `crystal_db/propose.py`: Phase 4 candidate registration.
- `crystal_db/report.py`: Phase 4 report generation.
- `crystal_db/calibrate.py`: Novelty calibration harness.
- `crystal_db/crystalcard.py`: Phase 5 CrystalCard semantics builder.
- `crystal_db/embeddings.py`: Deterministic embedding backend (hash stub).
- `crystal_db/textgen.py`: Text generation engines (baseline/robocrys/caption).
- `crystal_db/text_index.py`: Text embedding index builder.
- `crystal_db/sequence_index.py`: Sequence encoder + embeddings.
- `crystal_db/retrieval.py`: Multi-index retrieval (text/seq/struct/hybrid).
- `crystal_db/schemas/`: JSON schemas (CrystalCard v1).
- `docs/REPO_EXPLAINED.md`: This document.
- `docs/PHASE_CHANGELOG.md`: Phase-by-phase summary.
- `data/gold/`: Synthetic gold CIFs + expectations for semantics regression tests.
- `EVAL_PROTOCOL.md`: Evaluation protocol for Phase 4.

## CLI Map

- `python -m crystal_db ingest --db <db> --count 100`: ingest synthetic data.
- `python -m crystal_db ingest-folder --db <db> --path <dir> --source local_cif --policy local_cif`: ingest CIFs.
- `python -m crystal_db query --db <db> --filter '<json>'`: query structures.
- `python -m crystal_db get --db <db> --id <structure_id>`: fetch a structure.
- `python -m crystal_db describe --db <db> --id <structure_id>`: descriptor.
- `python -m crystal_db fingerprint --db <db> --id <structure_id>`: fingerprint.
- `python -m crystal_db similar --db <db> --id <structure_id> --k 5`: similarity search.
- `python -m crystal_db novelty --db <db> --cif <path> --threshold 25.0 --k 5`: novelty check.
- `python -m crystal_db agent --db <db> --query "..." --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1`: Phase 2 tool-only agent with evidence bundles.
- `python -m crystal_db audit --db <db> --run-id <run_id>`: audit bundle.
- `python -m crystal_db report-run --db <db> --run-id <run_id>`: Phase 2 run report (run header, steps, evidence, explored/proposed).
- `python -m crystal_db novelty-check --db <db> --id <structure_id> --k 5 --text-sim-threshold 0.80 --fp-sim-threshold 0.95`: Phase 2 novelty checker.
- `python -m crystal_db bench --db <db> --iters 20 --k 5`: benchmarks.
- `python -m crystal_db export-run --db <db> --run-id <run_id> --out runs\<run_id>.json`: export.
- `python -m crystal_db snapshot --db <db> --out snapshots`: snapshot.
- `python -m crystal_db propose --db <db> --run-name <name> --candidates <path>`: register CSP candidates.
- `python -m crystal_db report --db <db> --run-id <run_id> --out reports\<run_id>`: run report.
- `python -m crystal_db calibrate-novelty --db <db> --k 10 --out reports\calibration_YYYYMMDD`: calibration.
- `python -m crystal_db crystalcard --db <db> --id <structure_id>`: CrystalCard semantics.
- `python -m crystal_db gen-text --db <db> --engine caption --text-view caption --limit 100 --shard-count 1 --shard-index 0`: generate caption view text (deterministic structure_id order + optional sharding).
- `python -m crystal_db embed-text --db <db> --text-engine caption --text-view caption --engine hash --model hash-embed --model-version v1 --limit 100 --shard-count 1 --shard-index 0`: caption-view text embeddings with aligned sharding.
- `python -m crystal_db similar-text --db <db> --id <structure_id> --k 10 --engine hash --model hash-embed --model-version v1`: text similarity in one embedding space.
- `python -m crystal_db text-search --db <db> --query "lithium oxide layered cathode" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine robocrys --text-view robocrys`: free-text nearest-neighbor search.
- `python -m crystal_db text-search --db <db> --query "layered van der Waals 2D material exfoliable" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3`: caption-space + hybrid reranking.
- `python -m crystal_db csp-pack --db <db> --query "layered van der Waals 2D material" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3 --out out\csp_pack --export-top 5 --redacted true --demo-export false`: CSP-facing retrieval pack with hints + bundle export.
- `python -m crystal_db bench-retrieval --db <db> --cases benchmarks\retrieval\tiny_fixture.jsonl --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3 --redacted true --out out\bench_retrieval`: retrieval quality benchmark harness.
- `python -m crystal_db cases-normalize --in benchmarks\retrieval\phase6_small.jsonl --out data\phase6_cases_norm.jsonl`: normalize/dedupe benchmark cases with stable ordering.
- `python -m crystal_db cases-sample --db <db> --out data\phase6_cases_sampled.jsonl --n 50 --text-engine caption --text-view caption --label-mode none`: deterministic case sampling from DB.
- `python -m crystal_db cases-sample --db <db> --out data\phase6_cases_labeled.jsonl --n 50 --text-engine caption --text-view caption --label-mode self`: deterministic self-labeling (`expected_structure_ids=[provenance.structure_id]`) for immediate benchmark scoring.
- `python -m crystal_db calibrate-retrieval --db <db> --cases data\phase6_cases_norm.jsonl --k 10 --out data\calibration_out --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --preembed-queries true`: sweep thresholds/weights and choose best config (`w_fp` is always computed as `1 - w_text`).
- `python -m crystal_db gate-retrieval --db <db> --cases data\phase6_cases_norm.jsonl --k 10 --out data\gate_out --min-hit-at-k 0.10 --min-ndcg-at-k 0.05`: fail CI gate when retrieval regresses.
- `python -m crystal_db encode-seq --db <db> --format cif_canon --all`: sequence encoding.
- `python -m crystal_db embed-seq --db <db> --format cif_canon --model hash-embed --all`: sequence embeddings.
- `python -m crystal_db similar-seq --db <db> --id <structure_id> --k 10`: sequence similarity.
- `python -m crystal_db similar-struct --db <db> --id <structure_id> --k 10`: structure similarity (fingerprint).
- `python -m crystal_db similar-hybrid --db <db> --id <structure_id> --k 10 --sources text,struct,seq`: hybrid fusion.

## DB Schema Overview

- `structures`: CIF text + basic structure fields.
- `metadata`: formula, elements, space group, band gap.
- `provenance`: source and policy flags.
- `structure_descriptors`: descriptor text and features.
- `structure_fingerprints`: fingerprint vectors.
- `structure_crystalcards`: CrystalCard semantics (engine + version).
- `structure_texts`: generated text descriptions (engine + version).
- `text_docs`: canonical staged text documents by `(structure_id, engine, text_view)` with engine versioning.
- `text_embeddings`: canonical text vectors by `(text_doc_id, embed_engine, model, model_version)`.
- `query_embeddings`: cached benchmark query vectors by `(query_sha256, embed_engine, model, model_version)` for calibration reuse/resume.
- `structure_sequences`: canonical sequences (format + version).
- `structure_embeddings`: embeddings for text/struct/seq modalities.
- `runs`: audit run metadata.
- `run_steps`: per-tool immutable execution log (input/output JSON + hashes + status).
- `evidence_bundles`: retrieval/novelty/answer evidence attached to runs.
- `tool_calls`: tool-call logs.
- `answer_evidence`: agent evidence bundles.
- `explored_structures`: explored structure IDs.
- `proposed_structures`: novelty proposals.
- `novelty_results`: novelty outcomes and timings.
- `candidates`: Phase 4 candidate registration.
- `candidate_results`: novelty + comparators for candidates.


## Embedding Pipelines

Crystal-DB supports three embedding surfaces:
- Text embeddings from structure descriptions (`robocrys`) and intent-aligned captions (`caption`).
- Structure embeddings (fingerprints as indexed vectors).
- Sequence embeddings from canonical CIF token strings.

`similar-text` looks up neighbors only inside one embedding space key:
`(embed_engine, model_name, model_version)`. It reads from `text_docs` + `text_embeddings`; if query or candidates are missing in that space, it exits non-zero with diagnostics and remediation commands.

`text-search` embeds `--query` in the same embedding space and runs cosine search against `text_embeddings` filtered by `--text-engine` and `--text-view`. Optional hybrid mode reranks top text candidates with fingerprint similarity and reports `text_score`, `fp_score`, and `final_score`.

Multi-index retrieval fuses these sources deterministically using weighted reciprocal rank fusion (RRF).

Long text handling (Phase 6):
- `embed-text` now embeds full text docs using internal chunking + pooling when needed.
- Each `text_doc` still stores exactly one final embedding row in `text_embeddings` for each embedding space key.
- Chunking is internal only; retrieval and table contracts are unchanged.
- Pooling uses length-weighted mean over chunk embeddings.

Chunking environment variables:
- `CRYSTALDB_EMBED_MAX_CTX_TOKENS` (default `4096`)
- `CRYSTALDB_EMBED_CHUNK_OVERLAP_TOKENS` (default `128`)
- `CRYSTALDB_EMBED_MAX_ITEMS_PER_REQUEST` (default `8`)
- `CRYSTALDB_EMBED_MAX_TOTAL_TOKENS_PER_REQUEST` (default `12000`)
- `CRYSTALDB_EMBED_CHUNKING` (default `true`)

## Free-Text Demo

Safe mode (no demo export):
- `python -m crystal_db text-search --db data\phase6_mp_10k.db --query "spinel lithium manganese oxide with octahedral framework" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine robocrys --show-text-top 3 --export-cifs data\text_search_exports --export-top 3 --redacted true --format pretty`

Demo mode (explicit override + auto-open with VESTA):
- `python -m crystal_db text-search --db data\phase6_mp_10k.db `
  `--query "spinel lithium manganese oxide with octahedral framework" `
  `--k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 `
  `--text-engine robocrys --show-text-top 3 --export-cifs data\text_search_exports --export-top 3 `
  `--redacted false --demo-export --open-cifs --vesta "C:\Program Files\VESTA\VESTA.exe" --format pretty`

Phase 3 caption + hybrid flow:
- `python -m crystal_db gen-text --db data\phase6_mp_10k.db --engine caption --text-view caption --limit 100 --batch 32 --progress-every 10`
- `python -m crystal_db embed-text --db data\phase6_mp_10k.db --text-engine caption --text-view caption --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --limit 100 --batch 64 --progress-every 10`
- `python -m crystal_db text-search --db data\phase6_mp_10k.db --query "layered van der Waals 2D material exfoliable" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --show-text-top 3 --format pretty`
- `python -m crystal_db text-search --db data\phase6_mp_10k.db --query "layered van der Waals 2D material exfoliable" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3 --show-text-top 3 --format pretty`

Phase 5A scaling helpers (deterministic shards + resumable snapshots):
- `python -m crystal_db gen-text --db data\phase6_mp_10k.db --engine caption --text-view caption --limit 100 --shard-count 4 --shard-index 0 --snapshot data\logs\gen_shard0.json --snapshot-every 50`
- `python -m crystal_db embed-text --db data\phase6_mp_10k.db --text-engine caption --text-view caption --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --limit 100 --shard-count 4 --shard-index 0 --snapshot data\logs\embed_shard0.json --snapshot-every 50`

Phase 6 full-dump RoboCrys embedding (chunk + pool):
- `$env:CRYSTALDB_EMBED_MAX_CTX_TOKENS="4096"`
- `$env:CRYSTALDB_EMBED_CHUNKING="true"`
- `python -m crystal_db embed-text --db data\phase6_mp_10k.db --text-engine robocrys --text-view robocrys --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --batch 8 --progress-every 50`

Show-off comparison (caption space is less random than robocrys in the fixture tests):
- `python -m crystal_db text-search --db data\phase6_mp_10k.db --query "layered van der Waals 2D material exfoliable" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine robocrys --text-view robocrys --format pretty`
- `python -m crystal_db text-search --db data\phase6_mp_10k.db --query "layered van der Waals 2D material exfoliable" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --format pretty`

## CSP Pack

`csp-pack` packages retrieval outputs for downstream CSP solvers:
- retrieved exemplars with scores
- deterministic design hints (family/connectivity/chemistry/symmetry/quantitative clues)
- export bundle (`manifest.json`, `results.json`, and CIFs)
- run logging with retrieval/hints/export steps and evidence.

PowerShell examples:
- `python -m crystal_db csp-pack --db data\phase6_mp_10k.db --query "layered van der Waals 2D material exfoliable" --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3 --out data\csp_pack_query --export-top 5 --redacted true --demo-export false`
- `python -m crystal_db csp-pack --db data\phase6_mp_10k.db --id mp-01aaea59 --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3 --out data\csp_pack_id --export-top 5 --redacted true --demo-export false`

## Retrieval Benchmarks

Benchmark cases live in `benchmarks\retrieval\*.jsonl` (one JSON object per line), e.g.:
- `{"case_id":"perovskite_corner_share_001","query":"perovskite oxide with corner-sharing octahedra","expected":{"must_contain_any":["perovskite","corner-sharing","octahedra"],"family":"perovskite","elements_any":["O"]}}`
- `{"case_id":"sample_mp-123","query":"layered oxide with corner-sharing octahedra","expected_structure_ids":["mp-123"],"expected_formula":"Li2MnO3"}`

Notes:
- `expected_structure_ids` is optional and first-class. When present, benchmark scoring uses binary ID relevance (hit/MRR/NDCG by membership in that ID set).
- `cases-sample --label-mode self` writes `expected_structure_ids` automatically so sampled datasets are immediately benchmarkable.

Run benchmark:
- `python -m crystal_db bench-retrieval --db data\phase6_mp_10k.db --cases benchmarks\retrieval\tiny_fixture.jsonl --k 10 --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text 0.7 --w-fp 0.3 --redacted true --out data\bench_retrieval`

Outputs:
- `summary.json` (same payload as stdout)
- `cases_scored.jsonl` (per-case metrics)
- `summary.csv` (case_id/hit/rr/ndcg/status)

## Phase 6 Quality Gates

Phase 6 adds:
- `cases-normalize`: validates and canonicalizes benchmark JSONL files.
- `cases-sample`: deterministic hash-based sampling from DB to grow benchmark sets, with semantic sentence extraction so sampled queries include structure/motif context instead of raw text prefixes.
- `calibrate-retrieval`: pre-embeds all case queries once, caches per-case candidate packs once, then runs cheap sweep loops (`w_fp = 1 - w_text`) using only cached `text_score`/`fp_score` arithmetic.
- `gate-retrieval`: regression gate with absolute thresholds and optional baseline comparison.
- `--config` support for `bench-retrieval` and `csp-pack` (defaults file such as `benchmarks\retrieval\retrieval_defaults.json`).

PowerShell examples:
- `python -m crystal_db cases-normalize --in benchmarks\retrieval\phase6_small.jsonl --out data\phase6_cases_norm.jsonl`
- `python -m crystal_db cases-sample --db data\phase6_mp_10k.db --out data\phase6_cases_sampled.jsonl --n 100 --text-engine robocrys --text-view robocrys --query-mode semantic --query-min-sentences 2 --query-max-sentences 5 --query-max-chars 700 --label-mode none`
- `python -m crystal_db cases-sample --db data\phase6_mp_10k.db --out data\phase6_cases_labeled.jsonl --n 100 --text-engine robocrys --text-view robocrys --query-mode semantic --query-min-sentences 2 --query-max-sentences 5 --query-max-chars 700 --label-mode self`
- `python -m crystal_db calibrate-retrieval --db data\phase6_mp_10k.db --cases data\phase6_cases_norm.jsonl --k 10 --out data\calibration_out --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text-values 0.5,0.6,0.7 --preembed-queries true`
- `python -m crystal_db calibrate-retrieval --db data\phase6_mp_10k.db --cases data\phase6_cases_labeled.jsonl --k 10 --out data\calibration_out --engine lmstudio --model text-embedding-bge-m3 --model-version lmstudio_v1 --text-engine caption --text-view caption --hybrid true --w-text-values 0.5,0.6,0.7 --max-cases 50 --progress-every 10 --preembed-queries true`
- `python -m crystal_db gate-retrieval --db data\phase6_mp_10k.db --cases data\phase6_cases_norm.jsonl --k 10 --out data\gate_out --min-hit-at-k 0.10 --min-ndcg-at-k 0.05`
- `python -m crystal_db gate-retrieval --db data\phase6_mp_10k.db --cases data\phase6_cases_norm.jsonl --k 10 --out data\gate_out --baseline-summary data\calibration_out\calibration_best.json --baseline-delta 0.01`

## Library API

Crystal-DB now exposes stable importable wrappers in `crystal_db/api.py`:
- `retrieve_text(...)` -> `schema_version: text_search.v1`
- `make_csp_pack(...)` -> `schema_version: csp_pack.v1`
- `novelty_check(...)` -> `schema_version: novelty_check.v1`
- `bench_retrieval(...)` -> `schema_version: bench_retrieval.v1`

All API responses are schema-validated before return using `crystal_db/schema_validate.py`. CLI behavior remains unchanged.

Example import usage:
- `python examples\api_demo.py --db data\phase6_mp_10k.db --query "layered van der Waals 2D material" --k 5 --pack-out data\api_demo_pack`

## Main Workflows

- Ingest → describe/fingerprint → similar
- Propose → novelty → report
- Audit → export-run → snapshot

## Policy and Redaction

Policy enforcement is applied in `query.py`, `get_structure`, `export_run.py`, `report.py`, and audit logging redaction. CIFs marked restricted are not returned in `get` and are redacted in audit bundles and reports. Derived artifacts are allowed only if `allow_derivatives` permits.

## Tests and Benchmarks

- Run tests: `python -m pytest -q`
- Benchmarks: `python -m crystal_db bench --db <db> --iters 20 --k 5`

## Adding a New Engine (Descriptor or Semantics)

1. Add a new engine name and version constant in the relevant module.
2. Implement the engine as a pure function (no network, deterministic).
3. Add storage (engine + version + input_hash) in SQLite.
4. Add tests to assert determinism and minimum fields.
5. Update `docs/REPO_EXPLAINED.md` and `SKILL.md`.

## Maintenance Rule

Every new phase must update `docs/REPO_EXPLAINED.md` with changes and new commands.
