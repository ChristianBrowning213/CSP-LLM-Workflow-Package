# MLIP Relaxation Validation

The frozen paper input is
`benchmarks/paper_advanced_validation/PAPER_16_MANIFEST.csv`. Validate and baseline it before any
model run:

```powershell
python -m sca.cli validate-paper16-manifest
python -m sca.cli build-paper16-baseline
python -m sca.cli run-paper16-mlip
```

Every relaxation writes a new CIF under
`artifacts/electronic_stack/paper16/mlip_relaxed/chgnet/`. The source `generated.cif` is never
rewritten; both hashes are recorded and the source hash is checked again after each attempt.

The transition evaluator performs species-constrained periodic assignment and reports RMS/maximum
atomic displacement, lattice-axis and angle changes, volume change, composition consistency, and
site-count consistency. A mapping failure is explicit.

`ROBUST` requires a converged/available transition, retained composition/site count, valid geometry,
retained requested topology when evaluable, and no severe contacts. Exact space-group retention is
required only when the original manifest says `require_space_group=true`. Symmetry lowering with
the core family intact may be `MODIFIED_BUT_VALID`; loss of composition/topology, severe contacts,
mapping failure, or pathological volume change is `COLLAPSED`.

MLIP ensemble comparison uses within-model percentile ranks across the campaign. It never averages
raw CHGNet, M3GNet, MACE, or SevenNet energies and never calls a candidate thermodynamically stable.

