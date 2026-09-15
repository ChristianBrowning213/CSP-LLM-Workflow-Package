# Paper Workflow Presentation

## 1. Evaluation Framing

This evaluation frames Skill-Loop-CSP as a text-to-crystal workflow system, not as a direct CIF-token generator and not as a classical CSP baseline comparison. The central claim is:

> The system does not directly generate CIF tokens. It controls a retrieval-grounded, SPP-guided, QLIP-optimised workflow and records whether each stage completed or failed truthfully.

The evidence therefore focuses on workflow traceability: whether the input request was interpreted as a concrete material target, whether Crystal-DB retrieval produced usable corpus evidence, whether SPP/POT guidance was available, whether QLIP validation and solve completed, whether a solution CIF was produced, whether novelty/rediscovery was assessed, and whether partial runs reported an exact failed stage rather than fabricating success.

The calibrated paper smoke suite contains 13 runs. All 13 matched their expected outcome: 3 completed supported examples and 10 partial or diagnostic controls.

## 2. Comparison to CrystaLLM / AtomGPT

CrystaLLM-style systems directly model crystal representations as text, for example autoregressive generation over CIF tokens conditioned on composition and, optionally, space group. AtomGPT and CrysText-style systems similarly focus on direct or inverse generation from text, property, or benchmark conditioning, then evaluate generated structures using validity, plausibility, structure-match, property, or downstream screening metrics.

Skill-Loop-CSP has a different evidence style. The LLM is not trained to emit CIF text. It acts as a workflow/formulation controller that connects:

1. natural-language request interpretation,
2. Crystal-DB retrieval,
3. SPP/POT guidance,
4. QLIP request validation,
5. QLIP optimisation,
6. novelty/rediscovery checking,
7. final workflow evaluation.

This is complementary to direct text-to-crystal generation. The present evidence does not claim better generation rate, DFT stability, or property optimisation. It claims auditable completion for supported cases and truthful diagnostic behaviour for unsupported cases.

## 3. Workflow Evidence Suite

The calibrated suite summary is stored at:

`test_workdir/paper_smoke_suite_v1_calibrated/suite_summary.json`

Summary:

- Runs: 13
- Expected-outcome passes: 13
- Expected-outcome failures: 0
- Completed supported cases: CoAs2, CaTiO3, BaTiO3
- Partial/diagnostic controls: ZnS, LiCoO2, TiO2, ZnO, BrCl, CeF3, Al2O3, Fe2O3, ABO3, UnobtainiumO2
- Completed-case QLIP status: `OPTIMAL` for all 3 completed cases
- Completed-case novelty outcome: rediscovery/non-novel for all 3 completed cases

| Case | Input | Crystal-DB corpus | SPP/POT source | QLIP status | Final output | Diagnostic |
|---|---|---|---|---|---|---|
| CoAs2 | Generate a CoAs2 safflorite-like arsenide candidate using retrieved analogues, SPP guidance, QLIP optimisation, and novelty checking. | 10 semantic neighbours; 1 CIF exported for SPP; corpus panel VESTA-rendered. | Rendered POT curves for As-As, As-Co, Co-Co from SPP root. | `OPTIMAL` | VESTA-rendered solution CIF; objective -2.2628; novelty rediscovery/non-novel. | Completed; workflow score 100. |
| CaTiO3 | Generate a CaTiO3 perovskite-like oxide candidate using retrieved analogues, SPP guidance, QLIP optimisation, and novelty checking. | 10 semantic neighbours; 1 CIF exported for SPP; corpus panel VESTA-rendered. | Rendered POT curves for Ca-Ca, Ca-O, Ca-Ti, O-O, O-Ti, Ti-Ti. | `OPTIMAL` | VESTA-rendered solution CIF; objective -9.0422; novelty rediscovery/non-novel. | Completed; workflow score 100. |
| BaTiO3 | Generate a BaTiO3 perovskite-like oxide candidate using retrieved analogues, SPP guidance, QLIP optimisation, and novelty checking. | 10 semantic neighbours; 1 CIF exported for SPP; corpus panel VESTA-rendered. | Rendered POT curves for Ba-Ba, Ba-O, Ba-Ti, O-O, O-Ti, Ti-Ti. | `OPTIMAL` | VESTA-rendered solution CIF; objective -8.0380; novelty rediscovery/non-novel. | Completed; workflow score 100. |
| ZnS | Attempt ZnS workflow and stop truthfully when blocked. | Retrieval and SPP executed. | No solve-compatible request ref. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |
| LiCoO2 | Attempt LiCoO2 workflow and stop truthfully when blocked. | Retrieval and SPP executed. | No solve-compatible request ref. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |
| TiO2 | Attempt TiO2 workflow and stop truthfully when blocked. | Retrieval and SPP executed. | No solve-compatible request ref. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |
| ZnO | Attempt ZnO workflow and stop truthfully when blocked. | Retrieval and SPP executed. | No solve-compatible request ref. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |
| BrCl / CeF3 | Missing compatible SPP/POT handoff controls. | Retrieval and SPP executed. | Missing compatible request generation. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |
| Al2O3 / Fe2O3 | Calibrated false-positive controls. | Static evidence exists, but configured run does not prove solve-compatible handoff. | No solve-compatible request ref. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |
| ABO3 | Prototype-pattern request without concrete A/B elements. | Retrieval begins, but material is not concrete. | SPP blocks before QLIP handoff. | Not run | No fake solution CIF. | `spp.run_pipeline` blocked with `non_concrete_formula`. |
| UnobtainiumO2 | Unsupported/non-indexed material control. | Unsupported retrieval/handoff path. | No solve-compatible request ref. | Not run | No fake solution CIF. | `qlip.validate_request` blocked with `spp_request_ref_unavailable`. |

