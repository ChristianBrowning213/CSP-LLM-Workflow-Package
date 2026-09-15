# 100-Case Regularised SPP Weight Optimisation

## Purpose

This sweep evaluated SPP and ICSD/global SPP regularisation weights for the
text-to-crystal workflow. The goal was to test whether ICSD/global SPP
regularisation plus soft-repulsive missing-pair handling improves contact
realism and solver completion while preserving semantic and motif alignment.

This is solver-backed, regularisation-audited, semantic/motif-evaluated
evidence. It is not physical validation, DFT validation, thermodynamic stability
evidence, synthesizability evidence, experimental validation, or discovery
evidence.

## Method

The experiment used the 100-case mixed-specificity prompt bank and the
QLIP/IP-CSP solver path. Each run combined:

- task/retrieval SPP guidance derived from the Crystal-DB/SPP workflow
- ICSD/global SPP regularisation from `C:\Users\brown\Downloads\SPP\SPP\SPP\SPP`
- soft-repulsive feedback for missing pairs not covered by either SPP source
- generated-CIF Robocrys descriptions
- deterministic rule-based Robocrys intent scoring
- live LLM Robocrys intent scoring via Ollama for selected configurations
- SPP objective audit sidecars
- shortest-contact diagnostics

The benchmark used a cubic lattice override with `a = 4.6`. This override is a
benchmark control surface and can distort some structure families, so results
should be interpreted as workflow/weight diagnostics rather than as physical
crystal validation.

## Objective Components

The intended objective structure is:

```text
total objective =
    task_spp_weight * retrieved/task SPP
  + regularisation_weight * ICSD-wide SPP regulariser
  + missing-pair soft_repulsive fallback where neither SPP source covers the pair
```

The retrieved/task SPP term acts as a query-specific soft template. The
ICSD/global SPP term acts as a broad contact-realism regulariser. The
`soft_repulsive` missing-pair mode is a fallback only, used when neither the
retrieved/task SPP nor the global regulariser covers a pair.

No hard prototypes, fixed Wyckoff templates, or fixed topology constraints are
introduced by this weighting setup.

## Configurations Tested

| Config | SPP guidance weight | Regularisation weight | Notes |
| ------ | ------------------: | --------------------: | ----- |
| A | 10.0 | 1.0 | Baseline from earlier live LLM run |
| B | 10.0 | 0.5 | Lower regularisation |
| C | 10.0 | 2.0 | Recommended current default |
| D | 30.0 | 1.0 | Higher task SPP weight |
| E | 30.0 | 2.0 | Higher task SPP and regularisation |
| F | 3.0 | 2.0 | Highest yield, contact-unsafe |

All configurations used `missing_pair_policy = soft_repulsive` for the
regularised sweep.

## Full Sweep Results

Rule-only ranking used:

```text
3.0 * final_cif_rate
+ 2.0 * qlip_optimal_rate
+ 2.0 * mean_rule_based_score
- 3.0 * short_contact_lt_1p5_rate
- 1.0 * short_contact_lt_1p8_rate
- 1.0 * infrastructure_failure_rate
```

| Config | Final CIF rate | QLIP optimal rate | Min contact | <1.5 A | <1.8 A | Mean rule score | Rule rank score |
| ------ | -------------: | ----------------: | ----------: | -----: | -----: | --------------: | --------------: |
| A | 0.78 | 0.78 | 1.626 | 0 | 11 | 0.263 | 4.286 |
| B | 0.71 | 0.71 | 1.150 | 1 | 8 | 0.259 | 3.928 |
| C | 0.82 | 0.82 | 1.626 | 0 | 12 | 0.270 | 4.490 |
| D | 0.75 | 0.75 | 1.626 | 0 | 9 | 0.265 | 4.160 |
| E | 0.80 | 0.80 | 1.626 | 0 | 12 | 0.267 | 4.384 |
| F | 0.87 | 0.87 | 1.150 | 1 | 15 | 0.278 | 4.696 |

The generated report artifacts are:

- `test_workdir\weight_optimisation_100_regularised\WEIGHT_OPTIMISATION_SUMMARY.md`
- `test_workdir\weight_optimisation_100_regularised\WEIGHT_OPTIMISATION_SUMMARY.json`
- `test_workdir\weight_optimisation_100_regularised\config_metrics.csv`
- `test_workdir\weight_optimisation_100_regularised\per_case_metrics.csv`
- `test_workdir\weight_optimisation_100_regularised\README.md`
- `test_workdir\weight_optimisation_100_regularised\LIVE_LLM_RESCORE_PLAN.md`

## Live LLM Rescore

Configs A, C, and F have live LLM Robocrys intent scoring. Configs C and F were
rescored in no-solve mode using existing generated outputs; QLIP validation and
solve were not rerun by the rescore mode.

