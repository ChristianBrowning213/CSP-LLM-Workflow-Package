# Full Intent Benchmark

SCA can control a full end-to-end intent benchmark where Skill-Loop-CSP is the
generator and SCA is the benchmark controller/evaluator. The benchmark input is a
natural-language crystal-design intent, not a pre-existing CIF. Skill-Loop-CSP
generates or rejects each prompt, while SCA records raw archives, collects CIFs,
converts traceability bundles, and evaluates validity plus intent satisfaction.

Default run root:

```text
local_runs/full_100_intent_benchmark_seeded_20260626/
```

## Build Prompt Manifest

```bat
python -m sca.cli build-intent-benchmark-manifest ^
  --out local_runs/full_100_intent_benchmark_seeded_20260626/prompts/intent_prompts_100.csv ^
  --json local_runs/full_100_intent_benchmark_seeded_20260626/prompts/intent_prompts_100.json ^
  --seed 20260626 ^
  --num-prompts 100
```

The 100-row manifest has this fixed mode distribution: 30 loose design intents,
25 motif-specific prompts, 15 retrieval-grounded prompts, 15 solver-heavy
prompts, 10 adversarial or infeasible prompts, and 5 repair/diagnostic prompts.
Each row includes `intent_constraints_json` with formula, family, symmetry,
motifs, contact rules, and expected solver status.

## Run Generation

```bat
python -m sca.cli run-skill-loop-intent-benchmark ^
  --prompts local_runs/full_100_intent_benchmark_seeded_20260626/prompts/intent_prompts_100.csv ^
  --skill-loop-command "python C:\Users\brown\Documents\GitHub\Skill-Loop-CSP\scripts\run_text_entrypoint.py --prompt {prompt} --out-dir {out_dir} --seed {seed}" ^
  --out-root local_runs/full_100_intent_benchmark_seeded_20260626 ^
  --seed 20260626
```

Supported command placeholders are `{prompt}`, `{prompt_id}`, `{run_index}`,
`{seed}`, `{out_dir}`, `{target_formula}`, and `{benchmark_mode}`. SCA writes
per-prompt stdout/stderr, `manifest_row.json`, `prompt.txt`, a CSV/JSONL
generation log, and `manifests/generated_cifs_manifest_for_sca.csv`.

## Run Evaluation Only

```bat
python -m sca.cli run-full-intent-benchmark-evaluation ^
  --run-root local_runs/full_100_intent_benchmark_seeded_20260626 ^
  --manifest local_runs/full_100_intent_benchmark_seeded_20260626/manifests/generated_cifs_manifest_for_sca.csv ^
  --seed 20260626
```

This converts raw Skill-Loop-CSP archives to traceable bundles, runs direct CIF
benchmarking, runs `cif_parse,geometry,intent_satisfaction`, builds unique CSP
traceability summaries, writes grouped diagnostics, and creates the final full
report and summary JSON.

## One-Shot Command

```bat
python -m sca.cli run-full-skill-loop-intent-benchmark ^
  --skill-loop-command "python C:\Users\brown\Documents\GitHub\Skill-Loop-CSP\scripts\run_text_entrypoint.py --prompt {prompt} --out-dir {out_dir} --seed {seed}" ^
  --out-root local_runs/full_100_intent_benchmark_seeded_20260626 ^
  --seed 20260626 ^
  --num-prompts 100
```

Use `--skip-generation` to evaluate existing generated CIFs and archives. Use
`--skip-evaluation` to stop after generation and CIF collection.

## Intent Satisfaction

Direct CIF validity asks whether a CIF parses, has sane geometry, and passes
pre-DFT structural checks. `intent_satisfaction` asks whether the final CIF
matches the prompt row: formula, target family/prototype, space group or crystal
system, motif/coordination/connectivity terms, distance/contact constraints, and
expected solver status.

The scorer is deterministic and excludes `not_computable` components from the
score denominator. Missing MLIP, relaxation, property, reference, or trace fields
are reported as `not_computable`, not as zero. Tests do not use an LLM judge.

Adversarial or infeasible prompts can pass intent if Skill-Loop-CSP emits no fake
CIF and records an infeasible or invalid status archive.

## Outputs

Final artifacts:

- `reports/FULL_100_INTENT_BENCHMARK_REPORT.md`
- `reports/FULL_100_INTENT_BENCHMARK_SUMMARY.json`
- `logs/generation_log.csv`
- `logs/generation_log.jsonl`
- `manifests/generated_cifs_manifest_for_sca.csv`
- `sca_direct_benchmark/benchmark_results.csv`
- `sca_intent_benchmark/intent_results.csv`
- `sca_unique_benchmark/unique_summary.csv`
- `diagnostics/grouped_by_benchmark_mode.csv`
- `diagnostics/grouped_by_chemistry_family.csv`
- `diagnostics/grouped_by_challenge_type.csv`
- `diagnostics/worst_20_intent_failures.csv`
