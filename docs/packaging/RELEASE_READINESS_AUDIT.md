# First-release readiness audit

Audit date: 2026-09-10.

Ticket 11 updated the public installation boundary on 2026-09-11 by removing
the unlicensed SCA Git dependency. Wheel hashes and fresh-install results below
are retained as the Ticket 9 historical audit; they are not current release
artifacts. No replacement release artifact is declared while licensing remains
blocked.

Baseline was created before the audit as required:

~~~text
branch: main
starting commit: 397b568887934f3235234f9b84563fdcf97fb88c
starting status: clean
~~~

## Supported product surface

### llm_csp

Supported public interfaces are:

- llm_csp.workflow: CSPWorkflowRequest, WorkflowConfig, WorkflowResult,
  run_csp_workflow
- llm_csp.schemas: the seven public workflow configuration/result dataclasses
- llm_csp.retrieval: EvidenceRecord, RetrievalStageResult, retrieve_evidence
- llm_csp.spp: required-pair derivation, SPP fit/export, POT-subset export, and
  score_atoms
- llm_csp.validation: validation result models, validate_cif, and
  validate_family_topology
- llm-csp run and llm-csp demo

### crystal_db

Supported public interfaces are backend_status, make_csp_pack, retrieve_text,
run_csp_pack, and text_search. crystal-db-mcp is optional. Internal database,
embedding, and schema helpers are not compatibility promises.

### qlip

The top-level supported API is solve. qlip.core additionally exposes solve and
validate_request as the workflow-facing contract. Packaged resources are
resolved through qlip.resources. Internal allocation and formulation modules
are not declared stable merely because they are present.

### sca

SCA is external and lazy-loaded. The pinned contract is
sca.pipelines.evaluate_one_cif and
sca.evaluators.topology.family_topology_metrics at commit
e5b291312151f34949a5e6ef0f43bebfeb752bc9.

## Metadata audit

| Distribution | Version | Python | Backend | Discovery/data | Runtime and extras | Scripts | Licence/author |
| --- | --- | --- | --- | --- | --- | --- | --- |
| llm-csp | 0.1.0 | >=3.11 | setuptools.build_meta | Finds llm_csp, qlip, crystal_db from three source roots; includes both component resource sets | Scientific solver stack is core; test extra only; SCA installer excluded | llm-csp | MIT assertion for original work, Christian Browning; upstream QLIP notice included; integrated licensing blocked |
| crystal-db | 0.1.0 | >=3.10 | setuptools.build_meta | src discovery; schemas/config defaults included | mcp, schema, test extras | crystal-db-mcp | Christian Browning; licence intentionally unresolved |
| qlip | 0.1.0 | >=3.11 | setuptools.build_meta | src discovery; chemistry, schema, and POT resources included | Solver stack core; MCP 1.x and test extras | none | MIT upstream file; Vladimir V. Gusev and Christian Browning listed |

All README targets exist. Package names are distinct from import namespaces in
the conventional hyphen/underscore form. The integrated root Python minimum
was corrected to QLIP's effective >=3.11 floor. jsonschema was promoted to a
QLIP/core dependency after a clean install exposed it as mandatory for request
validation. MCP is constrained to >=1,<2 because the current server contract
uses the 1.x FastMCP API.

The first integrated contract uses synchronized 0.1.0 versions. Independent
component versioning can begin later if the root records the embedded versions.

## Installation and import audit

Normal integrated installation:

~~~shell
python -m pip install .
~~~

Developer/test installation:

~~~shell
python -m pip install -e ".[test]"
~~~

Environment results:

| Environment | Result |
| --- | --- |
| A, root wheel without extras | llm_csp, llm_csp.spp, workflow, validation, qlip, and crystal_db import from site-packages |
| B, solver-enabled | qlip.solve and qlip.core.validate_request import; Gurobi preflight works |
| C, Crystal-DB-only wheel | crystal_db imports with no DB or LM Studio; missing DB returns missing_db and creates no file |
| D, Ticket 9 validation experiment | validation imported without SCA and returned backend_unavailable; the then-present pinned extra imported SCA and evaluated |
| E, Ticket 9 full-stack experiment | installed-wheel offline demo completed with QLIP and SCA before the public dependency was removed |

