# Full 100 Guided SPP Benchmark Comparison

This document summarizes the full 100-prompt guided SPP / Skill-Loop-CSP benchmark and places it in context with sourced crystal-generation literature comparators. It uses the existing evaluation artifacts under:

`local_runs/full_100_intent_benchmark_seeded_20260626_guided_spp_jsonschema_fixed`

Key source artifacts:

- `reports/FULL_100_INTENT_BENCHMARK_SUMMARY.json`
- `sun_benchmark_v2/sun_summary.json`
- `symmetry_intent_benchmark/symmetry_summary.json`
- `symmetry_intent_benchmark/symmetry_report.md`
- `symmetry_intent_benchmark/SYMMETRY_FAILURE_DIAGNOSIS.md`
- `symmetry_intent_benchmark/QLIP_SYMMETRY_INPUT_DIAGNOSIS.md`
- `symmetry_intent_benchmark_sensitivity/SYMMETRY_SENSITIVITY_SUMMARY.md`
- `../symmetry_wiring_prototype_scaffold_smoke_20260704/SMOKE_TEST_REPORT.md`
- `stability_chgnet_static/STABILITY_CHGNET_STATIC_REPORT.md`
- `stability_chgnet_static/chgnet_static_summary.json`
- `stability_chgnet_relax/STABILITY_CHGNET_RELAX_REPORT.md`
- `stability_chgnet_relax/chgnet_relax_summary.json`
- `sun_benchmark_with_reference/NOVELTY_PENDING.md`
- `traceability_gap_analysis.md`
- `reports/LITERATURE_COMPARISON_REPORT_v4.md`
- `reports/LITERATURE_COMPARISON_REPORT_v4.json`
- `docs/paper_comparator_evidence.md`
- `data/paper_comparators/crystal_generation_comparators.csv`

## Executive Summary

The current 100-prompt guided SPP run shows strong basic generation control and useful auditability: all 100 generated CIFs parse, all satisfy the requested formula/composition, and 90% pass the current pre-DFT validity screen. The mean composite intent score is 0.810, and the S.U.N. pass finds 10 unique structures across 100 outputs, corresponding to all 10 requested target families being represented.

The new dedicated symmetry-intent benchmark sharpens the interpretation. Although formula and coarse family control are strong, the generated CIFs do not currently satisfy requested space-group, crystal-system, or family-compatible symmetry constraints under the dedicated `SpacegroupAnalyzer` pass at `symprec=0.01` and `angle_tolerance=5`. All 100 CIFs are parseable, but the space-group exact match rate, crystal-system match rate, family symmetry-compatible rate, and mean symmetry score are all 0.000.

CHGNet static energy/force is now computable for all 100 generated CIFs as a surrogate MLIP pre-DFT screen. The median static CHGNet energy is approximately -0.924 eV/atom, but the median max force is 7.187 eV/A and the mean max force is 12.015 eV/A, with a maximum of 38.826 eV/A. Those force values reinforce the geometry diagnosis: several candidates are not relaxation-ready without repair or stronger construction constraints. A 10-representative CHGNet relaxation pass was attempted, but CHGNet is unavailable in the current active Python environment, so no relaxation claims are made.

This means the current system is best described as formula- and geometry-guided text-to-CSP with traceable execution, not yet symmetry-constrained or stability-validated CSP. That is a useful benchmark discovery: it turns symmetry control and relaxation readiness from assumed properties into measured method-development targets.

## Benchmark Scope

- 100 text-intent prompts.
- 10 target crystal families.
- 10 prompt variants per family.
- Skill-Loop-CSP generation followed by SCA evaluation.
- One generated CIF per prompt in this run.
- Evaluation includes direct CIF quality, deterministic intent satisfaction, S.U.N. uniqueness/novelty/stability screening, unique/verifiable-CSP traceability scoring, sourced literature-context comparison, and the dedicated symmetry-intent benchmark.

The 10 target families are:

