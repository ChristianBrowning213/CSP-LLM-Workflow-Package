# SPP migration fileset

Pre-copy selection derived from the Ticket 2 manifest and the import graph at
`C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP`, branch `SPP_MCP`, commit
`3a2d557811973265f3373ec881cc8057a89789d2`, with a clean source worktree.

## Required-pair extraction

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker_qlip/required_pair_extraction.py` | `src/llm_csp/spp/required_pairs.py` | Canonical formula-required pair extraction and fresh POT construction. |
| `src/spp_maker_qlip/corpus_quality.py` | `src/llm_csp/spp/corpus_quality.py` | Required corpus suitability diagnostics. |
| `src/spp_maker_qlip/pot_quality.py` | `src/llm_csp/spp/quality.py` | Required generated-POT quality gate. |

## CIF parsing

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker/io_cif.py` | `src/llm_csp/spp/io_cif.py` | ASE CIF loading and deterministic directory ordering. |

## Pair-distance processing

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker/neighbors.py` | `src/llm_csp/spp/neighbors.py` | Periodic minimum-image neighbor edges. |
| `src/spp_maker/fit_hist.py` | `src/llm_csp/spp/fit_hist.py` | Canonical pair keys and distance histograms. |
| `src/spp_maker/fit_phi.py` | `src/llm_csp/spp/fit_phi.py` | Deterministic statistical-potential construction. |
| `src/spp_maker/weights.py` | `src/llm_csp/spp/weights.py` | Optional band-pass weighting used by fitting/scoring. |

## POT loading

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker/pot_io.py` | `src/llm_csp/spp/pot_io.py` | QLIP-compatible POT parser/writer. |
| `src/spp_maker/spp_model.py` | `src/llm_csp/spp/model.py` | In-memory pair-potential model for standalone scoring. |
| `src/spp_maker/pot_compat.py` | `src/llm_csp/spp/compat.py` | Strict POT-root compatibility checks. |

## POT selection/export

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker/export.py` | `src/llm_csp/spp/export.py` | Canonical `<A>-<B>/<A>-<B>.POT` writer. |
| selected pair/path behavior from `src/spp_maker_qlip/qlip_package.py` | `src/llm_csp/spp/library.py` | Minimal packaging adapter for explicit external POT roots, reverse-name fallback, canonical export, missing coverage, provenance, and hashes. |

The large source `qlip_package.py` is not copied wholesale because its
`QLIP_Outputs` registry and `Final_QLIP_output` layout belong to orchestration.

## Scoring

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker/score.py` | `src/llm_csp/spp/score.py` | Standalone validation scorer. |

## Configuration

| Source | Destination | Reason |
| --- | --- | --- |
| `src/spp_maker/covalent_filter.py` | `src/llm_csp/spp/covalent_filter.py` | Optional covalent exclusion policy used by supported fitting. |
| `rules/covalent_rules.yaml` | `configs/examples/covalent_rules.yaml` | Small policy example; makes the PyYAML boundary testable. |
| package marker/public facade (new) | `src/llm_csp/spp/__init__.py` | Supported `llm_csp.spp` API. |

`SPP_SOURCE_POT_ROOT` is introduced only for the external-library adapter.
Fresh fitting continues to require explicit `cif_dir` and `out_root` arguments.

## Schemas

No schema file is on the selected direct API graph. The existing JSON manifests
written by the source exporter are preserved; `library.py` adds the minimum
structured subset-export manifest required for installed orchestration.

## Tests

| Manifest/source behavior | Destination |
| --- | --- |
| fit histogram, phi, POT I/O/export, CIF/neighbors, pair diagnostics | `tests/unit/spp/` |
| standalone scoring | `tests/unit/spp/test_score.py` |
| required-pair construction and deterministic mixed-CIF evidence union | `tests/integration/spp/test_required_pair_builder.py` |
| QLIP POT handoff, reverse naming, missing coverage | `tests/integration/spp/test_qlip_handoff.py` |
| SrTiO3 export-to-QLIP solve | `tests/integration/spp/test_srtio3_qlip.py` |

Tests build synthetic CIFs and POT libraries or use the already packaged QLIP
SrTiO3 POT resources. Source corpus/POT fixtures are not copied.

## Examples

| Source | Destination |
| --- | --- |
| new installed API example using bundled QLIP SrTiO3 resources | `examples/spp_only/export_required_pairs.py` |

## Exclusions

- broad `QLIP_Outputs`, regulator POT libraries, generated runs, reports, and
  benchmark artifacts
- CLI, calibration campaign, publishing/index registry, MCP, paper scripts,
  plotting, bulk corpus preparation, and high-level run orchestration
- `common_contract.py` blend/regulator union logic: not called by canonical
  `export_required_pair_spp_root`; ownership remains later orchestration
- source CIF fixtures and generated POT fixtures

The manifest's original classifications remain historical inventory; Ticket 6
adds resolution notes without reclassifying them.
