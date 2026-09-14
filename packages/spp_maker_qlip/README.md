# SPP_Maker

SPP_Maker bootstraps the pipeline that will generate QLIP-compatible `.POT` outputs from structure corpora.

This repository currently includes:
- Python package layout in `src/spp_maker/`
- End-to-end `fit` and `score` CLI workflows
- Pytest coverage for core pipeline modules

## Install

```bash
pip install -e ".[dev]"
```

## MCP Server

Install MCP extras:

```bash
pip install -e ".[mcp]"
```

Run the MCP server over stdio:

```bash
spp-maker-mcp
# or
python -m spp_maker_mcp.server
```

Tool contracts and examples are documented in `docs/mcp/API.md`.

Example tool-call payloads:

```json
{"tool_name":"spp.run_pipeline","arguments":{"cif_dir":"tests/fixtures/cifs","out_dir":"out/mcp_demo","name":"demo","calibration":{"target":5.0},"dry_run":true}}
```

```json
{"tool_name":"spp.check_compat","arguments":{"spp_root":"out/mcp_demo/spp_root","strict":true}}
```

```json
{"tool_name":"spp.package_for_qlip","arguments":{"spp_root":"out/mcp_demo/spp_root","calibration_json":"out/mcp_demo/calibration.json","out_dir":"out","name":"demo_pkg"}}
```

```json
{"tool_name":"spp.publish_to_qlip_outputs","arguments":{"kind":"spp","artifact_root":"out/mcp_demo/spp_root","qlip_outputs_path":"QLIP_Outputs","name":"demo_pub","overwrite":false}}
```

## Quickstart

Run an end-to-end fit on a CIF directory and export QLIP-compatible POT files:

```bash
python -m spp_maker.cli fit \
  --cif_dir tests/fixtures/cifs \
  --out_root out/spp_root \
  --name demo_run
```

## One-command pipeline

Recommended path for QLIP handoff:

```bash
python -m spp_maker.cli run \
  --name ABO3_run \
  --cif_dir data/mp_ABO3_fe/cifs \
  --out_dir out \
  --fit_method supercell_gr \
  --calib_score_method neighbors \
  --no_bandpass \
  --target 10.0 \
  --max_calib 200 \
  --publish_to QLIP_Outputs
```

Outputs (under `--out_dir`, default current directory):
- `SPP_Runs/<run_id>/`:
  - `input_snapshot/` (`params.json`, `env.json`, `cif_list.txt`)
  - `fit/` (`spp_root/`, `manifest.json`, `compat_report_fit.txt`)
  - `calibrate/` (`calibration.json`, `scaled_spp_root/`, `compat_report_scaled.txt`)
  - `package/` (`package.json`, `snippet.py.txt`)
  - `logs/` (`run_summary.txt`, `timings.json`)
- `Final_QLIP_output/<run_id>/`:
  - `package.json`
  - `spp_root/`
  - `guidance/calibration.json`
  - `compat_report.txt`
  - `README.txt`
  - optional `qlip_outputs_tree/` when `--publish_to` is set

## Dmytro-Mode fitting (supercell g(r))

Use the supercell histogram backend (`fit_method=supercell_gr`) to match
Dmytro’s workflow:
- explicit supercell from unit cell (target ~20 A, with geometric support checks)
- all unit-cell -> supercell distances
- fixed histogram grid: 0-10 A, 200 bins, bin width 0.05 A
- Gaussian deposition with sigma 0.1 A, truncated at +/-3 sigma
- `phi(r) = -ln(g(r) + gr_eps)` with no shift/rescale

Example:

```bash
python -m spp_maker.cli fit \
  --cif_dir tests/fixtures/cifs \
  --out_root out/spp_root_dmytro \
  --fit_method supercell_gr \
  --supercell_target_len 20.0 \
  --r_max 10.0 \
  --bin_width 0.05 \
  --sigma 0.1 \
  --truncate_sigma 3.0 \
  --gr_eps 1e-12 \
  --dump_gr_csv out/gr_debug
```

Optional covalent-like exclusion (weight=0 for matching structures):

