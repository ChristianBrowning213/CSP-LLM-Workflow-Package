# SCA — Structured Crystal Analyser

## Purpose

SCA is an internal Python toolkit for pre-DFT evaluation of generated crystal structures. It is designed for comparing text-to-crystal workflows against CrystaLLM-style generated-structure evaluation before any expensive first-principles calculations.

## Install

```bash
pip install -e .
```

For development:

```bash
pip install -r requirements-dev.txt
pytest -q
```

ALIGNN is optional. Install it only when surrogate formation-energy scoring is needed:

```bash
pip install alignn
```

## CrystaLLM-Style Pre-DFT Evaluation

The `crystallm-eval` pipeline checks:

- CIF parse/processability
- composition and target formula consistency
- declared, detected, and target space-group consistency
- atom-site multiplicity consistency when explicit CIF multiplicities exist
- bond/contact reasonableness
- volume, density, and lattice geometry warnings
- duplicate grouping with `StructureMatcher`
- novelty/rediscovery against an optional reference corpus
- optional ALIGNN formation-energy scoring

SCA does not run DFT and does not compute real energy above hull.

## CLI Usage

Full intent benchmarks use Skill-Loop-CSP as the generator and SCA as the
controller/evaluator. See `docs/FULL_INTENT_BENCHMARK.md` for the seeded 100
prompt workflow, including generation, archive collection, intent satisfaction,
unique traceability summaries, and the final report.

Single CIF:

```bash
sca crystallm-eval one examples/cifs/tiny_valid.cif \
  --target-formula NaCl \
  --target-space-group 1 \
  --out reports/one.json \
  --require-spacegroup false \
  --alignn false
```

Folder:

```bash
sca crystallm-eval folder examples/cifs \
  --target-formula NaCl \
  --out reports/pre_dft_eval.csv \
  --jsonl reports/pre_dft_eval.jsonl \
  --require-spacegroup false \
  --alignn false
```

Manifest:

```bash
sca crystallm-eval manifest manifests/generated_candidates.csv \
  --path-col cif_path \
  --formula-col target_formula \
  --spacegroup-col target_space_group \
  --method-col method \
  --query-id-col query_id \
  --alignn true \
  --out reports/pre_dft_eval.csv \
  --jsonl reports/pre_dft_eval.jsonl
```

Manifest with novelty checking against a reference CIF folder:

```bash
sca crystallm-eval manifest manifests/generated_candidates.csv \
  --path-col cif_path \
  --formula-col target_formula \
  --spacegroup-col target_space_group \
  --method-col method \
  --query-id-col query_id \
  --novelty true \
  --reference-folder data/reference_mp_subset \
  --alignn false \
  --out reports/pre_dft_eval.csv \
  --jsonl reports/pre_dft_eval.jsonl
```

Novelty can also load references from a manifest:

```bash
sca crystallm-eval folder examples/cifs \
  --novelty true \
  --reference-manifest data/reference_manifest.csv \
  --reference-path-col cif_path \
  --reference-id-col material_id \
  --out reports/pre_dft_eval.csv \
  --jsonl reports/pre_dft_eval.jsonl
```

Summarize:

```bash
sca summarize reports/pre_dft_eval.csv \
  --group-col method \
  --out reports/pre_dft_summary_by_method.csv
```

Select top-k candidates for later DFT:

```bash
sca select-top-k reports/pre_dft_eval.csv \
  --group-cols method,query_id \
  --k 5 \
  --out reports/top5_for_dft.csv
```

The original ALIGNN-only commands remain available under `sca alignn`.

## Literature-Replication Benchmarks

List built-in literature comparator protocols:

```bash
python -m sca.cli list-benchmark-protocols
```

Run a direct CIF-set comparator report:

```bash
python -m sca.cli benchmark-cif-set \
  --manifest benchmarks/paper_targets/generated_manifest.csv \
  --protocols all \
  --out reports/direct_manifest_results.csv \
  --summary reports/direct_manifest_summary.csv \
  --json reports/direct_manifest_summary.json \
  --markdown reports/direct_manifest_report.md
```

Run an end-to-end prompt benchmark by providing a generator command template:

```bash
python -m sca.cli run-e2e-text-benchmark \
  --prompts benchmarks/e2e_text_prompts/e2e_prompts_v1.csv \
  --generator-command "python tests/fixtures/fake_generator.py --prompt {prompt} --out-dir {out_dir} --attempts {num_attempts}" \
  --out-dir reports/e2e_fake_runs \
  --num-attempts 3 \
  --protocols all \
  --summary reports/e2e_fake_summary.csv \
  --markdown reports/e2e_fake_report.md
```

See `docs/LITERATURE_REPLICATION_BENCHMARKS.md` for Windows CMD commands,
protocol-match caveats, and dataset scaffold details.

## Unique Verifiable CSP Benchmarks

The literature-replication commands ask whether generated CIFs match paper metrics. The unique CSP benchmark asks whether a text-to-crystal run is traceable, retrieval-grounded, constraint-faithful, solver-backed, auditable, repairable, and reproducible.

```bat
python -m sca.cli inspect-run-bundle --help
python -m sca.cli run-retrieval-ablation-benchmark --help
python -m sca.cli run-repairability-benchmark --help
python -m sca.cli unique-csp-benchmark-summary --help
```

