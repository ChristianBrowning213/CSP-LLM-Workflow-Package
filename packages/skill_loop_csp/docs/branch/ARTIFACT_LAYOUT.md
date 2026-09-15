# Branch Artifact Layout

Run root: `<workspace>/runs/<run_id>/`

Core files:

- `manifest.json`
- `tool_call_log.jsonl`
- `calls/*.json`

Branch-specific artifacts:

- `artifacts/task_spec.json`
- `artifacts/run_plan.json`
- `artifacts/clarification_decision.json`
- `artifacts/retrieval_bundle.json`
- `artifacts/spp_corpus_manifest.json`
- `artifacts/cell_candidates.json`
- `artifacts/spp_artifact_manifest.json` (guided runs)
- `artifacts/spp_calibration_report.json` (guided runs)
- `artifacts/verification_report.json`

Benchmark roots:

- `<workspace>/benchmarks/<benchmark_id>/benchmark_results.json`
- `<workspace>/benchmarks/<benchmark_id>/benchmark_report.json`