- argyrodite
- fluorite
- halide perovskite
- layered oxide
- nitride
- olivine phosphate
- perovskite
- pyrite
- rocksalt
- spinel

## Main Result Table

| Area | Metric | Value | Interpretation |
| --- | --- | ---: | --- |
| Direct quality | `parse_validity_rate` | 1.000 | All generated CIFs parse. |
| Direct quality | formula/composition satisfaction | 1.000 | Formula control is strong across the 100 prompts. |
| Direct quality | `pre_dft_validity_rate` | 0.900 | 90% pass current pre-DFT validity checks. |
| Direct quality | `bad_contact_rate` | 0.100 | 10% retain bad contacts or contact-like geometry failures. |
| Intent | `intent_satisfaction_score_mean` | 0.810 | Composite score; it mixes formula, family, symmetry/system, motif, contact, and solver-status checks. |
| S.U.N. | global uniqueness | 10/100 | Ten unique structure clusters among 100 outputs. |
| S.U.N. | target-family coverage | 10/10 | The uniqueness result reflects repeated structures within each family, not collapse into one cross-target structure. |
| S.U.N. | stability | not_computable | No DFT/MLIP hull or comparable energy input supplied. |
| S.U.N. | novelty | not_checked/not_computable | No global reference corpus supplied for novelty checking. |
| Traceability | `traceable_constraint_grounded_csp_score` | 0.253 | Partial traceable-CSP evidence exists, but constraint/solver/certificate fields are incomplete. |
| Traceability | `audit_bundle_score` | 0.528 | Audit artifacts are present enough to inspect, but not yet complete. |
| Literature comparison | comparator evidence rows | 37 rows | Used for contextual comparison only, with 4 rows marked `needs_manual_check`. |
| CHGNet static | `chgnet_ok_rate` | 1.000 | Static CHGNet proxy ran on all 100 CIFs in the existing static artifact. |
| CHGNet static | median energy per atom | -0.924 eV/atom | Surrogate MLIP diagnostic only, not DFT stability or hull energy. |
| CHGNet static | median max force | 7.187 eV/A | High enough to indicate relaxation-readiness issues. |
| CHGNet static | max force | 38.826 eV/A | Severe high-force outliers are present. |
| CHGNet relax | unique representatives | 10 | One representative per target formula/family was selected. |
| CHGNet relax | status | unavailable | Relaxation did not run in this environment because CHGNet is unavailable to the active Python environment. |
| Symmetry intent | `declared_p1_rate` | 1.000 | All CIFs declare P1, likely partly reflecting export behavior. |
| Symmetry intent | `analyzed_p1_rate` | 0.500 | Half analyze as P1 even after symmetry detection. |
| Symmetry intent | `space_group_exact_match_rate` | 0.000 | No generated CIF matches its requested analyzed space group. |
| Symmetry intent | `crystal_system_match_rate` | 0.000 | No generated CIF matches the requested crystal-system target under this benchmark. |
| Symmetry intent | `family_symmetry_compatible_rate` | 0.000 | No generated CIF reaches the transparent family-compatibility heuristic. |
| Symmetry intent | `symmetry_mismatch_rate` | 1.000 | All 100 rows are symmetry mismatches. |
| Symmetry intent | `mean_symmetry_score` | 0.000 | Symmetry control is not yet achieved. |

## Direct CIF Quality

The direct quality screen is strong at the basic structural-file level. All 100 CIFs parse, and formula/composition satisfaction is 1.000. This is a meaningful result: the system can produce syntactically usable CIFs with the requested chemical formula across a broad, deliberately varied prompt set.

The pre-DFT validity rate is 0.900, with a bad-contact rate of 0.100. That means the workflow is not merely writing valid text files; most structures also pass the current geometry/contact checks. The remaining 10% are concrete repair targets for geometry cleanup, local relaxation, or stricter rejection before final output.

## CHGNet Static Proxy