The integrated root wheel removes the need for users to understand the nested
package graph. No editable install or sibling checkout was used for its test.

## Distribution artifacts and content

Artifacts were built with build 1.6.1 in an isolated virtual environment using
python -m build. They are stored only in an external temporary audit directory.

| Package | Wheel | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| llm-csp | llm_csp-0.1.0-py3-none-any.whl | 259269 | 1ec44d76fa03dcd96957a7cc4da132664adbe847223087657804c111c7f79b7e |
| crystal-db | crystal_db-0.1.0-py3-none-any.whl | 53167 | ea1ec2a9c078718eb3dc82cb64bd971f3bcccfae13ce6bc0053c8bb261d454dc |
| qlip | qlip-0.1.0-py3-none-any.whl | 157572 | e50ee5d44927769ff83db05986c60d7fe0cb1ed824e4d3faffdb4a2da11855ac |

The matching sdists also built. Wheel inspection found:

- integrated wheel: 112 entries, five JSON schemas, six canonical POTs, all
  runtime modules, Crystal-DB defaults, root licence, and upstream QLIP licence;
- Crystal-DB wheel: 25 entries, three schemas, packaged defaults, runtime code;
- QLIP wheel: 58 entries, two schemas, base chemistry JSON, six POTs, runtime
  code, and upstream licence;
- zero included databases, CIF corpora, embedding files, broad POT trees,
  benchmarks, paper outputs, local runs, Git metadata, caches, or temp files.

## Offline demo and reproducibility

Canonical command:

~~~shell
llm-csp demo --output ./runs
~~~

Installed result:

~~~text
workflow status: completed
solver status: OPTIMAL
objective: 4.883033620558714
formula: Sr1 Ti1 O3
validation: evaluated
~~~

Two runs in distinct output roots had identical QLIP scientific request,
required pair set, all POT hashes, solver objective, generated CIF SHA-256, and
validation values. Only temporary absolute POT/candidate paths differed.

The manifest records llm-csp, crystal-db, qlip, and SCA versions; workflow and
provenance schema identities; source workflow commit; pinned SCA commit;
request/configuration; pair/POT hashes; solver status/objective; candidate hash;
and validation result.

## Failure experience

| Case | Observed behavior |
| --- | --- |
| gurobipy physically absent | QLIP preflight stops before solve, records gurobi_unavailable and qlip_backend_unavailable, suggests installation/licence remediation, CLI exits 3 |
| Gurobi licence exception | Technical exception type/message retained under qlip_backend_unavailable; no fallback solver |
| Production DB absent | Crystal-DB returns error/missing_db and does not create a database |
| LM Studio unavailable | Import succeeds; invocation returns query_embedding_failed with endpoint remediation |
| Embedding dimension mismatch | candidate_vectors_unusable with dim_mismatch count; similarity function is not called |
| POT root absent | Distinct source-root configuration error |
| Required POT missing | regulator_pair_coverage_incomplete; QLIP not invoked |
| POT invalid | regulator_pair_quality_failed with unusable pairs; QLIP not invoked |
| SPP output unwritable | PermissionError type/message retained as structured spp_error; QLIP not invoked |
| SCA absent | Candidate and OPTIMAL solver result preserved; workflow is completed_with_validation_failure, CLI exits 3 |
| Invalid configuration | Missing formula/design space, invalid retrieval engine, unsupported solver, invalid path type, and unknown fields fail at the boundary; CLI JSON error and exit 2 |

CLI success is 0, invalid input is 2, unavailable runtime/backend is 3, and a
scientifically blocked/failed run is 4. Third-party solver stdout is redirected
to stderr under --json, leaving valid JSON on stdout.

## Production and external requirements

