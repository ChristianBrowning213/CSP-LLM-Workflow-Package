# External Benchmark Setup (Local Staged LMDB)

This repo supports local staged external benchmark ingestion for:

- `mp_20`
- `perov_5`
- `mpts_52`

Staged raw layout (no network download step):

- `benchmarks/external/mp_20/raw/{train,val,test}.lmdb`
- `benchmarks/external/perov_5/raw/{train,val,test}.lmdb`
- `benchmarks/external/mpts_52/raw/{train,val,test}.lmdb`

## 1) Normalize staged LMDB splits

Normalize one dataset:

```bash
python -m sok_llm_orchestrator.cli benchmark import-external --dataset mp_20
```

Normalize all staged datasets:

```bash
python -m sok_llm_orchestrator.cli benchmark import-external --dataset all
```

Normalized outputs:

- `benchmarks/external/<dataset>/normalized/train.jsonl`
- `benchmarks/external/<dataset>/normalized/val.jsonl`
- `benchmarks/external/<dataset>/normalized/test.jsonl`

Each normalized row includes:

- `benchmark_dataset`
- `split`
- `case_id`
- `composition`
- `cif`
- `source_metadata`

## 2) Run external benchmark matrix

Run the matrix on test split with bounded budget:

```bash
python -m sok_llm_orchestrator.cli \
  --config my_live_config.yaml \
  --workspace .sokllm_workspace_live \
  benchmark run-external \
  --mode live \
  --dataset all \
  --splits test \
  --regimes all \
  --max-cases-per-split 8 \
  --max-iterations 4 \
  --selection-view property_decomp_aware
```

Supported regimes:

- `qlip_baseline`
- `qlip_fixed_spp`
- `qlip_retrieval_spp`
- `qlip_full_orchestrator`

Outputs are written under:

- `.sokllm_workspace*/benchmarks/external_matrix/<matrix_id>/external_benchmark_matrix_results.json`
- `.sokllm_workspace*/benchmarks/external_matrix/<matrix_id>/external_benchmark_matrix_report.json`

## 3) Regenerate matrix report from saved results

```bash
python -m sok_llm_orchestrator.cli benchmark regenerate-external --results <path-to-results-json>
```

## 4) Compare two matrix reports

```bash
python -m sok_llm_orchestrator.cli benchmark compare-external --left <left-report> --right <right-report>
```

## Notes and caveats

- This path is local-file-first and intentionally does not fetch datasets from the internet.
- `lmdb` is required for import (`benchmark import-external`).
- Current split handling follows the staged `train/val/test` files as-is.
- Polymorph-aware split construction and richer rediscovery metrics remain future work.
