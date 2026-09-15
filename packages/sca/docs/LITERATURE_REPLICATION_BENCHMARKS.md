# Literature-Replication Benchmarks

SCA has a secondary benchmark stack for comparing generated CIF sets against
literature-style comparator values. These reports are audit aids, not leaderboard
claims unless the dataset scope and protocol match the cited paper exactly.

## Protocol Registry

```bat
python -m sca.cli list-benchmark-protocols
python -m sca.cli list-benchmark-protocols --json reports\benchmark_protocols.json
```

Every protocol row includes required inputs/evaluators, dataset scope, and the
protocol requirements needed for an exact comparison.

## Direct Folder Benchmark

```bat
python -m sca.cli benchmark-cif-set ^
  --cif-folder "C:\Users\brown\Downloads\example created cifs" ^
  --protocols all ^
  --out reports\direct_cif_results.csv ^
  --summary reports\direct_cif_summary.csv ^
  --json reports\direct_cif_summary.json ^
  --markdown reports\direct_cif_report.md
```

## Direct Manifest Benchmark

```bat
python -m sca.cli benchmark-cif-set ^
  --manifest benchmarks\paper_targets\generated_manifest.csv ^
  --protocols all ^
  --out reports\direct_manifest_results.csv ^
  --summary reports\direct_manifest_summary.csv ^
  --json reports\direct_manifest_summary.json ^
  --markdown reports\direct_manifest_report.md
```

## E2E Fake Generator Benchmark

```bat
python -m sca.cli run-e2e-text-benchmark ^
  --prompts benchmarks\e2e_text_prompts\e2e_prompts_v1.csv ^
  --generator-command "python tests\fixtures\fake_generator.py --prompt {prompt} --out-dir {out_dir} --attempts {num_attempts}" ^
  --out-dir reports\e2e_fake_runs ^
  --num-attempts 3 ^
  --protocols all ^
  --summary reports\e2e_fake_summary.csv ^
  --markdown reports\e2e_fake_report.md
```

Supported generator placeholders are `{prompt}`, `{prompt_id}`, `{out_dir}`,
`{num_attempts}`, `{target_formula}`, `{target_space_group}`, and
`{target_structure_family}`.

## Comparator Matrix

Direct and E2E reports write:

`benchmark_family,metric_name,our_value,paper_value,paper_name,comparator_name,direction,unit,beats_paper,delta,dataset_scope,protocol_match_level,n_total,n_computable,n_not_computable,required_inputs_missing,notes`

`protocol_match_level` is one of `exact_protocol`, `subset_protocol`,
`approximate_protocol`, `contextual_only`, or `not_comparable`.

## Caveats

- Contextual comparator values are not leaderboard claims.
- Surrogate MLIP is not DFT.
- Local novelty is not global novelty.
- Subset protocol is not full MP-20/MPTS-52.
- Missing references, hulls, property targets, or generator outputs produce
  `not_computable` rows instead of crashes.
