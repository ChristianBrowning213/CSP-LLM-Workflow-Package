# Row-based experiments

One CSV row is one experiment. Copy `TEMPLATE.csv`, edit it in a text editor or spreadsheet, and run:

```powershell
.\.venv\Scripts\python.exe scripts\run_experiment_table.py experiments\my_tests.csv --dry-run
.\.venv\Scripts\python.exe scripts\run_experiment_table.py experiments\my_tests.csv
```

Results are written by default to `experiments/results/<table-name>/`: `RESULTS.csv`, `RESULTS.md`, `RUN_SUMMARY.md`, and one artifact directory per row. Each successful canonical CIF row also produces `rows/<row_id>/figures/workflow_full.png`, a matching PDF, a provenance manifest, and the exact plotted solver-guidance CSV. The workflow figure uses the row's ranked retrieval, final solver-consumed POTs, generated CIF, VESTA renders, and validation fields. Controlled failures are explicitly marked `NOT_APPLICABLE` and do not receive a success figure.

Required columns are `row_id`, `formula`, `request`, `scaffold_mode` (`tight`, `loose`, or `minimal`), and `request_spp_mode` (`enabled` or `disabled`). Paper/result metadata columns include `experiment_block`, `family`, `repeat_group`, `repeat_index`, `run_sca`, and `run_chgnet`. Optional workflow columns are `corpus`, `reference_id`, `enabled`, `notes`, `retrieval_depth`, `embedding_model`, `embedding_version`, `retrieval_demo_export`, `cutoff`, `request_coefficient`, `regulator_coefficient`, `outer_objective_scale`, `request_spp_convention`, `regulator_id`, `registry_path`, `cell_mode`, and `cell_volume_per_atom`.

`cell_mode` (`native`, `composition_scaled`, or `retrieval_derived`) only applies to rows solved with no explicit scaffold (`scaffold_mode=none` and the CLI run without `--scaffolds`, i.e. `native_qlip=True`); it selects the cubic candidate-cell edge length QLIP searches, while the uniform-grid density and every other constraint stay frozen. `native` (the default) reproduces the exact original hardcoded 3.9 A cell. `composition_scaled` sizes the cell from the target atom count times a single frozen, target-independent volume-per-atom constant (see `sok_llm_orchestrator.workflow.cell_strategy.GLOBAL_VPA_A3_PER_ATOM`). `retrieval_derived` uses the median volume-per-atom of the SAME leakage-safe evidence structures already retrieved for request-SPP fitting. `cell_volume_per_atom` is an explicit override of that per-mode statistic for `composition_scaled`/`retrieval_derived` rows; leave it blank for ordinary rows (any value here means "I picked this cell size by hand", not a leakage-safe statistic).

`corpus` is an assertion against canonical routing, not an override. A supplied `reference_id` must resolve to an exportable, formula-matching CIF in that routed Crystal-DB corpus; it is excluded using the existing prospective reference adapter and compared only after generation.

Useful options: `--output <dir>`, `--only <row_id>`, `--from-row <n>`, `--dry-run`, `--resume`, `--vesta-path <VESTA.exe>`, `--no-figures`, and `--continue-on-scientific-failure`. Figures are enabled by default for ordinary CLI runs. Resume preserves terminal row artifacts and retries only row-input/software failures.

`execution_mode=canonical` is the default and calls `run_csp_workflow()`. `execution_mode=reuse_frozen` is reserved for auditable assembly of an existing result: `source_artifact` must identify the exact JSON/CSV source and `source_artifact_key` must select a unique CSV record when needed. The runner records and hashes that source; it does not relabel a frozen result as a fresh execution.

The frozen final-paper table is `paper_results/RESULTS_EXPERIMENTS.csv`. Run it without editing Python:

```powershell
.\.venv\Scripts\python.exe scripts\run_experiment_table.py experiments\paper_results\RESULTS_EXPERIMENTS.csv --dry-run --output artifacts\final_paper_results\dry_run
.\.venv\Scripts\python.exe scripts\run_experiment_table.py experiments\paper_results\RESULTS_EXPERIMENTS.csv --output artifacts\final_paper_results\table_run --resume
```

QLIP status, objective parity, SCA validity, and held-out reference recovery are reported separately. Raw objectives are not compared across different search spaces.

To rebuild a complete figure inventory from an assembled master table without editing Python:

```powershell
.\.venv\Scripts\python.exe scripts\build_row_workflow_figures.py
.\.venv\Scripts\python.exe scripts\build_paper_figures_from_rows.py
```

Visual approval is intentionally separate and fail-closed: inspect the generated row contact sheet and original-resolution samples before using `--approve-visual-qa`, then inspect all five paper figures before approving their QA manifest.