The CHGNet static pass produced records for 100/100 generated CIFs in `stability_chgnet_static/chgnet_static_results.csv`. The report in `stability_chgnet_static/STABILITY_CHGNET_STATIC_REPORT.md` summarizes this as an MLIP surrogate pre-DFT screen.

Key values:

| Metric | Value |
| --- | ---: |
| total rows | 100 |
| `chgnet_ok_rate` | 1.000 |
| median CHGNet energy per atom | -0.924 eV/atom |
| mean CHGNet energy per atom | -1.103 eV/atom |
| min / max CHGNet energy per atom | -3.381 / 1.047 eV/atom |
| median max force | 7.187 eV/A |
| mean max force | 12.015 eV/A |
| max force | 38.826 eV/A |

High-force families are flagged in the static report. The clearest examples are BaTiO3, CsPbBr3, and Li6PS5Cl, with Li6PS5Cl also carrying the bad-contact/pre-DFT-validity failure pattern. These are not DFT stability results. They are useful because they show which formula/family representatives are geometrically strained under a learned interatomic potential before any expensive first-principles workflow.

CHGNet static energy/force is a surrogate pre-DFT screen and not a DFT stability or energy-above-hull claim.

## CHGNet Relaxation

A unique-representative manifest was built at `stability_chgnet_relax/unique_representatives_manifest.csv` with 10 rows, one per target formula/family. The manifest preserves CIF path, formula, family, prompt ID, method, run index, attempt ID, and existing static diagnostic fields. It also includes `target_cif_path = cif_path` so the existing relaxation evaluator can report before/after self-match diagnostics without treating the input as an external ground truth.

The requested relaxation command wrote `stability_chgnet_relax/chgnet_relax_unique_results.csv` and `.jsonl`, but every row was skipped because CHGNet is unavailable in the current active Python environment. The relaxation summary is therefore:

| Metric | Value |
| --- | ---: |
| representatives | 10 |
| relax ok count | 0 |
| relax ok rate | 0.000 |
| status | unavailable |

The report in `stability_chgnet_relax/STABILITY_CHGNET_RELAX_REPORT.md` records the failure explicitly. No relaxed-force, energy-drop, convergence, or relaxed-CIF claims are inferred from the static results.

## Intent-Following

The original `intent_satisfaction_score_mean = 0.810` is a composite metric. It is useful as a broad health score, but it should not be read as proof that every intent dimension is solved. In this run, formula/composition control is strong, and target-family representation is broad. Symmetry intent, however, fails under the dedicated analysis described below.

The practical interpretation is:

- The system controls formula/composition well.
- The system often produces parseable and mostly pre-DFT-valid structures.
- The aggregate intent score hid a major unresolved subproblem: requested symmetry is not being enforced.

## Symmetry-Intent Benchmark

The dedicated symmetry-intent benchmark answers a narrower question than the composite intent score:

Did the generated CIF have the requested space group, requested crystal system, or prototype-compatible symmetry?

Measured values:

| Metric | Value |
| --- | ---: |
| `total_rows` | 100 |
| `parseable_rows` | 100 |
| `declared_p1_rate` | 1.000 |
| `analyzed_p1_rate` | 0.500 |
| `space_group_exact_match_rate` | 0.000 |
| `crystal_system_match_rate` | 0.000 |
| `family_symmetry_compatible_rate` | 0.000 |
| `symmetry_mismatch_rate` | 1.000 |
| `mean_symmetry_score` | 0.000 |

All CIFs declare P1. That may partly be a CIF export or writing convention rather than a complete statement about the underlying geometry. The analyzer result is therefore the more important check: with `SpacegroupAnalyzer`, half of the structures still analyze as P1, and none match the requested target space group, crystal system, or family-compatible symmetry heuristic.

This is a real method-development signal. The current system is formula- and geometry-guided CSP, not yet symmetry-constrained CSP. It can produce plausible formula-controlled structures, but it is not yet constructing structures on the requested space-group/prototype manifold.

