# CSV generation workflow v1

`csv_workflow_v1` is the frozen user-facing batch interface around the final
`paper_final_v2` generation method. One CSV row produces one independent,
portable row bundle. Generation ends after the raw QLIP candidate is copied and
hashed. SCA and visualisation are separate commands.

## 1. Configure component roots

Copy `.env.example` to `.env` in the Skill-Loop-CSP repository root and set:

```dotenv
CRYSTAL_DB_ROOT=C:\path\to\Crystal-DB
SPP_MAKER_ROOT=C:\path\to\SPP-Maker-QLIP
QLIP_ROOT=C:\path\to\qlip
SCA_ROOT=C:\path\to\Structured_Crystal_Analyser
```

The repository-root `.env` is loaded first. Actual process environment
variables override `.env`. Relative configured paths are resolved against the
Skill-Loop-CSP root; all roots are then made absolute and validated. The frozen
benchmark command never guesses sibling paths. `.env` is ignored by Git;
`.env.example` is tracked.

Check the setup:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow doctor
```

The doctor prints PASS/FAIL and resolved paths for `CRYSTAL_DB_ROOT`,
`SPP_MAKER_ROOT`, `QLIP_ROOT`, and `SCA_ROOT`.

## 2. Minimal CSV

Only `request_text` is required:

```csv
request_text
"Generate a plausible rocksalt MgO structure."
"Generate a cubic BaTiO3 perovskite."
```

Requests must include enough information to resolve a composition. The known
final-paper tasks use the existing deterministic normaliser. Other explicit
formula requests use the versioned deterministic formula/intent parser. No LLM
is introduced by this interface.

## 3. Advanced CSV schema

Blank optional cells inherit the canonical defaults in
`config/final_workflow_v1.json`.

| Column | Type | Contract |
|---|---:|---|
| `row_id` | string | Optional stable folder identity; sanitized and required to be unique. |
| `request_text` | string | Required, non-empty original researcher request. |
| `database` | enum | `auto`, `general`, `spinel`, or `layered`; never a filesystem path. |
| `retrieval_top_k` | integer | Positive retrieval depth. |
| `spp_contract` | enum | Frozen v1 accepts `dmytro_gr_v1` only. |
| `cell_policy` | enum | Frozen v1 accepts `retrieval_feasible_cell_v1` only. |
| `solver_time_limit_s` | integer | Positive Gurobi time limit. |
| `solver_threads` | integer | Positive thread count. |
| `solver_mip_gap` | float | Non-negative MIP gap. |
| `proximity_scale` | float | Positive `proximity.atomic_radii` scale. |
| `random_seed` | integer | QLIP solver seed. |
| `target_reference_id` | string | Optional designated Crystal-DB record ID. |
| `exclude_target_reference` | boolean | If true, the non-empty designated ID is excluded from SPP evidence. |
| `notes` | string | User annotation only; it does not affect science. |

Unsupported columns are rejected before any row starts. All rows are parsed,
typed, normalized, checked for unique IDs, and checked against logical database
selectors before scientific execution begins.

Example:

```csv
row_id,request_text,database,retrieval_top_k,solver_time_limit_s
mgo_test,"Generate rocksalt MgO",general,50,300
spinel_test,"Generate a zinc ferrite spinel with composition ZnFe2O4",spinel,50,300
```

## 4. Frozen defaults

The single source of truth is `config/final_workflow_v1.json`:

- workflow: `csv_workflow_v1`
- scientific parent: `paper_final_v2`
- SPP: `dmytro_gr_v1`
- cell: `retrieval_feasible_cell_v1`
- database routing: `auto`
- retrieval top-k: 50
- SPP evidence limit: 30 ranked leakage-safe structures
- cutoff: 10 angstrom
- cubic grid: 4 x 4 x 4 (64 candidate positions)
- QLIP time limit: 300 seconds
- QLIP threads: 1
- QLIP MIP gap: 0.0
- QLIP seed: 0
- proximity: `proximity.atomic_radii(scale=1.0)`
- target-reference exclusion: false unless explicitly requested with an ID

The retrieval-derived median volume-per-atom prior, existing evidence/fallback
semantics, exact QLIP formulation, and final-v2 dynamic-cell search are reused.

## 5. Generation and preflight

Validate configuration and CSV only, with no retrieval or output mutation:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow generate `
  --input inputs.csv `
  --output outputs\demo `
  --dry-run
```

Run the scientific preflight (structured task, live retrieval, SPP support and
fallback, dynamic-cell hard feasibility, and output preparation), but no final
QLIP generation solve:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow generate `
  --input inputs.csv `
  --output outputs\demo `
  --preflight-only
