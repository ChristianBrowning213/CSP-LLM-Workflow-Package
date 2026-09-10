# Deterministic workflow

LLM-CSP provides a retrieval-guided, solver-backed workflow that converts an
explicit crystallographic request into an evidence-conditioned QLIP run with
SPP provenance and post-generation validation.

```text
CSPWorkflowRequest
  -> packaged Crystal-DB retrieval (or deterministic fixture boundary)
  -> exportable CIF evidence gate
  -> packaged request SPP + complete external regulator policy
  -> packaged QLIP validate_request + solve
  -> candidate CIF
  -> llm_csp.validation
  -> serializable WorkflowResult and run.json
```

## Python API

```python
from llm_csp.schemas import CSPWorkflowRequest, WorkflowConfig
from llm_csp.workflow import run_csp_workflow

result = run_csp_workflow(request, config)
```

The request requires query text, formula, and an explicit QLIP design space.
Optional constraints, target space group, topology family, and scaffold ID are
metadata/policy inputs. The workflow does not infer a new scaffold or parse
arbitrary natural language into crystallographic settings.

`WorkflowConfig` requires `output_root`. Retrieval, SPP weights/regulator,
solver, and validation are explicit nested configurations. A configured
retrieval provider is supported for deterministic offline testing; production
uses `crystal_db.retrieval.text_search`.

## Stage and failure semantics

- Retrieval errors become `retrieval_backend_unavailable` or
  `retrieval_embedding_incompatible`.
- An empty result is `retrieval_empty`; records without usable exported CIFs
  become `retrieval_no_exportable_cifs`. No SPP call follows these states.
- The external regulator must have usable POTs for every required formula pair.
  Incomplete coverage blocks before QLIP.
- With request fitting enabled, usable request POTs and weighted regulator POTs
  both contribute. Missing or unusable request pairs use regulator-only
  fallback. With request fitting disabled, the complete regulator is primary.
- QLIP requests always pass through `qlip.core.validate.validate_request` before
  `qlip.solve`.
- `OPTIMAL`, `FEASIBLE`, and `FEASIBLE_TIME_LIMIT` are preserved distinctly and
  may carry a real candidate. Other statuses produce no candidate or validation.
- General/topology validator failure retains a successful QLIP result and CIF;
  the workflow status becomes `completed_with_validation_failure`.

## Run directory

Each call creates `<output_root>/<run_id>/` and refuses to overwrite it:

```text
request.json
run.json
retrieval/result.json
retrieval/cifs/
spp/workflow_manifest.json
spp/request/
spp/regulator/
qlip/request.json
qlip/request_validation.json
qlip/result.json
validation/result.json
final/candidate.cif
```

Only reached-stage artifacts are created. `run.json` includes the input, stage
states, errors, artifact paths, source contract, and component versions.

## CLI

```shell
llm-csp run --config request.json --output runs --json
```

The JSON file contains `request` and `config` objects matching the Python
models. The CLI contains no scientific logic.

## External runtime requirements

Production retrieval needs a compatible external Crystal-DB SQLite/index and
matching embedding service. Broad regulator POTs remain external. QLIP needs a
configured solver; the canonical regression uses Gurobi. SCA is installed with
the `validation` extra. No network or production database is used by the
deterministic offline SrTiO3 test.