The diagnostic report `symmetry_intent_benchmark/SYMMETRY_FAILURE_DIAGNOSIS.md` separates two issues. First, all CIFs declare P1, which is partly an export/declaration issue. Second, the analyzed geometries still fail the requested symmetry checks: half analyze as P1 and all miss the target symmetry criteria. The sensitivity report `symmetry_intent_benchmark_sensitivity/SYMMETRY_SENSITIVITY_SUMMARY.md` shows the failure is robust across `symprec = 0.001, 0.01, 0.1`; exact SG, crystal-system, and family-compatible rates remain zero.

Symmetry diagnosis indicates whether target symmetry is currently metadata-only, request-only, weak template-only, active constraint bug, or export loss.

A later 3-case wiring/prototype-scaffold smoke test is recorded at `local_runs/symmetry_wiring_prototype_scaffold_smoke_20260704`. It moves BaTiO3, NiO, and CeO2 symmetry metadata into structured Skill-Loop-CSP task specs, QLIP `problem.symmetry` / `problem.prototype`, `symmetry_trace.json`, and `prototype_scaffold` candidate-site mode. It is not a replacement for the full benchmark and does not claim symmetry enforcement: SCA symmetry checks on the three smoke outputs still report zero exact space-group, crystal-system, and family-compatible matches.

## S.U.N.

The S.U.N. evaluation finds 10 unique structures among 100 generated CIFs, for a global uniqueness rate of 0.100. That should be interpreted alongside target-family coverage: all 10 target families are represented. The result is not a collapse into one universal structure across all prompts. It is better understood as repeated or highly similar outputs within each target family.

Stability and novelty remain pending:

- Stability is `not_computable` because no DFT hull, predicted energy-above-hull, formation-energy, or comparable static-energy input was supplied.
- Novelty is `not_checked/not_computable` because no global reference corpus was supplied.

This keeps the S.U.N. result honest: uniqueness is measured, but stable-and-novel discovery is not yet claimed.

No expected reference manifest was found under `reference_sets/crystal_db_snapshot/metadata.csv`, `reference_sets/mp20/metadata.csv`, or `reference_sets/materials_project_snapshot/metadata.csv`. The pending instructions are written to `sun_benchmark_with_reference/NOVELTY_PENDING.md`. Reference sets should be used only for evaluation-only novelty checking unless explicitly testing retrieval contamination.

## Literature Comparison

The literature comparison uses the sourced evidence table in `data/paper_comparators/crystal_generation_comparators.csv` and the rendered report in `reports/LITERATURE_COMPARISON_REPORT_v4.md`. It is comparison context, not a leaderboard claim. Version 4 includes the symmetry-intent summary and CHGNet MLIP surrogate summary.

### Contextual Anchors

CrysText/CrysText-RL is the closest conceptual comparator for text-conditioned composition and space-group prompting. The sourced evidence includes CrysText composition+space-group satisfaction rows, but CrysText composition-only and space-group-only rows remain marked `needs_manual_check`. Our new dedicated symmetry benchmark should be compared to those rows only contextually, because prompt distributions and scoring protocols differ.

Chemeleon and CrystaLLM provide useful context for text-conditioned generation, validity, and structure recovery, but their evaluation settings differ. CDVAE provides context for validity and coverage in unconditional generation. These systems often optimize distributional validity, coverage, and structure-match metrics over benchmark datasets.

### Not Comparable Without Reference CIFs

Lang2Str MP-20/MPTS-52 match rates and RMSE, CrysText MP-20 N=1/N=20 match rates and RMSE, CDVAE coverage metrics, and CrystaLLM benchmark rows require reference structures and exact dataset protocols. The current 100-prompt run is not an MP-20 or MPTS-52 leaderboard run, and it should not be described as beating those structure-match metrics.

### Not Computable Without Stability, Hull, Or Relaxation Inputs

