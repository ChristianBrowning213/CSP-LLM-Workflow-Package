# Paper Comparator Evidence

This file records source-backed comparator values for crystal-generation and crystal-structure-prediction papers. The values are normalized for later use in SCA reports, but most are contextual rather than directly comparable to our current 100-prompt Skill-Loop-CSP run.

Machine-readable copies:

- `data/paper_comparators/crystal_generation_comparators.csv`
- `data/paper_comparators/crystal_generation_comparators.json`

## Evidence Table

| Paper / system | Source | Year | Task | Scope | Metric | Value | Attempts | Status | Comparability | Note |
|---|---:|---:|---|---|---|---:|---:|---|---|---|
| CrysText / CrysText-RL | [ChemRxiv](https://chemrxiv.org/doi/10.26434/chemrxiv-2024-gjhpq) | 2025 | text-conditioned | paper reported | composition-only satisfaction |  |  | needs_manual_check | contextual_only | Exact composition-only CrysText-RL value was not confidently extractable from accessible text. |
| CrysText / CrysText-RL | [ChemRxiv](https://chemrxiv.org/doi/10.26434/chemrxiv-2024-gjhpq) | 2025 | text-conditioned | paper reported | composition+space-group satisfaction | 0.76 |  | ok | contextual_only | Source-accessible text reports 76% for CrysText-RL and 72% for supervised CrysText. |
| CrysText / CrysText-RL | [ChemRxiv](https://chemrxiv.org/doi/10.26434/chemrxiv-2024-gjhpq) | 2025 | CSP_from_formula | MP-20 | match_rate_n1 | 0.57 | 1 | ok | not_comparable | MP-20 reference-structure protocol. |
| CrysText / CrysText-RL | [ChemRxiv](https://chemrxiv.org/doi/10.26434/chemrxiv-2024-gjhpq) | 2025 | CSP_from_formula | MP-20 | match_rate_n20 | 0.73 | 20 | ok | not_comparable | Requires 20 samples per MP-20 target. |
| CrysText / CrysText-RL | [ChemRxiv](https://chemrxiv.org/doi/10.26434/chemrxiv-2024-gjhpq) | 2025 | CSP_from_formula | MP-20 | rms_dist | 0.0243 | 20 | ok | not_comparable | Paper StructureMatcher/RMSE setup. |
| Lang2Str | [arXiv HTML](https://arxiv.org/html/2603.03946v1) | 2026 | CSP_from_formula | MP-20 | structure_match_rate | 0.6392 |  | ok | not_comparable | Table 4: MR 63.92%, RMSE 0.076. |
| Lang2Str | [arXiv HTML](https://arxiv.org/html/2603.03946v1) | 2026 | CSP_from_formula | MP-20 | rms_dist | 0.076 |  | ok | not_comparable | Table 4 MP-20 RMSE. |
| Lang2Str | [arXiv HTML](https://arxiv.org/html/2603.03946v1) | 2026 | CSP_from_formula | MP-20 | relaxed_rms_dist | 0.055 |  | ok | not_comparable | Table 6 reports RMSE after ML-DFT relaxation. |
| Lang2Str | [arXiv HTML](https://arxiv.org/html/2603.03946v1) | 2026 | CSP_from_formula | MPTS-52 | structure_match_rate | 0.2836 |  | ok | not_comparable | Table 4: MR 28.36%, RMSE 0.1424. |
| Lang2Str | [arXiv HTML](https://arxiv.org/html/2603.03946v1) | 2026 | CSP_from_formula | MPTS-52 | rms_dist | 0.1424 |  | ok | not_comparable | Table 4 MPTS-52 RMSE. |
| CrystaLLM small | [Nature Communications](https://www.nature.com/articles/s41467-024-54639-7) | 2024 | text-conditioned | held-out test set | structure_match_rate | 0.881 | 3 | ok | contextual_only | Article reports at least one match within three attempts for 88.1% of 10,286 held-out CIF prompts. |
| CrystaLLM large | [Nature Communications](https://www.nature.com/articles/s41467-024-54639-7) | 2024 | text-conditioned | challenge unseen | structure_match_rate | 0.40 | 100 | ok | contextual_only | Article states unseen challenge structures matched in up to 40% of cases. |
| CrystaLLM | [official GitHub](https://github.com/lantunes/CrystaLLM/blob/main/BENCHMARKING.md) | 2024 | CSP_from_formula | Perov-5 / Carbon-24 / MP-20 / MPTS-52 | match_rate_n20 |  | 20 | needs_manual_check | not_comparable | Official repo documents reproduction steps; exact full-size table values should be rechecked before publication use. |
| Chemeleon | [Nature Communications](https://www.nature.com/articles/s41467-025-59636-y) | 2025 | text-conditioned | paper reported | pre_dft_validity_rate | 0.98-0.99 | 20 | ok | contextual_only | Validity means no overlap and reasonable cell lengths; test set has 708 structures. |
| Chemeleon Crystal CLIP | [Nature Communications](https://www.nature.com/articles/s41467-025-59636-y) | 2025 | text-conditioned | paper reported | structure_match_rate | 0.20 | 20 | ok | contextual_only | General text prompts recover 20% of unseen ground-truth structures. |
| Chemeleon | [Nature Communications](https://www.nature.com/articles/s41467-025-59636-y) | 2025 | relaxation | TiO2 | relax_success_rate | 0.9818 |  | ok | contextual_only | 539 of 549 generated TiO2 polymorphs converged under MACE-MP. |
| Chemeleon | [Nature Communications](https://www.nature.com/articles/s41467-025-59636-y) | 2025 | stability | paper reported | predicted_ehull_threshold | 0.15 eV/atom |  | ok | contextual_only | Metastable threshold used for generated chemical spaces. |
| Chemeleon | [Nature Communications](https://www.nature.com/articles/s41467-025-59636-y) | 2025 | chemical-space generation | Li-P-S-Cl | stable_count | 17 |  | ok | not_comparable | Discovery count after hull workflow. |
| Chemeleon | [Nature Communications](https://www.nature.com/articles/s41467-025-59636-y) | 2025 | chemical-space generation | Li-P-S-Cl | metastable_count | 435 |  | ok | not_comparable | Discovery count after hull workflow. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | Perov-5 | structural validity | 1.00 |  | ok | contextual_only | Table 2 generation performance. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | Perov-5 | composition validity | 0.9859 |  | ok | contextual_only | Chemical plausibility, not prompt satisfaction. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | Perov-5 | COV-R / COV-P | 0.9945 / 0.9846 |  | ok | not_comparable | Dataset-distribution coverage metric. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | Carbon-24 | structural validity | 1.00 |  | ok | contextual_only | Table 2 generation performance. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | Carbon-24 | COV-R / COV-P | 0.9980 / 0.8308 |  | ok | not_comparable | Dataset-distribution coverage metric. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | MP-20 | structural validity | 1.00 |  | ok | contextual_only | Table 2 generation performance. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | MP-20 | composition validity | 0.8670 |  | ok | contextual_only | Chemical plausibility, not prompt satisfaction. |
| CDVAE | [arXiv PDF](https://arxiv.org/pdf/2110.06197) | 2022 | unconditional | MP-20 | COV-R / COV-P | 0.9915 / 0.9949 |  | ok | not_comparable | Dataset-distribution coverage metric. |
| MGB | [OpenReview PDF](https://openreview.net/pdf?id=K15Dqxm0ge) | 2026 | CSP_from_formula | Perov-5 / Carbon-24 / MP-20 / MPTS-52 | benchmark_protocol |  | 1 / 20 | needs_manual_check | not_comparable | Useful protocol pointer; exact rows need manual extraction. |
| AtomGPT | [arXiv HTML](https://arxiv.org/html/2405.03680v2) | 2024 | stability_prediction | JARVIS-Leaderboard formation-energy split | formation_energy_mae | 0.072 eV/atom |  | ok | not_comparable | Forward property-prediction metric, not generation validity. |

## How These Compare To Our Current 100-Prompt Result

Our current Skill-Loop-CSP / LLM-CSP run is best compared to text-conditioned instruction-following metrics only at a contextual level. It is not a direct MP-20, MPTS-52, CDVAE coverage, or DFT hull benchmark.

Current 100-prompt values:

- `parse_validity_rate = 1.00`
- `formula/composition satisfaction = 1.00`
- `pre_dft_validity_rate = 0.90`
- `bad_contact_rate = 0.10`
- `intent_satisfaction_score_mean = 0.81`
- `global uniqueness = 10/100`, with `10/10` target families represented
- Dedicated symmetry-intent benchmark: `space_group_exact_match_rate = 0.00`, `crystal_system_match_rate = 0.00`, `family_symmetry_compatible_rate = 0.00`, `mean_symmetry_score = 0.00`
- `stability and novelty = pending`

Most direct contextual anchors:

- CrysText and CrysText-RL are the closest in spirit for composition and space-group instruction following, but their prompt distribution and exact scoring protocol differ.
- Our dedicated space-group/symmetry benchmark is now measured and currently fails under the SCA symmetry-intent protocol; this should be presented as a method-development target, not as a direct CrysText comparison.
- Chemeleon validity/no-overlap is conceptually close to our `pre_dft_validity_rate`, though Chemeleon samples 20 structures per test prompt and uses its own structural validity filters.
- Lang2Str, CrysText MP-20 CSP, CrystaLLM benchmark, and CDVAE coverage rows require reference datasets and paper-specific evaluation protocols, so they should not be presented as direct wins/losses for the 100-prompt run.
- Stability comparators remain pending for us until generated structures are evaluated against a comparable MLIP or DFT hull workflow.
