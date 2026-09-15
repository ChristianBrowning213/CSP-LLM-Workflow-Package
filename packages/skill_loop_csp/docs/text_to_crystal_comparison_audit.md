# Text-to-Crystal Comparison Audit

## Comparison Frame

This project should be compared as a text-to-crystal workflow system, not as a direct CIF-token generator. Direct text-to-crystal methods typically train or prompt models to emit crystal representations directly from text, composition, space-group conditions, CIF tokens, structure strings, or property prompts.

Our system uses the LLM differently: the LLM does not directly generate CIF tokens. It acts as a workflow and formulation controller that routes a text request through retrieval, SPP/POT guidance, QLIP validation and solve, novelty checking, and evaluator reporting.

## Direct Text-to-Crystal / CIF-Token Generation Methods

CrystaLLM is best framed as autoregressive CIF-language generation, with conditioning such as composition or space group in some settings, followed by plausibility and ab initio validation. Citation placeholder: CrystaLLM paper / repository URL.

AtomGPT is best framed as an atomistic generative transformer for text, structure, and property tasks. In inverse-design settings, it can generate structures from property or text-like representations and then use downstream screening or optimisation. Citation placeholder: AtomGPT paper / repository URL.

CrysText appears relevant as text-conditioned crystal generation or text-to-crystal representation work if included in the final related-work set. Citation placeholder: CrysText paper URL.

MatLLMSearch appears relevant as LLM-guided materials search rather than purely direct CIF generation. Citation placeholder: MatLLMSearch paper URL.

SLICES and related inverse-representation methods are adjacent rather than exact baselines: they define structure encodings useful for generation or reconstruction, but are not the same as an audited multi-tool workflow. Citation placeholder: SLICES paper URL.

## How They Present Evidence

Direct generators usually emphasize representation validity, structural plausibility, novelty/diversity, property or energy screening, and sometimes DFT relaxation or ab initio validation. Their evidence often centers on generated structure quality and benchmark metrics over samples.

That evidence style is appropriate for direct representation generation, but it does not test whether a workflow faithfully interpreted a user request, used retrieved evidence, produced an auditable solver formulation, validated the request, or stopped honestly when a run lacked sufficient evidence.

## How Our Workflow Should Present Evidence

Our evidence should emphasize:

- The original text request and concrete material system.
- Retrieval execution and exported structural evidence.
- SPP/POT package status, pair coverage, missing pairs, and POT-root compatibility.
- QLIP request validation before solve.
- QLIP solve status and objective value when solved.
- Solution CIF artifact existence when solved.
- Novelty or rediscovery result when novelty checking runs.
- Traceable report artifacts and raw tool responses.
- Partial-run diagnostics when a run cannot truthfully proceed.

## Metrics Table

| method | representation | conditioning input | output | evidence style | validity/plausibility checks | energy/DFT checks | novelty checks | traceability/auditability | failure diagnostics | our equivalent/complement |
|---|---|---|---|---|---|---|---|---|---|---|
| CrystaLLM | CIF-language tokens | composition, space group, or prompt-style conditions | generated CIF-like structures | sample validity, plausibility, ab initio validation | structural/CIF validity and plausibility filters | ab initio validation reported in method-specific studies | may include novelty/diversity checks | limited to generation records and validation outputs | usually not workflow-stage diagnostics | our system validates a formulated QLIP request and reports each tool-stage artifact |
| AtomGPT | atomistic generative transformer representations | text, structure, and property/task prompts | generated structures or task outputs | generation plus downstream screening/optimisation | structure/task validity checks | downstream screening or optimisation depending on task | may include screening/diversity analysis | model/task logs, less focused on tool-chain provenance | task failure diagnostics depend on setup | our system separates text interpretation from solver-backed structure generation |
| CrysText | text-conditioned crystal representation | text prompt or material description | generated crystal representation | direct generation benchmark evidence | representation validity checks | placeholder pending citation details | placeholder pending citation details | not primarily an execution trace | placeholder pending citation details | our evaluator maps text request to workflow fulfilment checks |
| MatLLMSearch | LLM-guided materials search | natural language or search objective | candidate materials or search plan/results | search success and screening evidence | depends on search backend | depends on screening backend | depends on search objective | closer to workflow logs if reported | may report search failures | our workflow adds deterministic QLIP validation/solve and bundle-level reports |
| SLICES / inverse representation | invertible structure string representation | composition or latent/generative condition | reconstructed/generated structures | representation validity and reconstruction/generation metrics | reconstruction and structural validity | downstream checks possible | diversity/novelty possible | representation-level audit, not full workflow audit | representation parse/reconstruction failures | adjacent encoding work; our output evidence is workflow and solver traceability |
| Skill-Loop-CSP workflow | retrieved evidence plus QLIP solve request, not CIF-token generation by the LLM | original text request plus concrete material_system | validated/solved CIF candidate or truthful partial report | traceability, requirement fulfilment, validated tool execution, solver output, novelty report | QLIP request validation, artifact checks, evaluator requirements | QLIP objective only; no DFT/property success unless separately integrated | structural novelty check when artifact exists | full execution report, raw responses, workflow evaluation JSON/Markdown | explicit failed tool, code, missing pairs/root mismatch, next action | complementary to direct generators: auditable execution rather than direct token synthesis |

## Claim Boundary

The paper should not claim that the workflow proves target property success unless a property predictor or experimental/DFT evidence is actually present. Semantic retrieval does not prove property satisfaction. Novelty is a structural or fingerprint-style outcome, not experimental validation. QLIP optimality is only with respect to the formulated QLIP objective.

## Recommended Paper Wording

The workflow can produce solver-backed crystal candidates for supported material systems, and produces explicit diagnostic reports for unsupported inputs. Unlike direct text-to-CIF generators, the LLM is used as a controller for a retrieval-grounded, validated, solver-backed workflow rather than as the direct source of crystal-file tokens.