```bash
python -m spp_maker.cli fit \
  --cif_dir tests/fixtures/cifs \
  --out_root out/spp_root_dmytro_cov \
  --fit_method supercell_gr \
  --supercell_target_len 20.0 \
  --r_max 10.0 \
  --bin_width 0.05 \
  --sigma 0.1 \
  --truncate_sigma 3.0 \
  --gr_eps 1e-12 \
  --exclude_covalent \
  --covalent_rules path/to/rules.yaml \
  --max_pairs 5000000
```

Rules file format (`.csv` or `.yaml/.yml`):
- `elem1`
- `elem2`
- `min_dist`
- exclusions are explainable in `manifest.json` via:
  - `excluded_structure_count`
  - `excluded_by_rule`
  - `sample_exclusions` (capped list with pair, threshold, observed distance, atom indices, and rule source)

Dmytro mode safeguards:
- `--r_cut/--knn` are rejected in this mode (use `--r_max/--sigma`)
- bandpass flags are rejected
- `--shift_phi/--no_shift_phi` are rejected (mode is fixed to `phi=-ln(g+gr_eps)`)
- `--max_pairs` optionally caps accepted distances per structure with deterministic `i,j` traversal

Validation workflow:
- write CSV dumps (`--dump_gr_csv`) with columns `r,g,exp_minus_phi` (optional `--dump_gr_pair`)
- compare `g(r)` and `exp(-phi(r))` qualitatively by visual inspection
- helper script:
  - direct CIF mode: `python scripts/plot_gr_dump.py --cif tests/fixtures/cifs/nacl.cif --out_dir out/gr_debug`
  - exported root mode: `python scripts/plot_gr_dump.py --spp_root out/spp_root_dmytro --out_dir out/gr_debug`

Output layout:
- `out/spp_root/<A>-<B>/<A>-<B>.POT`
- `out/spp_root/manifest.json`

Score one CIF:

```bash
python -m spp_maker.cli score \
  --spp_root out/spp_root \
  --cif tests/fixtures/cifs/nacl.cif
```

Score a folder (sorted by filename) with JSON lines output:

```bash
python -m spp_maker.cli score \
  --spp_root out/spp_root \
  --cif_dir tests/fixtures/cifs \
  --json
```

## Property-conditioned fitting

Use metadata to fit on a filtered subset:

```bash
python -m spp_maker.cli fit \
  --cif_dir tests/fixtures/cifs \
  --out_root out/spp_root_propA \
  --meta_csv path/to/meta.csv \
  --property_filter A \
  --property_mode include
```

Where `meta.csv` contains at least:
- `cif_name` or `cif_path`
- `property_label`
- optional `weight`

## Demo

Run the end-to-end baseline vs property-conditioned comparison script:

```bash
python scripts/demo_property_conditioned_spp.py \
  --cif_dir tests/fixtures/cifs \
  --meta_csv path/to/meta.csv \
  --property_filter A \
  --out_dir out/demo_prop_spp \
  --name demo
```

Outputs:
- `out/demo_prop_spp/demo/spp_all/` (baseline model)
- `out/demo_prop_spp/demo/spp_prop_A/` (property-conditioned model)
- `out/demo_prop_spp/demo/report.json` (machine-readable comparison)
- `out/demo_prop_spp/demo/summary.txt` (human-readable summary)

## QLIP integration

- Integration notes and copy/paste snippets: `QLIP_Outputs/INTEGRATION.md`
- POT compatibility check:

```bash
python scripts/check_pot_compat.py --spp_root out/demo_prop_spp/demo/spp_all --strict
```

## Publishing to QLIP_Outputs

Publish a generated SPP root into the canonical handoff registry:

```bash
python scripts/publish_qlip_outputs.py \
  --spp_root out/demo_prop_spp/demo/spp_all \
  --name demo_all
```

This creates/updates:
- `QLIP_Outputs/SPP/runs/<run_id>/...`
- `QLIP_Outputs/index.json`
- `QLIP_Outputs/SPP/latest.txt`

QLIP_Outputs now supports multiple artifact kinds (`spp`, `guidance`, `constraint`)
with a versioned unified index. See `QLIP_Outputs/README.md` for details and publish examples.

