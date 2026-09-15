# Unique Verifiable CSP Benchmarks

Existing crystal-generation benchmarks mostly ask: did the model emit a plausible CIF?

This benchmark family asks a different question: did the system convert a natural-language materials request into a traceable, retrieval-grounded, constraint-faithful, solver-backed, auditable, repairable, and reproducible CSP run?

The stack is separate from the literature-replication benchmark layer. It can be run with synthetic fixtures in CI and later pointed at real LLM-CSP, QLIP, CHGNet, MACE, SevenNet, or other backends.

The full intent benchmark uses this stack after generation: SCA converts
Skill-Loop-CSP raw run archives to traceable bundles, runs
`unique-csp-benchmark-summary`, and combines those results with direct CIF
validity and `intent_satisfaction`. See `docs/FULL_INTENT_BENCHMARK.md` for the
end-to-end command sequence and adversarial/infeasible prompt scoring.

## Commands

Inspect one run bundle:

```bat
python -m sca.cli inspect-run-bundle ^
  --run-dir reports\e2e_runs\example_run ^
  --out reports\run_bundle_inspection.csv ^
  --json reports\run_bundle_inspection.json ^
  --markdown reports\run_bundle_inspection.md
```

Run retrieval ablation with a fake generator:

```bat
python -m sca.cli run-retrieval-ablation-benchmark ^
  --prompts benchmarks\unique_verifiable_csp\retrieval_ablation_prompts.csv ^
  --generator-command "python tests\fixtures\fake_generator.py --prompt {prompt} --out-dir {out_dir} --attempts {num_attempts}" ^
  --retrieval-modes none,metadata,evidence_spp ^
  --out-dir reports\retrieval_ablation ^
  --summary reports\retrieval_ablation_summary.csv ^
  --json reports\retrieval_ablation_summary.json ^
  --markdown reports\retrieval_ablation_report.md
```

Run repairability with a fake repair command:

```bat
python -m sca.cli run-repairability-benchmark ^
  --cases benchmarks\unique_verifiable_csp\repair_cases.csv ^
  --repair-command "python tests\fixtures\fake_repair.py --input-cif {input_cif} --prompt {prompt} --out-dir {out_dir}" ^
  --out-dir reports\repairability ^
  --summary reports\repairability_summary.csv ^
  --json reports\repairability_summary.json ^
  --markdown reports\repairability_report.md
```

Build the composite report:

```bat
python -m sca.cli unique-csp-benchmark-summary ^
  --bundles reports\e2e_runs ^
  --out reports\unique_csp_benchmark_summary.csv ^
  --json reports\unique_csp_benchmark_summary.json ^
  --markdown reports\unique_csp_benchmark_report.md
```

Convert one LLM-CSP, QLIP, or evidence-pack archive into the traceable bundle format:

```bat
python -m sca.cli convert-run-archive-to-bundle ^
  --archive path\to\llm_csp_run ^
  --out-dir reports\traceable_bundles\run_001 ^
  --run-id run_001 ^
  --markdown reports\traceable_bundles\run_001_inspection.md
```

Batch-convert archives:

```bat
python -m sca.cli convert-run-archives-to-bundles ^
  --archives-root reports\e2e_runs ^
  --out-dir reports\traceable_bundles ^
  --summary reports\traceable_bundle_conversion_summary.csv
```

Run the unique benchmark on converted bundles:

```bat
python -m sca.cli unique-csp-benchmark-summary ^
  --bundles reports\traceable_bundles ^
  --out reports\unique_csp_real_summary.csv ^
  --json reports\unique_csp_real_summary.json ^
  --markdown reports\unique_csp_real_report.md
```

## Evaluators

The unique benchmark layer registers these dependency-free row evaluators:

- `evidence_traceability`
- `constraint_faithfulness`
- `solver_certificate`
- `evidence_faithfulness`
- `audit_bundle_completeness`

They can also be used through the existing modular benchmark command when manifest rows include `run_bundle_dir` or `bundle_dir`.

## Synthetic Assets

Prompt suites live in `benchmarks\unique_verifiable_csp`:

- `traceable_csp_prompts_v1.csv`
- `infeasible_prompts.csv`
- `retrieval_ablation_prompts.csv`
- `repair_cases.csv`
- `evidence_trap_prompts.csv`

The test bundle at `tests\fixtures\traceable_run_bundle` contains a complete offline audit trail.

## Archive Adapter Coverage

`sca.traceability.adapters.llm_csp_archive` performs best-effort conversion from real or real-like run folders. It recognizes common archive artifacts:

- prompts: `prompt.txt`, `input.txt`, `input_prompt.txt`
- structured intent: `structured_intent*.json`, `*intent*.json`, `robocrys_intent_rescore.json`
- retrieval/evidence: `retrieval_trace*.json`, `*retrieval*.json`, `*evidence*.json`, `qlip*.json`
- constraints: `constraint_trace*.json`, `*constraints*.json`
- SPP traces: `spp_trace*.json`, `spp*.json`
- solver files/logs: `solver_trace*.json`, `*solver*.json`, `qlip_solve*.json`, `*solve*.json`, `*solver*.log`
- generated candidates: `*.cif`
- validation, relaxation, diagnostics, and final decision/report files

Missing source artifacts are written into `bundle_manifest.csv` and left absent from the normalized bundle so `inspect-run-bundle` reports them honestly.

## Composite Score

`traceable_constraint_grounded_csp_score` is:

```text
0.20 * output_validity
+ 0.20 * constraint_faithfulness_score
+ 0.15 * structure_or_prototype_match_score
+ 0.15 * mlip_or_relaxation_robustness_score
+ 0.15 * evidence_trace_score
+ 0.10 * audit_bundle_score
+ 0.05 * solver_certificate_score
```

This score is a workflow-audit score, not a replacement for physical-validity or DFT-level metrics.

## Limitations

The adapter is heuristic. It does not interpret every possible custom run manager format, and it does not run QLIP, MLIP, CHGNet, MACE, SevenNet, internet retrieval, DFT, or a repair loop. Metrics involving those systems become physically meaningful only when the converted archive contains real evidence, solver, validation, relaxation, diagnostics, and candidate artifacts.
