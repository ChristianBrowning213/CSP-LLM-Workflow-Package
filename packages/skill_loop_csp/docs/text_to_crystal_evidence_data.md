# Text-to-Crystal Evidence Data

This note records the evidence basis for comparing the Skill-Loop-CSP workflow with direct text-to-crystal and CIF-token generation methods. It is a comparison frame, not a claim that this workflow outperforms those systems.

The central distinction is:

- CrystaLLM/AtomGPT-style systems generate crystal representations directly.
- Our system does not train an LLM to emit CIF tokens.
- Our system uses the LLM as a workflow/formulation controller over retrieval, SPP/POT packaging, QLIP validation/solve, novelty checking, and evaluator reporting.
- Our current evidence is not "better generation rate"; it is auditable workflow completion and truthful diagnostic behaviour.

Machine-readable companion data is stored in [text_to_crystal_evidence_data.json](/c:/Users/brown/Documents/GitHub/Skill-Loop-CSP/artifacts/text_to_crystal_evidence_data.json).

## Methods Included

| Method | Representation | Conditioning | Main evidence style |
|---|---|---|---|
| CrystaLLM | CIF text tokens | Composition and optional space group | Direct CIF generation validity, plausibility, novelty/diversity, selected ab initio validation |
| AtomGPT | Atomistic text and structure/property representations | Chemical, structural, property, and inverse-design prompts | Forward property prediction, inverse generation examples, downstream DFT checks |
| CrysText | Text-conditioned crystal generation representation | Text/material conditions and reported energy-above-hull conditioning | MP-20-style benchmark metrics, structure match rates, RMSE metrics |
| Fine-tuned LLMs generate stable inorganic materials as text | Text-encoded atomistic structures | Unconditional, infilling, and text-conditional generation | Physical-constraint adherence, energy-above-hull screening, selected DFT checks |
| AtomBench | Benchmark framing over generated atomic structures | Inverse-design benchmark tasks | Validity, plausibility, distributional, and downstream generative metrics |
| MatLLMSearch | Text/CIF/POSCAR-style crystal representations in LLM-guided search | Search objective and evolving candidate state | Stability-rate screening and DFT-verified examples |

Source URLs are listed in the JSON artifact. Exact competitor table values should be extracted from the final paper tables before any quantitative cross-method comparison.

## Our Suite Evidence

Source suite: `test_workdir/paper_smoke_suite_v1_calibrated/suite_summary.json`

| Metric | Value |
|---|---:|
| Total runs | 13 |
| Expected outcome passes | 13 |
| Expected outcome failures | 0 |
| Demonstrated completed supported cases | 3 |
| Expected partial or diagnostic controls | 10 |
| Completed cases with QLIP OPTIMAL | 3 |
| Completed cases marked non-novel/rediscovery | 3 |

### Completed Cases

| Run | Material | Final status | Workflow score | QLIP status | Novelty result | Solution artifact |
|---|---|---:|---:|---|---|---|
| `coas2_expected_complete` | CoAs2 | completed | 100 | OPTIMAL | non-novel / rediscovery | `test_workdir/paper_smoke_suite_v1_calibrated/coas2_expected_complete/_raw_run/execution/step_003_qlip_solve/solution.cif` |
| `catio3_expected_complete` | CaTiO3 | completed | 100 | OPTIMAL | non-novel / rediscovery | `test_workdir/paper_smoke_suite_v1_calibrated/catio3_expected_complete/_raw_run/execution/step_003_qlip_solve/solution.cif` |
| `batio3_expected_complete` | BaTiO3 | completed | 100 | OPTIMAL | non-novel / rediscovery | `test_workdir/paper_smoke_suite_v1_calibrated/batio3_expected_complete/_raw_run/execution/step_003_qlip_solve/solution.cif` |

These cases support the narrower claim that, for currently supported material systems, the workflow can complete the evidence chain:

`retrieval -> SPP/POT -> QLIP validation -> QLIP solve -> novelty check -> workflow evaluator`

They do not by themselves establish DFT stability, experimental synthesizability, or property optimisation success.

### Partial Diagnostic Cases

| Run | Material | Failed tool | Error code | Diagnostic value |
|---|---|---|---|---|
| `zns_expected_partial` | ZnS | qlip.validate_request | spp_request_ref_unavailable | Blocks before QLIP solve when SPP does not emit a solve-compatible request |
| `licoo2_expected_partial` | LiCoO2 | qlip.validate_request | spp_request_ref_unavailable | Preserves the intended material system and reports unsupported handoff |
| `tio2_expected_partial` | TiO2 | qlip.validate_request | spp_request_ref_unavailable | Shows no fake solve success for unsupported SPP/QLIP handoff |
| `zno_expected_partial` | ZnO | qlip.validate_request | spp_request_ref_unavailable | Reports failed tool and structured error code |
| `brcl_expected_partial` | BrCl | qlip.validate_request | spp_request_ref_unavailable | Negative-control evidence for missing compatible package |
| `cef3_expected_partial` | CeF3 | qlip.validate_request | spp_request_ref_unavailable | Negative-control evidence for missing compatible package |
| `al2o3_expected_partial` | Al2O3 | qlip.validate_request | spp_request_ref_unavailable | Calibrates a former expected-complete false positive as partial |
| `fe2o3_expected_partial` | Fe2O3 | qlip.validate_request | spp_request_ref_unavailable | Calibrates a former expected-complete false positive as partial |
| `generic_abo3_requires_concrete_composition` | ABO3 | spp.run_pipeline | non_concrete_formula | Blocks prototype notation unless a concrete composition is supplied |
| `not_in_crystaldb_unobtainium` | UnobtainiumO2 | qlip.validate_request | spp_request_ref_unavailable | Unsupported-material diagnostic control |