## 4. Hero Workflow Figure: CoAs2

![CoAs2 workflow artifact](../test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_coas2.png)

**Figure caption.** Workflow artifact generated after execution. The panels show the input request, retrieved Crystal-DB corpus, SPP/POT pair guidance, QLIP optimisation landscape, and final VESTA-rendered CIF. Detailed provenance is stored in the manifest.

Evidence from the CoAs2 figure manifest:

- Crystal-DB corpus panel: VESTA-rendered exported CIF from 10 semantic neighbours.
- SPP/POT panel: rendered curves for As-As, As-Co, and Co-Co.
- QLIP panel: schematic objective landscape, explicitly marked schematic because no solver trajectory samples were available.
- Final crystal panel: VESTA-rendered solution CIF.
- QLIP status: `OPTIMAL`.
- Novelty: rediscovery/non-novel.
- Manifest: `test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_coas2_manifest.json`

## 5. Additional Completed Cases: CaTiO3 / BaTiO3

![CaTiO3 workflow artifact](../test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_catio3.png)

CaTiO3 completed with QLIP status `OPTIMAL`, VESTA-rendered final CIF, rendered SPP/POT curves for the six required Ca/Ti/O pairs, and novelty reported as rediscovery/non-novel.

![BaTiO3 workflow artifact](../test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_batio3.png)

BaTiO3 completed with QLIP status `OPTIMAL`, VESTA-rendered final CIF, rendered SPP/POT curves for the six required Ba/Ti/O pairs, and novelty reported as rediscovery/non-novel.

The retrieved-corpus panels are deliberately provenance-oriented. They show semantic neighbours and distinguish exported CIF evidence from metadata-only neighbours in the sidecar tables:

- `test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_coas2_semantic_neighbours.md`
- `test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_catio3_semantic_neighbours.md`
- `test_workdir/paper_evidence_pack_v1/figures/workflow_artifact_batio3_semantic_neighbours.md`

## 6. Diagnostic Controls

The diagnostic controls are part of the evidence, not failed examples to hide. For unsupported or underspecified inputs, the workflow stops before fabricating a QLIP solve.

Examples:

- `ABO3` blocks with `non_concrete_formula`, because ABO3 is a prototype pattern rather than a concrete composition.
- `ZnS`, `LiCoO2`, `TiO2`, and `ZnO` block at `qlip.validate_request` with `spp_request_ref_unavailable` when SPP does not emit a solve-compatible QLIP request.
- `Al2O3` and `Fe2O3` were calibrated from expected-complete false positives to expected partial controls because configured-run evidence did not prove solve-compatible SPP handoff.
- `UnobtainiumO2` provides an unsupported-material control and does not produce a fake solution.

This behaviour supports the paper claim that the workflow can produce solver-backed candidates for supported material systems and explicit diagnostic reports for unsupported inputs.

## 7. What the Figures Prove

The workflow artifacts prove that the completed examples are not just free-form text outputs. Each figure is a post-run artifact assembled from recorded execution evidence:

- the original text request and target material,
- Crystal-DB retrieval metadata and exported corpus CIF evidence,
- SPP/POT pair guidance rendered from POT files,
- a QLIP optimisation panel labelled as schematic when no real trajectory exists,
- the final solution CIF rendered through the QLIP/VESTA path,
- manifest-backed provenance for every panel.

They also prove the current limitation honestly: the completed examples are rediscoveries or close analogues under the novelty checker, not new validated materials.

## 8. Limitations

- The workflow does not yet report DFT stability, energy-above-hull, or property optimisation success.
- The QLIP optimisation landscape panel is schematic unless real solver trajectory/candidate samples are recorded.
- Novelty is structural/fingerprint based; it is not experimental validation.
- Semantic retrieval evidence does not by itself prove target-property satisfaction.
- The completed suite currently demonstrates solver-backed workflow completion for three supported examples, not broad benchmark superiority over CrystaLLM, AtomGPT, CrysText, or related direct generators.
- Partial controls indicate missing or unsupported handoff conditions truthfully; they should be presented as diagnostic evidence, not as generated crystals.
