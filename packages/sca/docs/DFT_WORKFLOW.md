# External DFT Workflow

SCA prepares, submits, tracks, collects, parses, validates, and analyses. CASTEP (or another future
adapter) remains the electronic-structure engine.

## Prepare

```powershell
python -m sca.cli dft prepare `
  --manifest benchmarks/paper_advanced_validation/PAPER_6_DFT_MANIFEST.csv `
  --backend castep `
  --config configs/dft_pbe_relax.yaml `
  --slurm-config configs/slurm_barkla.json `
  --out-dir artifacts/dft/prepared
```

Copy `configs/slurm_barkla.example.json` to `configs/slurm_barkla.json` and replace the partition
and module placeholders with values confirmed by Barkla documentation/support. SCA does not guess
an account, licensed executable, module, or queue.

Each directory contains `calculation.json`, `input.cif`, `input.sha256`, CASTEP `.cell`/`.param`
files, `environment.json`, `settings_fingerprint.json`, and (when configured) `submit.slurm` plus
the exact scheduler config.

## Submit, track, collect

Run these commands on Barkla after confirming CASTEP and Slurm availability:

```powershell
python -m sca.cli dft submit --calculations artifacts/dft/prepared
python -m sca.cli dft status --calculations artifacts/dft/prepared --json artifacts/dft/DFT_STATUS.json
python -m sca.cli dft collect --calculations artifacts/dft/prepared --out-dir artifacts/dft/results
```

Submission captures only a job ID actually returned by `sbatch`. States normalize to `PREPARED`,
`QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `TIMEOUT`, `NOT_CONVERGED`, or `UNKNOWN`. Collection
classifies SCF/ionic non-convergence, walltime, engine crash, missing output, pseudopotential,
memory, structure-collapse, parser, and unknown failures. SCA never silently changes settings.
Retries require a new calculation ID, parent ID, changed parameters, and reason.

The current repository/environment contains no confirmed Barkla configuration or licensed CASTEP
or VASP executable. The CASTEP adapter is therefore testable and preparation-ready, while live
execution remains `BLOCKED_ENVIRONMENT` until the site values are supplied on Barkla.

