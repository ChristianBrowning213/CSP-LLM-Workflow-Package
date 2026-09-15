# SCA Benchmarking

SCA benchmark mode is for pre-DFT screening and benchmarking of generated crystal
structures. It collects reusable validity, target-matching, novelty, duplicate,
and optional surrogate-model outputs into CSV and JSONL reports that can be used
to compare generation methods before more expensive relaxation or DFT.

SCA benchmark mode does not prove thermodynamic stability. ALIGNN and CHGNet
outputs are surrogate model outputs, not final validation. DFT relaxation,
energy-above-hull calculations, and experimental validation should be handled
separately later.

For natural-language crystal-design intent benchmarks, use the full
Skill-Loop-CSP workflow in `docs/FULL_INTENT_BENCHMARK.md`. In that mode
Skill-Loop-CSP generates CIFs or infeasibility archives, and SCA builds prompts,
collects run archives, runs direct CIF validity, evaluates `intent_satisfaction`,
converts traceable bundles, and writes one final report.

## Manifest Format

Benchmark manifests are CSV files. The default path column is `cif_path`.
Relative CIF paths are resolved relative to the manifest file.

Common columns:

- `cif_path`: generated CIF to evaluate
- `target_formula`: optional expected composition
- `target_space_group`: optional expected space group
- `target_cif_path`: optional target/reference CIF for `structure_match`
- `reference_id`: optional label for the target structure
- `target_formation_energy_per_atom`: optional target property value
- `target_energy_above_hull`: optional target property value
- `target_band_gap`: optional target property value
- `target_property_name`: optional generic target property name
- `target_property_value`: optional generic target property value
- `method`: generator or workflow name
- `query_id`: prompt, composition, or task identifier

## Evaluators

- `pre_dft_validity`: CIF parsing, composition, symmetry, multiplicity,
  contact, geometry, duplicate grouping, novelty, and optional ALIGNN-in-pipeline
  checks reused from the CrystaLLM-style workflow.
- `structure_match`: StructureMatcher target-CIF matching with exact,
  anonymous, and combined modes.
- `alignn`: optional ALIGNN formation-energy adapter.
- `chgnet_static`: optional CHGNet static surrogate-energy adapter.
- `chgnet_relax`: optional CHGNet structure relaxation adapter that writes real
  `relax_ok`, before/after energy, before/after max force, relaxed CIF, and
  reference-match columns for paper benchmark D metrics.
- `spp`: Statistical Pair Potential plausibility scorer from a versioned
  `spp.v1.json` artifact.
- `m3gnet_static`, `mace_static`, `sevennet_static`: optional MLIP-depth static
  surrogate routes.
- `mlip_ensemble`: model-disagreement metrics from available surrogate energies.
- `property_targets`: compares predicted/surrogate properties against manifest
  target values.
- `predicted_hull`: computes predicted/surrogate energy above hull from local
  reference phase entries.
- `intent_satisfaction`: deterministic row evaluator for checking whether a
  generated CIF matches the prompt's formula, family, symmetry, motif,
  distance/contact, and expected solver-status constraints. Missing components
  are marked `not_computable`, not zero.

Optional evaluators are lazy. If an optional dependency such as ALIGNN or CHGNet
is not installed, benchmark runs return structured evaluator results rather than
crashing the whole benchmark.

See `docs/INSTALL_BACKENDS.md` for optional extras, model setup, and
`python -m sca.cli verify-backends`.

For paper-comparable A-E summaries over an existing benchmark CSV, see
`docs/PAPER_BENCHMARKS.md` and:

```bash
python -m sca.cli build-paper-run-manifest \
  --targets benchmarks/paper_targets/paper_targets_v1.csv \
  --generated-folder "C:\Users\brown\Downloads\example created cifs" \
  --out benchmarks/paper_targets/generated_manifest.csv \
  --unmatched-out benchmarks/paper_targets/unmatched_generated_cifs.csv

python -m sca.cli benchmark manifest benchmarks/paper_targets/generated_manifest.csv \
  --evaluators pre_dft_validity,structure_match,chgnet_static,chgnet_relax,m3gnet_static,mace_static,sevennet_static,mlip_ensemble \
  --out reports/paper_targets_results.csv \
  --jsonl reports/paper_targets_results.jsonl

python -m sca.cli paper-benchmark-summary reports/paper_targets_results.csv \
  --manifest benchmarks/paper_targets/paper_targets_v1.csv \
  --include-built-in-comparators \
  --out reports/paper_benchmark_summary.csv \
  --json reports/paper_benchmark_summary.json \
  --markdown reports/paper_benchmark_report.md
```