| Config | Final CIF rate | Min contact | <1.5 A | <1.8 A | Mean rule | Mean LLM | LLM judged |
| ------ | -------------: | ----------: | -----: | -----: | --------: | -------: | ---------: |
| A | 0.78 | 1.626 | 0 | 11 | 0.263 | 0.219 | 78 |
| C | 0.82 | 1.626 | 0 | 12 | 0.306 | 0.246 | 82 |
| F | 0.87 | 1.150 | 1 | 15 | 0.315 | 0.257 | 87 |

Config F has the highest final CIF rate and highest mean LLM score, but it is
contact-unsafe because one solved case has a shortest contact below 1.5 A.

The unsafe case is:

- `challenge_069`
- `mgco3_magnesite`
- `MgCO3`
- shortest contact: `1.15 A`
- LLM judgement: `partially_correct`
- score: `0.56`

## Visual Summary

These plots summarize the benchmark diagnostics. They are documentation views
of solver-backed, regularisation-audited, semantic/motif-evaluated evidence;
they are not physical validation.

![Final CIF rate by config](assets/weight_optimisation_100_regularised/final_cif_rate_by_config.png)

Config F maximizes final-CIF yield, while Config C is annotated as the current
recommended default because it improves over Config A without introducing a
`<1.5 A` contact-safety failure.

![Short-contact warnings by config](assets/weight_optimisation_100_regularised/short_contact_warnings_by_config.png)

The short-contact plot separates warning-level `<1.8 A` contacts from hard
warning `<1.5 A` contacts. Configs B and F each have a `<1.5 A` contact-safety
failure; Config C has none.

![Rule rank score by config](assets/weight_optimisation_100_regularised/rule_rank_score_by_config.png)

The rule-only rank score favors Config F, but the rank is not sufficient for
default selection because Config F is contact-unsafe. Config C is selected as
the contact-safe default.

![Live LLM Robocrys intent alignment](assets/weight_optimisation_100_regularised/llm_alignment_rescored_configs.png)

The live LLM Robocrys-intent comparison shows Config F with the highest mean
LLM score and Config C improving over Config A. Config F remains high-yield but
contact-unsafe; Config C preserves the `<1.5 A = 0` gate.

![Yield versus contact-safety trade-off](assets/weight_optimisation_100_regularised/yield_vs_contact_safety_tradeoff.png)

The scatter plot shows the yield/contact-safety trade-off. Config F has high
yield but more warning contacts and one `<1.5 A` failure. Config C has good
yield and no `<1.5 A` failure.

![Recommended config summary](assets/weight_optimisation_100_regularised/recommended_config_summary.png)

The compact A/C/F summary highlights the default-selection logic: Config C is
the current default, while Config F should be treated as experimental until its
short-contact failure is understood.

## Recommendation

Recommended current default:

```text
spp_guidance_weight = 10.0
regularisation_weight = 2.0
missing_pair_policy = soft_repulsive
```

This corresponds to Config C. Config C is recommended because it improves final
CIF rate and live LLM semantic/motif alignment over Config A while preserving a
cleaner contact-safety profile with zero `<1.5 A` contacts.

Config F should not be used as the default yet. It is useful as a high-yield
experimental setting, but the `challenge_069 / MgCO3 / magnesite` short-contact
failure must be audited before treating it as a safe default.

## Contact-Safety Interpretation

Shortest-contact diagnostics are used as a default-selection guard:

- `<1.5 A` contacts are hard warnings and disqualify a configuration from
  default selection until the case is audited.
- `<1.8 A` contacts are warning-level diagnostics.

Config C has zero `<1.5 A` contacts. Config F has one `<1.5 A` contact and
therefore remains contact-unsafe despite its higher yield.

Earlier 5-case regularisation evidence showed that regularisation loaded
successfully, with 3388 POT pairs available, and did not show an obvious
1.15 A-style contact in the paired loose/specific run. In that smaller run,
loose design intent scored better than specific structural intent, suggesting
that motif/topology reconstruction remains weaker than broad pair-distance
realism.

## Limitations

- Semantic/motif alignment scores remain low overall.
- Live LLM judging is slow and should be used selectively.
- Motif and topology reconstruction remain weaker than broad contact realism.
- The cubic lattice override may distort some families.
- The ICSD/global SPP regulariser improves contact diagnostics but does not
  prove physical correctness.
- These results do not establish DFT stability, thermodynamic stability,
  synthesizability, experimental validation, or material discovery.

## Next Steps

1. Audit `challenge_069 / MgCO3 / magnesite` under Config F.
2. Add a contact-safety veto or stronger fallback for unsafe contacts.
3. Investigate soft motif/coordination guidance without hard templates.
4. Use Config C as the current default for medium-size evidence runs.
5. Use Config F only with contact-safety checks.
6. Update benchmark and paper-evidence docs when this default is adopted in
   run presets.
