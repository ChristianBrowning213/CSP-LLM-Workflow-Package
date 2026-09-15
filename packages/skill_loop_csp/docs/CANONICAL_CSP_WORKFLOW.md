# Canonical Crystal-DB to IP-CSP workflow

## Scientific boundary

The language model produces a text/structured task specification; it does not create coordinates. Crystal-DB supplies ranked evidence. SPP-Maker-QLIP fits request-conditioned statistical guidance. The broad ICSD SPP is a separate regulator. A registered scaffold defines the finite representable search space. QLIP/IP-CSP selects a candidate. SCA, reference comparison, and CHGNet are post-generation evaluation only and cannot affect selection.

## One supported stage contract

| # | Stage | Canonical implementation / owner | Input | Output and artifacts | Configuration |
|---:|---|---|---|---|---|
| 1 | Request/task specification | `orchestrator.stages.intake.run_intake_stage` / Skill-Loop-CSP | text or structured task | task spec, run plan, clarification decision | workflow config + task |
| 2 | Corpus selection | `retrieval.corpus_router.route_corpus` / Skill-Loop-CSP | request, formula, holdout flag | resolved corpus ID/database and reason | `data/corpora/registry.json` |
| 3 | Retrieval | `crystal_db.retrieval.text_search` / Crystal-DB | query, resolved DB, Robocrys/BGE-M3 space | ranked IDs/scores and policy-gated CIF exports | `config/workflow/*.json` |
| 4 | Target exclusion | workflow structure-holdout policy / Skill-Loop-CSP | ranked retrieval and frozen reference identity | eligible ranked evidence + exclusion audit | paper config only when evaluation requires it |
| 5 | Evidence bundle | canonical deterministic evidence assembler | eligible ranked retrieval, required pairs | selected IDs/CIFs/ranks/reasons/pair counts/hash | evidence policy in workflow config |
| 6 | Request SPP fit | SPP-Maker-QLIP `spp.run_pipeline` and `spp.package_for_qlip` | evidence bundle CIF directory | versioned QLIP bundle and request POT root | request SPP config |
| 7 | Regulator load | QLIP `SPPCollection.load_regularisation` | configured broad POT tree | 3,388-pair loaded regulator/audit | environment-resolved regulator + manifest |
| 8 | Guidance combination | QLIP `SPPCollection.pair_cost_matrix`; independent `workflow.spp` | request/regulator roots, pairs, weights | request/regulator/combined coefficients | weights and 11 Å cutoff |
| 9 | Scaffold | QLIP scaffold registry and existing prototype/NASICON scaffold adapters | structured task | registered finite design space | scaffold registry version |
| 10 | Compile | QLIP core solve compiler | design space + combined SPP | Pyomo IP-CSP model | QLIP request |
| 11 | Solve | QLIP solve API | validated QLIP request | status, assignment, objective, certificates | solver config |
| 12 | Objective parity | `workflow.spp.score_spp_components` using QLIP primitives | selected structure and frozen POT roots | component scores and parity record | same cutoff/weights |
| 13 | CIF export | QLIP solution exporter | selected assignment | generated CIF + hash | run output root |
| 14 | SCA | `orchestrator.stages.verification.run_verification_stage` and SCA backend | generated CIF only | parse/formula/symmetry/contact/topology results | SCA config |
| 15 | Reference comparison | held-out evaluation adapter | generated CIF + frozen reference | StructureMatcher and lattice/volume metrics | frozen tolerances |
| 16 | CHGNet | external predictor/relaxation adapter | generated CIF | convergence and relaxed CIF; no stability claim | paper protocol when required |
| 17 | Relaxed SCA | same SCA configuration as stage 14 | relaxed CIF | post-relaxation SCA | same SCA config |
| 18 | Provenance | run logger/workflow result | all stage records | hashes, module/function paths, manifests | freeze config |

## Current gate status

The canonical implementation is frozen for the prospective paper benchmark. The unified `run_csp_workflow` API passed the 54-test canonical gate and complete live smokes for BaTiO3, CsPbBr3, and Na3Zr2Si2PO12. Those smokes exercised live retrieval, fresh request SPP fitting, the frozen broad regulator, pairwise fallback, authorized QLIP optimization, objective parity, CIF export, and installed SCA validation.

Paper-specific scripts and `experiments.paper_workflow` are historical implementations and are not supported production entrypoints.
