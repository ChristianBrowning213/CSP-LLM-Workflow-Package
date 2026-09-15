# Full 100 Seeded Skill-Loop-CSP Manifest

This directory contains the prompt/run manifest for executing a deterministic 100-run Skill-Loop-CSP benchmark with seed `20260626`.

Skill-Loop-CSP is the generator/orchestrator for these runs. SCA is the downstream evaluator and should be run only after Skill-Loop-CSP has generated the run archives and CIF outputs.

## Files

- `full_100_skill_loop_manifest.csv`: CSV manifest for the 100 Skill-Loop-CSP inputs.
- `full_100_skill_loop_manifest.json`: JSON copy of the same rows for tooling that prefers structured input.
- `run_config.json`: Seed, manifest path, executor, evaluator, and benchmark notes.
- `downstream_sca_commands.md`: Later SCA command sketch for post-execution evaluation.

## Benchmark Modes

- `loose_design_intent`: Broad formula/family prompts from the loose design-intent source set.
- `motif_specific`: Source prompts with explicit retrieval, SPP/POT, QLIP, novelty, and motif language.
- `retrieval_evidence_grounded`: Motif-specific prompts with an explicit requirement to cite retrieved structures that informed constraints.
- `solver_constraint_heavy`: Motif-specific prompts with an explicit requirement to emit solver status, objective value, active constraints, and generated CIF.
- `adversarial_or_infeasible`: Impossible or conflicting prompts that should be rejected, invalidated, or certified infeasible.

## Expected Artifact Layout

Skill-Loop-CSP execution should write raw run archives under:

```text
reports/full_100_seeded_20260626/raw_runs/run_001
...
reports/full_100_seeded_20260626/raw_runs/run_100
```

Each archive is expected to preserve the manifest row, seed, prompt text, generated CIF when applicable, solver status when applicable, and enough traceability for SCA to evaluate the result after execution.

## Reproducibility

All rows carry seed `20260626`. The manifest is deterministic and validation is provided by:

```powershell
python scripts/validate_full_100_manifest.py benchmarks/full_100_seeded_20260626/full_100_skill_loop_manifest.csv
```

This directory is manifest-only. The rows become physically meaningful benchmark cases only after Skill-Loop-CSP executes the prompts and SCA evaluates the generated outputs.