See `docs/UNIQUE_VERIFIABLE_CSP_BENCHMARKS.md` for Windows CMD commands,
synthetic smoke fixtures, and details on the unique workflow-audit score.

Convert real or archived LLM-CSP/QLIP runs into traceable bundles before running
the unique benchmark:

```bat
python -m sca.cli convert-run-archive-to-bundle ^
  --archive path\to\llm_csp_run ^
  --out-dir reports\traceable_bundles\run_001 ^
  --run-id run_001

python -m sca.cli convert-run-archives-to-bundles ^
  --archives-root reports\e2e_runs ^
  --out-dir reports\traceable_bundles ^
  --summary reports\traceable_bundle_conversion_summary.csv

python -m sca.cli unique-csp-benchmark-summary ^
  --bundles reports\traceable_bundles ^
  --out reports\unique_csp_real_summary.csv ^
  --json reports\unique_csp_real_summary.json ^
  --markdown reports\unique_csp_real_report.md
```

## Python Library Usage

```python
from sca.pipelines.crystallm_style import evaluate_one_cif

record, structure = evaluate_one_cif(
    "examples/cifs/tiny_valid.cif",
    target_formula="NaCl",
    target_space_group="1",
    require_spacegroup=False,
    run_alignn=False,
)
print(record.model_dump())
```

Batch helpers:

```python
from sca.batch import evaluate_manifest

records = evaluate_manifest(
    "examples/cif_manifest.csv",
    path_col="cif_path",
    formula_col="target_formula",
    spacegroup_col="target_space_group",
    method_col="method",
    query_id_col="query_id",
)
```

## Manifest Format

A manifest CSV can include:

```csv
cif_path,target_formula,target_space_group,method,query_id
cifs/tiny_valid.cif,NaCl,1,crystallm,q001
```

`cif_path` is required by default. Relative paths are resolved relative to the manifest file.

## Output Columns

Reports include per-CIF fields for:

- identity: `run_id`, `method`, `query_id`, `input_path`, `file_name`
- parsing and composition: `parse_ok`, `formula`, `reduced_formula`, `target_formula`, `target_formula_match`
- symmetry: `declared_space_group`, `detected_space_group`, `target_space_group`, `space_group_consistent`
- multiplicity: `multiplicity_checked`, `multiplicity_consistent`
- bonds and geometry: `bond_reasonableness_score`, `bond_lengths_reasonable`, `min_distance`, `num_bad_contacts`, `volume`, `volume_per_atom`, `density`, `geometry_ok`
- uniqueness and novelty: `duplicate_group_id`, `is_duplicate`, `is_unique_representative`, `novelty_checked`, `nearest_reference_id`, `known_match`, `novel_by_structure_matcher`, `novelty_error`
- optional ALIGNN: `alignn_ok`, `alignn_model`, `formation_energy_per_atom`
- workflow fields: `pre_dft_valid`, `pre_dft_rank_score`, `selected_for_dft`, `error_type`, `error_message`

## ALIGNN Caveat

ALIGNN formation energy is a surrogate pre-DFT prediction. It is not DFT, not a relaxed energy, and not energy above the convex hull.

If the installed ALIGNN Python API is incompatible, configure a subprocess fallback with `SCA_ALIGNN_COMMAND`. The command may use `{input}` for a temporary POSCAR path and `{model}` for the model name.

```bash
export SCA_ALIGNN_COMMAND="python -m alignn.scripts.pretrained --model {model} --file {input}"
```

## Top-K Selection For Later DFT

`select-top-k` sorts by `pre_dft_rank_score` within each requested group and writes selected rows only, setting `selected_for_dft=true` in the output. Lower scores are better. Failed parses, formula mismatches, bad contacts, geometry failures, multiplicity inconsistencies, and duplicate non-representatives are penalized.

## Advanced energetic and DFT validation

SCA now provides an explicit orchestration layer from immutable generated CIFs through multi-MLIP
screening/relaxation, post-relaxation validation, reproducible CASTEP preparation, Slurm lifecycle,
DFT collection, compatible formation energy, and a distinct compatible-DFT convex hull.

```powershell
python -m sca.cli validate-paper16-manifest
python -m sca.cli build-paper16-baseline
python -m sca.cli verify-backends --json reports/backend_readiness.json
python -m sca.cli dft --help
python -m sca.cli analyse-crystal candidate.cif --level advanced
```

See [Advanced Crystal Analysis](docs/ADVANCED_CRYSTAL_ANALYSIS.md),
[MLIP Relaxation Validation](docs/MLIP_RELAXATION_VALIDATION.md),
[DFT Workflow](docs/DFT_WORKFLOW.md), [DFT Energy Contract](docs/DFT_ENERGY_CONTRACT.md), and
[Hull Analysis](docs/HULL_ANALYSIS.md).

SPP score is not physical energy; ALIGNN formation energy is not DFT; MLIP energy is not DFT
energy; MLIP or DFT relaxation is not proof of thermodynamic stability; DFT relaxation is not
E_hull; and E_hull is not experimental synthesizability.

## Roadmap

- CHGNet and M3GNet surrogate evaluators
- richer pymatgen validity checks
- configurable novelty corpora
- optional Materials Project integration
- additional DFT engine adapters and real compatible reference bundles
