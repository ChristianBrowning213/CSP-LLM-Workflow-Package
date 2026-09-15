# Paper-Comparable Benchmarks

SCA paper benchmark summaries consume ordinary `sca benchmark` CSV outputs and
compute scalar A-E metrics for paper-style comparison. This is a framework for
paper-derived target subsets and comparable protocol checks. It is not a full
MP-20, MPTS-52, or other leaderboard reproduction unless the manifest explicitly
uses that full dataset and protocol.

For direct CIF and end-to-end literature comparator reports, see
`docs/LITERATURE_REPLICATION_BENCHMARKS.md`.

For the complementary traceable workflow benchmark, see
`docs/UNIQUE_VERIFIABLE_CSP_BENCHMARKS.md`. That stack asks whether a run is
retrieval-grounded, constraint-faithful, solver-backed, auditable, repairable,
and reproducible.

## Benchmark Groups

- `A_validity`: parse, composition, pre-DFT validity, geometry, contacts.
- `B_structure_reproduction`: StructureMatcher match rates and RMS distances.
- `C_mlip_stability`: optional MLIP success, disagreement, and predicted hull
  threshold rates.
- `D_relaxation`: relaxation success, force, energy-drop, and RMSE deltas from
  real relaxation columns.
- `E_novelty_sun`: local uniqueness, local novelty, and SUN using predicted hull
  or MLIP consensus as the stability proxy.

Missing inputs produce not-computable rows instead of crashes.

## Templates

- `benchmarks/paper_targets/paper_targets_v1.csv`
- `benchmarks/paper_targets/comparator_values_v1.csv`
- `benchmarks/paper_targets/reference_cifs_v1.csv`
- `benchmarks/paper_targets/reference_cifs/`

`reference_cifs_v1.csv` records the auditable prototype references used for the
22 generated challenge targets. These are not generated CIFs and should not be
treated as DFT-relaxed ground truth. Fill or pass a hull reference before
interpreting predicted hull metrics.

## Example 1: Generated Folder

Build a run manifest that maps generated CIFs to paper target rows:

```bat
python -m sca.cli build-paper-run-manifest ^
  --targets benchmarks\paper_targets\paper_targets_v1.csv ^
  --generated-folder "C:\Users\brown\Downloads\example created cifs" ^
  --out benchmarks\paper_targets\generated_manifest.csv ^
  --unmatched-out benchmarks\paper_targets\unmatched_generated_cifs.csv
```

Then benchmark that manifest so paper metadata such as `benchmark_id`,
`attempt_id`, and `target_formula` are preserved in the result CSV:

```bat
python -m sca.cli benchmark manifest benchmarks\paper_targets\generated_manifest.csv ^
  --evaluators pre_dft_validity,structure_match,novelty,chgnet_static,chgnet_relax,m3gnet_static,mace_static,sevennet_static,mlip_ensemble ^
  --path-col cif_path ^
  --formula-col target_formula ^
  --spacegroup-col target_space_group ^
  --target-cif-col target_cif_path ^
  --target-reference-id-col reference_id ^
  --method-col paper_source ^
  --query-id-col benchmark_id ^
  --out reports\paper_targets_results.csv ^
  --jsonl reports\paper_targets_results.jsonl
```

For a CPU-friendly CHGNet relaxation pass on Windows CMD, set optional relaxation
knobs before the benchmark command:

```bat
set SCA_CHGNET_RELAX_STEPS=50
set SCA_CHGNET_RELAX_FMAX=0.1
set SCA_CHGNET_RELAX_OUT_DIR=reports\paper_targets_chgnet_relaxed
```

Unset them afterwards if you do not want later runs to inherit those settings.

## Example 2: Summarize Against Manifest

```bat
python -m sca.cli paper-benchmark-summary reports\paper_targets_results.csv ^
  --manifest benchmarks\paper_targets\paper_targets_v1.csv ^
  --comparator-values benchmarks\paper_targets\comparator_values_v1.csv ^
  --include-built-in-comparators ^
  --out reports\paper_benchmark_summary.csv ^
  --json reports\paper_benchmark_summary.json ^
  --markdown reports\paper_benchmark_report.md
```

## Example 3: Per-Target Diagnostics

Use this after the benchmark and paper summary to classify each target's success
or failure without changing the benchmark metrics:

```bat
python -m sca.cli paper-target-diagnostics ^
  --results reports\paper_targets_results.csv ^
  --manifest benchmarks\paper_targets\generated_manifest.csv ^
  --references benchmarks\paper_targets\reference_cifs_v1.csv ^
  --out reports\paper_target_diagnostics.csv ^
  --json reports\paper_target_diagnostics.json ^
  --markdown reports\paper_target_diagnostics.md
```

Diagnostics rows include `primary_category`, `category_flags`,
`relaxation_effect`, `reference_risk`, parsed generated/reference/relaxed space
groups, volume ratios, and the raw structure-match and relaxation evidence.

## Example 4: With Hull Reference

```bat
python -m sca.cli benchmark manifest benchmarks\paper_targets\generated_manifest.csv ^
  --evaluators pre_dft_validity,structure_match,predicted_hull,chgnet_static,m3gnet_static,mace_static,sevennet_static,mlip_ensemble ^
  --hull-reference data\reference_hulls\paper_targets_hull.csv ^
  --out reports\paper_targets_hull_results.csv ^
  --jsonl reports\paper_targets_hull_results.jsonl
```

## Output Columns

`paper-benchmark-summary` writes rows with:

- `summary_scope`
- `benchmark_group`
- `metric_name`
- `our_value`
- `n_total`
- `n_computable`
- `n_not_computable`
- `comparator_name`
- `comparator_value`
- `comparator_direction`
- `beats_comparator`
- `delta`
- `unit`
- `notes`

Comparator rows include metric name, comparator name, comparator value, direction,
our value, pass/fail, delta, units, and notes.

## Caveats

- Surrogate MLIP scores are not DFT.
- Local novelty is not global novelty.
- Paper-derived target subsets are not full MP-20/MPTS-52 leaderboard results
  unless explicitly scoped that way.
- Predicted hull metrics require local reference hull entries.
- Relaxation metrics require actual relaxed structures; SCA does not fake them
  from static energy outputs.