For literature-replication comparator reports over arbitrary CIF folders or
manifests, see `docs/LITERATURE_REPLICATION_BENCHMARKS.md`.

```bash
python -m sca.cli list-benchmark-protocols

python -m sca.cli benchmark-cif-set \
  --manifest benchmarks/paper_targets/generated_manifest.csv \
  --protocols all \
  --out reports/direct_manifest_results.csv \
  --summary reports/direct_manifest_summary.csv \
  --json reports/direct_manifest_summary.json \
  --markdown reports/direct_manifest_report.md
```

For the complementary unique verifiable-CSP benchmark, see
`docs/UNIQUE_VERIFIABLE_CSP_BENCHMARKS.md`. That stack asks whether a
natural-language crystal request produced a traceable, retrieval-grounded,
constraint-faithful, solver-backed, auditable, repairable, and reproducible CSP
run.

Real run archives can be converted into traceable bundles before scoring:

```bat
python -m sca.cli convert-run-archive-to-bundle ^
  --archive path\to\llm_csp_run ^
  --out-dir reports\traceable_bundles\run_001 ^
  --run-id run_001

python -m sca.cli convert-run-archives-to-bundles ^
  --archives-root reports\e2e_runs ^
  --out-dir reports\traceable_bundles ^
  --summary reports\traceable_bundle_conversion_summary.csv

python -m sca.cli unique-csp-benchmark-summary ^
  --bundles reports\traceable_bundles ^
  --out reports\unique_csp_real_summary.csv ^
  --json reports\unique_csp_real_summary.json ^
  --markdown reports\unique_csp_real_report.md
```

## Example Commands

```bash
python -m sca.cli list-evaluators
```

```bash
python -m sca.cli benchmark one examples/cifs/tiny_valid.cif \
  --evaluators pre_dft_validity \
  --out reports/one.csv \
  --jsonl reports/one.jsonl
```

```bash
python -m sca.cli benchmark manifest examples/cif_manifest.csv \
  --evaluators pre_dft_validity,structure_match \
  --path-col cif_path \
  --target-cif-col cif_path \
  --method-col method \
  --query-id-col query_id \
  --out reports/bench.csv \
  --jsonl reports/bench.jsonl
```

```bash
python -m sca.cli benchmark manifest examples/cif_manifest.csv \
  --evaluators pre_dft_validity \
  --path-col cif_path \
  --reference-folder examples/cifs \
  --out reports/bench_novelty.csv \
  --jsonl reports/bench_novelty.jsonl
```

```bash
python -m sca.cli benchmark-summary reports/bench.csv \
  --group-col method \
  --out reports/bench_summary.csv
```

```bash
python -m sca.cli benchmark one examples/cifs/tiny_valid.cif \
  --evaluators pre_dft_validity,spp,chgnet_static,mlip_ensemble \
  --spp-artifact examples/spp.v1.json \
  --out reports/v15.csv \
  --jsonl reports/v15.jsonl
```

```bash
python -m sca.cli benchmark manifest examples/cif_manifest.csv \
  --evaluators chgnet_static,predicted_hull,property_targets \
  --hull-reference references/local_phase_entries.csv \
  --out reports/property_hull.csv \
  --jsonl reports/property_hull.jsonl
```

Predicted hull mode uses only local reference entries. It does not call Materials
Project and does not produce a true DFT energy above hull unless the supplied
reference and generated energies are real DFT energies.

## Rediscovery Labels

Benchmark rows include `rediscovery_label`:

- `invalid`: parsing failed
- `valid_reference_not_checked`: valid enough to parse, but novelty/reference
  checking was not run
- `valid_known_match`: novelty/reference matching found a known structure
- `valid_novel`: novelty/reference matching found no known match
- `valid_unknown`: novelty/reference checking ran but did not produce a clear
  known or novel label