External users must provide a compatible production Crystal-DB SQLite/index,
the exact embedding identity and LM Studio-compatible BGE-M3 service, exportable
CIF data rights, a broad regulator POT root covering all formula pairs, an
explicit finite QLIP design space, and Gurobi runtime/licence. Validation needs
a separately authorized compatible backend; the public package does not
install SCA. Optional scaffold corpora and motif catalogs are separate user
assets. No downloader is claimed.

The full classification is in RELEASE_DEPENDENCY_MATRIX.md and all supported
environment variables/assets are in docs/external_assets.md and .env.example.

## Fresh-clone gate

A no-local clone of committed packaging state 0e1940c was created at:

~~~text
C:\Users\brown\AppData\Local\Temp\ticket9-fresh-b555cb794120421e93671dbdfb993e9a
~~~

From that clone, a new virtual environment ran the then-documented non-editable:

~~~shell
python -m pip install ".[validation,test]"
~~~

This command is historical and was superseded by Ticket 11's `pip install .`
boundary. The installed CLI demo passed from outside the repository. The unit,
integration, and E2E suites then reported 163 passed and 2 skipped. Replacing
the installed distribution with the separately built final wheel and rerunning
the demo also passed. Generated clone-local audit files were not copied back.

## Repository hygiene

- Runtime scan: no C:\Users paths, development usernames, sibling-repository
  discovery, local_runs, or final-paper campaign references remain in src or
  packages.
- Historical absolute and sibling paths remain only in migration inventories,
  where they identify frozen source provenance.
- Endpoint scan: only the documented localhost LM Studio default and public
  schema/project URLs occur.
- Secret signature and password-assignment scans found no key, token, password,
  private-key, credential-bearing URL, or licence-key material.
- No tracked file is larger than 1 MB.
- Build trees, egg-info, pytest caches, and bytecode are ignored; distributions
  and run artifacts were created only beneath temporary audit directories.

## Licence and citation status

Ticket 10's `LICENSE_AUDIT.md`, `SOURCE_ATTRIBUTION_MATRIX.csv`, and
`LICENSING_RELEASE_DECISION.md` record the exact-revision and blob-level
evidence. QLIP's observed MIT notice is carried by both its wheel and the
integrated wheel. Crystal-DB, SPP-Maker-QLIP, Skill-Loop-CSP, and SCA have
`NO_EXPLICIT_LICENSE` at the audited revisions. The root MIT declaration cannot
supply rights that were not established upstream. The six bundled POTs and
derived base-data tables also require explicit asset-rights confirmation.

## Release blockers

| Issue | Severity | Release blocker? | Resolution |
| --- | --- | --- | --- |
| Crystal-DB redistribution licence not established | CRITICAL | Yes | Obtain and commit an upstream licence/contributor approval; then update package metadata |
| SPP-Maker-QLIP migrated-code licence not established | CRITICAL | Yes | Establish licence and file-level attribution, including ipcsp-spp lineage |
| Skill-Loop-CSP workflow licence not established | CRITICAL | Yes | Establish permission/licence and contributors |
| SCA has no observed licence | HIGH | No after Ticket 11 isolation | Git dependency/validation extra removed; require permission before restoration |
| Bundled POT authority/generation provenance unresolved | HIGH | Yes | Confirm licensing authority and record source/generation provenance |
| Derived base chemistry/radii data rights unresolved | HIGH | Yes | Review upstream package/data terms and record permission or replace the tables |
| Full scientific contributor list unresolved | HIGH | Yes | Confirm contributors and update CITATION/third-party notices |
| Production data, BGE-M3 service, broad POT corpus, and Gurobi licence are external | MEDIUM | No | Clearly documented and fail-closed |
| Optional deprecated QLIP constraint warnings | LOW | No | Remove compatibility aliases in a later breaking cleanup |

## Recommendation

The software distribution, installation, offline demo, resource contents,
failure behavior, and reproducibility gates pass. A public v0.1.0 release is
nevertheless blocked because redistribution rights and attribution for several
migrated/upstream components are not established.

NOT_READY
