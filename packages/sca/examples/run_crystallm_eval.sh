#!/usr/bin/env bash
set -euo pipefail

sca crystallm-eval manifest examples/cif_manifest.csv \
  --path-col cif_path \
  --formula-col target_formula \
  --spacegroup-col target_space_group \
  --method-col method \
  --query-id-col query_id \
  --alignn false \
  --out examples/pre_dft_eval.csv \
  --jsonl examples/pre_dft_eval.jsonl

sca summarize examples/pre_dft_eval.csv \
  --group-col method \
  --out examples/pre_dft_summary_by_method.csv

sca select-top-k examples/pre_dft_eval.csv \
  --group-cols method,query_id \
  --k 5 \
  --out examples/top5_for_dft.csv