The partial cases are useful evidence because the workflow records what failed, where it failed, and why it did not proceed to a fabricated validation or solution artifact.

## Comparison Axes

| Axis | CrystaLLM-style direct generation | AtomGPT/CrysText-style inverse generation | Our workflow evidence |
|---|---|---|---|
| Input conditioning | Composition and optional space-group-style conditions | Text, property, structure, or benchmark conditioning | Natural-language goal plus explicit material system |
| Representation | CIF or atomistic text tokens | Atomistic text, crystal representations, learned model states | Tool requests and artifacts: retrieval outputs, SPP/POT metadata, QLIP request, solution CIF |
| Generation mechanism | LLM directly emits crystal representation | Model directly generates or predicts structures/properties | LLM controls workflow/formulation; QLIP solves the generated request |
| Output artifact | Generated CIF-like structures | Generated structures or benchmark predictions | Solver-backed solution CIF for completed cases; partial diagnostic report otherwise |
| Validity checking | Structure and composition validity metrics | Benchmark validity and property/structure checks | QLIP request validation plus evaluator requirement checks |
| Physical plausibility | Plausibility filters and ab initio validation examples | ML-potential, DFT, or property checks depending on method | Current evidence is QLIP-objective feasibility and artifact completeness; no DFT/property validation yet |
| Solver/optimisation role | No solver formulates the initial generated CIF | Often downstream screening or optimisation after generation | Solver validation and optimisation are central workflow stages |
| Novelty/rediscovery | Novelty/diversity usually reported as generation metrics | May report diversity, novelty, or distributional metrics | Novelty check is explicit; current completed cases are rediscoveries or close analogues |
| Failure diagnostics | Invalid generations can be counted, but no staged workflow failure applies | Failure reporting depends on benchmark/method | Failed tool, error code, warnings, and recommended next action are first-class outputs |
| Traceability/provenance | Generation logs and validation outputs where available | Model outputs and benchmark records | Full execution report, raw tool responses, workflow evaluation JSON/Markdown |
| Best-supported claim | Can generate plausible CIF-like structures under reported conditions | Can perform inverse or property-conditioned generation under reported benchmarks | Can complete an auditable retrieval/SPP/QLIP/novelty workflow for supported cases and truthfully diagnose unsupported cases |

## Evidence Categories Extracted

The current workflow evidence dataset records:

- Request interpretation and material-system propagation
- Retrieval execution
- SPP/POT package status
- QLIP validation status
- QLIP solve status
- Solution CIF artifact presence
- Novelty or rediscovery status
- Failed tool and error code for partial runs
- Trace/provenance availability
- Workflow evaluator score

## Metrics We Can Report Fairly

The current suite supports reporting:

- Workflow completion rate on supported cases
- Diagnostic correctness on unsupported cases
- QLIP validation/solve success rate for completed cases
- Novelty/rediscovery rate
- Trace completeness rate
- Evidence-chain completeness: retrieval -> SPP/POT -> QLIP validation -> solve -> novelty -> evaluator
- Number of artifacts per run and availability of full traces

The current suite should not report:

- Generation rate versus CrystaLLM, AtomGPT, CrysText, or related direct generators
- DFT stability comparison
- Property optimisation success

Those would require separate, explicit downstream experiments.

## Recommended Paper Wording

This project should be framed as a retrieval- and solver-backed text-to-crystal workflow. Unlike direct text/CIF generation methods, the LLM is not evaluated as a standalone crystal-token generator. It is evaluated as a controller that interprets a request, assembles evidence, formulates a QLIP-compatible optimisation request, validates and solves it when possible, checks novelty, and writes an auditable report.

A careful claim supported by the current evidence is:

> The workflow can produce solver-backed crystal candidates for demonstrated supported material systems, and produces explicit diagnostic reports for unsupported or underspecified inputs.

## Missing Evidence For Stronger Comparison

Stronger cross-method claims would require additional work:

- DFT relaxation or energy-above-hull checks for generated solution CIFs
- Property-predictor evidence if making property-conditioned claims
- Larger calibrated suite with more supported and unsupported material families
- Quantitative novelty/diversity analysis across many completed candidates
- Direct comparison protocol against published benchmark datasets, if claiming generative benchmark performance
- Table-level extraction of competitor metrics from final paper PDFs before numeric comparisons
