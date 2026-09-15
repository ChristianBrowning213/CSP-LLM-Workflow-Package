# Advanced Crystal Analysis

SCA's advanced workflow is an evidence-preserving orchestration stack:

```text
generated CIF -> crystallographic/intent checks -> MLIP static/relaxation
              -> post-MLIP checks -> external DFT -> post-DFT checks
              -> compatible formation energy -> compatible DFT convex hull
```

Run a single-crystal report with:

```powershell
python -m sca.cli analyse-crystal candidate.cif --intent intent.json --level advanced --out-dir reports/advanced
```

Optional layers are never silently omitted. They appear as `NOT_RUN`, `NOT_AVAILABLE`,
`NOT_COMPUTABLE`, or `SKIPPED`. The report exposes independent dimensions for crystallographic
validity, intent compliance, MLIP robustness/agreement, DFT relaxation robustness, formation
energy availability, and thermodynamic context. It intentionally has no universal quality score.

The evidence tiers are not interchangeable:

- An SPP score is a statistical pair-potential plausibility score, not physical energy.
- ALIGNN formation energy is a learned prediction, not DFT formation energy.
- MLIP energy is model-specific surrogate energy, not DFT energy. Raw energies from unrelated
  MLIPs are not averaged.
- MLIP relaxation tests robustness under one approximate potential; it is not proof of stability.
- DFT relaxation tests convergence to a local stationary structure; it is not energy above hull.
- Energy above hull requires compatible competing phases; it is not experimental synthesizability.

Machine-readable outputs are `advanced_analysis.csv`, `advanced_analysis.jsonl`, and
`advanced_analysis_summary.json`; the human report is `advanced_analysis_report.md`.