```

Generate candidates:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow generate `
  --input inputs.csv `
  --output outputs\demo
```

The command above is for a fresh output directory. After a successful
`--preflight-only` command has already created `outputs\demo`, continue the same
prepared run with:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow generate `
  --input inputs.csv `
  --output outputs\demo `
  --resume
```

Useful controls are `--rows row_0001,row_0007`, `--resume`, `--fail-fast`, and
`--retry-technical-failures`. A successful candidate is never overwritten.
`--resume` skips `GENERATED` and `INFEASIBLE` scientific terminal rows, prepares
rows not yet attempted, and refuses a technical-failure retry unless
`--retry-technical-failures` is explicit.

Generation does not import or run SCA. It does not reject a generated candidate
merely because SCA has not run.

## 6. Run and row layout

```text
outputs/demo/
  input.csv
  run_config.json
  run_manifest.csv
  run_provenance.json
  row_0001/
    input/
      request.txt
      input_row.json
      effective_config.json
    structured_task/
      structured_task.json
      provenance.json
    retrieval/
      query.json
      retrieval_config.json
      retrieval_manifest.csv
      retrieval_manifest.json
      neighbour_hashes.csv
      neighbours/*.cif
    cell/
      retrieval_volume_prior.json
      dynamic_cell.json
      feasibility_trace.json
      search_space.json
    spp/
      config.json
      pair_manifest.csv
      evidence_counts.csv
      blend_weights.csv
      provenance.json
      potentials/**/*.POT
    qlip/
      solver_config.json
      problem_size.json
      solver_result.json
      objective_check.json
      logs/
    generated/
      candidate.cif
      candidate.sha256
    status/
      generation_status.json
    sca/                 # created only by workflow sca
    visualisation/       # created only by workflow visualise
```

`retrieval/neighbours` contains copies of exported neighbour CIFs, including
every CIF selected into the SPP evidence cohort. The manifests retain rank,
Crystal-DB record ID, similarity, contribution flag, source path, portable path,
and SHA-256. `spp/potentials` is a copied, solver-consumed pair-complete POT root;
its tree hash and per-pair hashes are recorded. The raw candidate is copied once
to `generated/candidate.cif`; both generation and every downstream command check
or preserve its SHA-256.

Absolute component roots are allowed in `run_provenance.json`, but never in the
scientific input CSV. Archive or copy a complete `row_x` directory as the
portable scientific unit.

## 7. Separate SCA trigger

One row:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow sca `
  --row outputs\demo\row_0001
```

An entire run:

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow sca `
  --run outputs\demo
```

Run mode discovers rows from `run_manifest.csv`, evaluates only rows with
generated candidates, skips rows without a CIF, and writes
`SCA_RUN_SUMMARY.csv` plus `SCA_RUN_SUMMARY.json`. Existing row results are not
replaced unless `--force` is supplied. `--rows` limits run mode. SCA is imported
from `SCA_ROOT`; evaluation code is not duplicated here. Candidate hashes are
checked before and after evaluation.

## 8. Row-only visualisation

```powershell
.\.venv\Scripts\python.exe -m sok_llm_orchestrator.cli workflow visualise `
  --row outputs\demo\row_0001
```

The renderer reads only that row folder: exact request text, copied neighbours,
retrieval scores, copied POT curves, dynamic-cell metadata, solver result, raw
candidate, and optional SCA summary. It never loads `.env`, queries Crystal-DB,
reruns retrieval/SPP/QLIP, or needs the input CSV. If SCA is absent, the figure
shows `SCA: NOT RUN`. Outputs are:

```text
row_x/visualisation/workflow.png
row_x/visualisation/workflow.pdf
row_x/visualisation/figure_metadata.json
```

The generated structure uses a 2 x 2 x 2 display-only replication. Raw CIFs and
raw POT values are not modified.

## 9. Run manifest and states

`run_manifest.csv` has one row per input request. It records the stable row ID,
CSV row number, exact request, logical database, generation state, stage status,
retrieval count, cell edge/policy, SPP pair support/fallback counts, solver
status/objective/runtime, relative candidate path/hash, SCA status,
visualisation status, and notes.

Generation states are `NOT_STARTED`, `RUNNING`, `GENERATED`, `INFEASIBLE`, and
`TECHNICAL_FAILURE`. `GENERATED` and `INFEASIBLE` are scientific terminal states.
They are not silently rerun.

## 10. Freeze boundary

This interface freeze does not start or define the forthcoming 50+50 benchmark.
The benchmark CSV, 100-row preflight, and campaign launch belong to the next
goal. Changes to retrieval, SPP construction, dynamic-cell methodology, QLIP,
or validation policy require a new explicit workflow version; results from
different frozen methods must not be mixed.