## QLIP guardrails

For QLIP-safe scoring defaults:
- out-of-range policy: `max`
- missing-pair policy: `max_global`

Example explicit scoring policies:

```bash
python -m spp_maker.cli score \
  --spp_root out/spp_root \
  --cif tests/fixtures/cifs/nacl.cif \
  --oob_policy max \
  --missing_pair_policy max_global
```

Example export-time short-distance floor:

```bash
python -m spp_maker.cli fit \
  --cif_dir tests/fixtures/cifs \
  --out_root out/spp_root_guarded \
  --short_distance_floor 3.0 \
  --short_distance_bins 2
```

## Calibration (lambda)

Calibrate a recommended `lambda` so SPP penalties are on a chosen target scale:

```bash
python -m spp_maker.cli calibrate \
  --spp_root out/spp_root \
  --cif_dir tests/fixtures/cifs \
  --mode structure_median \
  --target 5.0
```

Calibration sign semantics:
- structure/edge scores can be negative (for example when `phi=-ln(g)` and
  parts of `g(r)` exceed 1, giving negative `phi` in some bins)
- calibration now reports transparent lambda fields:
  - `lambda_raw` (signed)
  - `lambda_abs`
  - `lambda_clipped`
  - `lambda_used` (positive value actually applied)
- convention controls downstream usage:
  - `reward`: use `+ lambda_used * score`
  - `penalty`: use `+ lambda_used * (-score)`

Write a scaled SPP root (`U <- lambda * U`) and JSON report:

```bash
python -m spp_maker.cli calibrate \
  --spp_root out/spp_root \
  --cif_dir tests/fixtures/cifs \
  --target 5.0 \
  --write_scaled_root out/spp_root_scaled \
  --out_json out/calibration.json
```

Neighbors scoring, no bandpass, reward convention:

```bash
python -m spp_maker.cli calibrate \
  --spp_root out/spp_root \
  --cif_dir tests/fixtures/cifs \
  --score_method neighbors \
  --no_bandpass \
  --convention reward \
  --target 10.0 \
  --out_json out/calibration_neighbors_reward.json
```

Supercell scoring (Dmytro-aligned), reward convention:

```bash
python -m spp_maker.cli calibrate \
  --spp_root out/spp_root_dmytro \
  --cif_dir tests/fixtures/cifs \
  --score_method supercell_gr \
  --convention reward \
  --target 10.0 \
  --out_json out/calibration_supercell_reward.json
```

Publish calibration guidance to `QLIP_Outputs`:

```bash
python -m spp_maker.cli calibrate \
  --spp_root out/spp_root \
  --cif_dir tests/fixtures/cifs \
  --target 5.0 \
  --publish \
  --qlip_outputs QLIP_Outputs \
  --name calibration_demo
```

## CLI usage

```bash
spp-maker --help
spp-maker fit --help
spp-maker score --help
spp-maker calibrate --help
spp-maker run --help

python -m spp_maker.cli --help
```

## Planned modules

- `src/spp_maker/io_cif.py`: ASE-first CIF loading adapter
- `src/spp_maker/neighbors.py`: periodic MIC distance + neighbor edge builder
- `src/spp_maker/fit_hist.py`: weighted species-pair distance histogram accumulator
- `src/spp_maker/fit_phi.py`: smoothed probabilities and phi=-log(p) curve builder
- `src/spp_maker/pot_io.py`: QLIP-compatible `.POT` reader/writer helpers
- `src/spp_maker/export.py`: pair-directory export + manifest writer
- `src/spp_maker/spp_model.py`: load/query exported SPP roots in memory
- `src/spp_maker/score.py`: structure scoring backend and score reports
- `src/spp_maker/weights_csv.py`: optional per-structure weights CSV parser
- `src/spp_maker/meta_csv.py`: metadata/property label parser + matcher
- `src/spp_maker/calibration.py`: corpus scoring stats, lambda recommendation, and scaled-root utility

## Docs

Project plans and constraints are in `docs/`, including:
- `docs/Repo stack.docx`
- `docs/Milestone_ qlip_SPP*.docx`