Chemeleon stability/metastability counts, relaxation/convergence results, and AtomGPT formation-energy MAE are not directly comparable to this run. Our stability and formation-energy fields are not populated, and no equivalent DFT/MLIP hull workflow has been run.

### Manual-Check Rows

Rows marked `needs_manual_check` remain caution rows. They are useful reminders for future source extraction, but they are not claims and should not be used as quantitative comparison points.

## Unique Verifiable-CSP Contribution

The unique/verifiable-CSP layer is the main methodological contribution separate from raw crystal-generation metrics. It asks whether a generated structure is part of a traceable, inspectable CSP workflow rather than only asking whether a final CIF looks plausible.

The relevant dimensions are:

- Retrieval grounding: whether prompts and generated structures are connected to explicit supporting evidence.
- Constraint traceability: whether formula, family, symmetry, geometry, and other constraints can be traced through the workflow.
- Solver certificate: whether the solver or constructive step leaves evidence that the constraints were actually enforced.
- Audit bundle completeness: whether prompt, retrieval, solver, generated CIF, validation, diagnostics, and decision artifacts can be inspected after the run.
- Reproducibility: whether enough environment and configuration metadata exists to repeat or diagnose the run.

Current traceability scores are partial: `traceable_constraint_grounded_csp_score = 0.253` and `audit_bundle_score = 0.528`. This is enough to make failures inspectable, but not enough to claim complete traceable CSP execution.

The traceability gap report is `traceability_gap_analysis.md`. The most common missing converted-bundle artifacts are `structured_intent`, `constraint_trace`, `validation_trace`, and `diagnostics_trace`, each missing across the converted run bundles. The next archive-writing step is to persist structured intent, retrieval traces, evidence records, SPP traces, constraint traces, solver request/result payloads, validation reports, final decisions, run configuration, and environment metadata as explicit files, including honest skipped/status files when a stage does not run.

## Limitations

- No DFT stability evaluation has been run.
- CHGNet static was run as a surrogate MLIP screen, but this is not DFT and not an energy-above-hull calculation.
- CHGNet relaxation on 10 unique representatives was attempted but unavailable in the active environment; no relaxation convergence claim is made.
- No exact MP-20 or MPTS-52 leaderboard protocol has been run.
- No global novelty reference set has been supplied.
- No symmetry-constrained generation has been achieved yet.
- The current symmetry failure is measured at `symprec=0.01` and `angle_tolerance=5`; tolerance sensitivity can be explored, but the present result is already decisive enough to guide method development.
- The literature comparison is contextual and source-audited, but several rows remain `needs_manual_check`.

## Next Method-Development Target

The next technical target is symmetry-constrained CSP. The benchmark points to specific implementation directions:

- Prototype-template seeding: initialize candidates from family-appropriate prototype templates rather than unconstrained cell/site guesses.
- Wyckoff-position candidate generation: generate sites using allowed Wyckoff positions for the requested space group.
- Symmetry-orbit IP variables: represent equivalent atom orbits explicitly in the integer/constraint model.
- Symmetry-aware post-processing and rejection: analyze candidate symmetry after generation and reject or repair structures that fall off the target manifold.
- Symmetry objective/penalty: include a score term that rewards exact space-group, crystal-system, or family-compatible symmetry before final CIF selection.

These changes would move the workflow from formula- and geometry-guided generation toward true symmetry-constrained CSP.

## Final Claim

The full 100-prompt guided SPP benchmark demonstrates a real and useful capability: controlled text-to-CIF generation with strong formula satisfaction, complete parse validity, mostly acceptable pre-DFT geometry, broad target-family coverage, and an auditable evaluation stack. It should not be claimed as an MP-20/MPTS-52 leaderboard result, a stability/novelty discovery run, or a solved symmetry-conditioned generator. The strongest honest claim is that SCA now exposes the workflow clearly enough to separate what works from what does not: formula control works, geometry quality is promising but imperfect, traceability is partially present, and symmetry control is the next concrete technical frontier.
