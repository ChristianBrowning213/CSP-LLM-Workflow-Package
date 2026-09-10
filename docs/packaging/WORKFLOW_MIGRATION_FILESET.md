# Workflow migration fileset

This selection was frozen before implementation from Skill-Loop-CSP branch
`Agentic-Loop`, commit `b2130661b4690623877e852dc03132506aa720dd`.
The known untracked `benchmarks/external/OMatG/` directory is unrelated and is
not read, copied, modified, staged, or removed.

The migration adapts coordination policy to installed public component APIs;
it does not copy these research modules verbatim.

## Request schemas

| Source | Destination | Reason |
| --- | --- | --- |
| `workflow/runner.py::WorkflowConfig` | `src/llm_csp/schemas/workflow.py` | Explicit portable request/config and serializable result contracts. |

## Workflow runner and artifacts

| Source | Destination | Reason |
| --- | --- | --- |
| `workflow/runner.py::run_csp_workflow` | `src/llm_csp/workflow/runner.py` | Canonical deterministic stage ordering, failure propagation, and run manifests. |

## Retrieval

| Source | Destination | Reason |
| --- | --- | --- |
| `workflow/runner.py::ProductionWorkflowStages.retrieve` | `src/llm_csp/retrieval/adapter.py` | Normalize packaged Crystal-DB results and allow a deterministic offline boundary fixture. |
| `workflow/evidence.py` selected evidence records | `src/llm_csp/retrieval/adapter.py` | Minimal ranked/exportable CIF evidence contract; similarity math stays in Crystal-DB. |

## SPP and regulator orchestration

| Source | Destination | Reason |
| --- | --- | --- |
| `workflow/runner.py::fit_request_spp` pair decision subset | `src/llm_csp/workflow/spp_policy.py` | Call packaged SPP fitting/export, require full regulator coverage, and preserve request-plus-regulator versus regulator-only decisions. |
| `workflow/runner.py::_qlip_spp_request_adapter` | `src/llm_csp/generation/qlip_request.py` | Preserve QLIP complete/partial/fallback guidance encoding. |

The source-only calibration campaign and `common_contract` fitting/blending
implementation are not copied. The packaged workflow consumes the supported
Ticket 6 builder and byte-preserving library exporter.

## Scaffold and QLIP compilation

| Source | Destination | Reason |
| --- | --- | --- |
| `workflow/runner.py::solve` request assembly | `src/llm_csp/generation/qlip_request.py` | Compile caller-supplied `none` or explicit packaged QLIP design spaces and solver controls. |

QLIP scaffold construction, constraints, allocation, validation, and solve
remain owned by packaged QLIP. Paper-named family scaffold builders and the
external NASICON corpus are excluded.

## Validation

| Source | Destination | Reason |
| --- | --- | --- |
| `workflow/runner.py::evaluate` | `src/llm_csp/workflow/runner.py` | Invoke `llm_csp.validation` only and retain general/topology results separately. |

## CLI and tests

| Source | Destination | Reason |
| --- | --- | --- |
| Canonical runner API | `src/llm_csp/cli/main.py`, `src/llm_csp/__main__.py` | Thin JSON-configured `llm-csp run` entry point. |
| `tests/test_canonical_workflow_api.py` and focused adapter/failure tests | `tests/unit/workflow/`, `tests/integration/workflow/`, `tests/e2e/` | Adapted stage, failure, parity, artifact, and installed-package coverage. |

## Explicit exclusions

- `agentic/`, agent memory/loop/control and Dream/SoK prototypes
- `paper_final_v1.py`, `paper_final_v2.py`, paper scaffold campaigns
- benchmark, ablation, dataset-generation, reporting, figure, audit, repair,
  visualization, HPC, `local_runs`, outputs, and paper artifacts
- Crystal-DB databases/embeddings, broad regulator POTs, SCA implementation,
  QLIP scientific implementation, and SPP scientific implementation
- historical `orchestrator.pipeline`, `system_entrypoint`, and CSV/paper runners
