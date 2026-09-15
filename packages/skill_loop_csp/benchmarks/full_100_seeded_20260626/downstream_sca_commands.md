# Downstream SCA Commands

Run these only after Skill-Loop-CSP has executed the 100 manifest rows and produced raw run archives under `reports/full_100_seeded_20260626/raw_runs/`.

```powershell
sca convert-run-archives-to-bundles `
  --input reports/full_100_seeded_20260626/raw_runs `
  --output reports/full_100_seeded_20260626/sca_bundles `
  --manifest benchmarks/full_100_seeded_20260626/full_100_skill_loop_manifest.csv
```

```powershell
sca benchmark-cif-set `
  --input reports/full_100_seeded_20260626/sca_bundles `
  --output reports/full_100_seeded_20260626/sca_benchmark_results
```

```powershell
sca unique-csp-benchmark-summary `
  --input reports/full_100_seeded_20260626/sca_benchmark_results `
  --output reports/full_100_seeded_20260626/sca_unique_summary.json
```

If the installed SCA version supports paper-target diagnostics for this bundle schema:

```powershell
sca paper-target-diagnostics `
  --input reports/full_100_seeded_20260626/sca_benchmark_results `
  --manifest benchmarks/full_100_seeded_20260626/full_100_skill_loop_manifest.csv `
  --output reports/full_100_seeded_20260626/sca_paper_target_diagnostics.json
```
