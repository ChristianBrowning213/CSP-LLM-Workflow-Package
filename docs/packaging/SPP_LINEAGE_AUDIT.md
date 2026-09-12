# SPP-Maker / ipcsp-spp lineage audit

Audit date: 2026-09-12.

This audit compares the SPP-Maker-QLIP scientific source revision
`3a2d557811973265f3373ec881cc8057a89789d2` with `ipcsp-spp` revision
`ef9c5cc2924fae6ee35d0c5e526c132c17e1a014`. It assesses observable code
lineage, not legal ownership or scientific-method priority.

## Evidence examined

- complete reachable Git histories and commit identities;
- repository remotes and initial commits;
- selected migration paths in `SPP_MIGRATION_FILESET.md`;
- Python function/class names and source comments;
- exact nontrivial source-line matches;
- token-sequence similarity with comments/formatting removed;
- cross-references to `ipcsp`, its contributors, or its module names; and
- Git commit-object overlap between the two repositories.

Results:

- the repositories share zero Git commits and have separate initial histories;
- no selected SPP-Maker file is blob-identical to an `ipcsp-spp` file;
- no top-level function or class name is shared;
- no identical nontrivial source line of 40 or more characters was found;
- no SPP-Maker source/documentation cross-reference to `ipcsp-spp`, Vladimir
  Gusev, Esma Kurban, Daniel Typov, or the Leverhulme centre was found; and
- each selected SPP-Maker file traces only to a Christian Browning Git identity.

The nearest token similarities are low. `pot_io.py` versus `ipcsp2/spp.py` is
0.2026 and `pot_compat.py` versus `ipcsp2/spp.py` is 0.1844; all other selected
files are at or below 0.1549 except `neighbors.py` at 0.1416. Shared Python
syntax and the common POT-file domain can produce such values. These scores are
evidence against literal copying, not proof of independent authorship.

## Module classifications

| Packaged destination | Frozen SPP-Maker source | Relative to `ipcsp-spp` | Evidence note |
| --- | --- | --- | --- |
| `src/llm_csp/spp/io_cif.py` | `src/spp_maker/io_cif.py` | `ORIGINAL_TO_SPP_MAKER` | CIF/ASE loader; best cross-repo token similarity 0.1327 |
| `src/llm_csp/spp/neighbors.py` | `src/spp_maker/neighbors.py` | `ORIGINAL_TO_SPP_MAKER` | ASE minimum-image neighbor implementation; no matching identifier/line; similarity 0.1416 |
| `src/llm_csp/spp/fit_hist.py` | `src/spp_maker/fit_hist.py` | `ORIGINAL_TO_SPP_MAKER` | Histogram/binning implementation absent from ipcsp API; similarity 0.1216 |
| `src/llm_csp/spp/fit_phi.py` | `src/spp_maker/fit_phi.py` | `ORIGINAL_TO_SPP_MAKER` | Probability/phi pipeline; no matching identifier/line; similarity 0.1239 |
| `src/llm_csp/spp/weights.py` | `src/spp_maker/weights.py` | `ORIGINAL_TO_SPP_MAKER` | Band-pass weighting API absent from ipcsp; similarity 0.1061 |
| `src/llm_csp/spp/pot_io.py` | `src/spp_maker/pot_io.py` | `ORIGINAL_TO_SPP_MAKER` | Both parse POT text, but code structure/names differ and no line matches; similarity 0.2026 |
| `src/llm_csp/spp/model.py` | `src/spp_maker/spp_model.py` | `ORIGINAL_TO_SPP_MAKER` | Same scientific domain as `ipcsp2.spp`, but different model/API and no expression match; similarity 0.1083 |
| `src/llm_csp/spp/compat.py` | `src/spp_maker/pot_compat.py` | `ORIGINAL_TO_SPP_MAKER` | Compatibility audit has no ipcsp counterpart; similarity 0.1844 reflects POT parsing vocabulary |
| `src/llm_csp/spp/export.py` | `src/spp_maker/export.py` | `ORIGINAL_TO_SPP_MAKER` | Structured exporter absent from ipcsp API; similarity 0.1345 |
| `src/llm_csp/spp/score.py` | `src/spp_maker/score.py` | `ORIGINAL_TO_SPP_MAKER` | ASE edge-scoring implementation; no matching identifier/line; similarity 0.1174 |
| `src/llm_csp/spp/covalent_filter.py` | `src/spp_maker/covalent_filter.py` | `ORIGINAL_TO_SPP_MAKER` | Rule-based filter absent from ipcsp; similarity 0.1549 |
| `src/llm_csp/spp/required_pairs.py` | `src/spp_maker_qlip/required_pair_extraction.py` | `ORIGINAL_TO_SPP_MAKER` | Formula/pair fitting boundary absent from ipcsp; similarity 0.1087 |
| `src/llm_csp/spp/corpus_quality.py` | `src/spp_maker_qlip/corpus_quality.py` | `ORIGINAL_TO_SPP_MAKER` | Corpus suitability audit absent from ipcsp; similarity 0.1085 |
| `src/llm_csp/spp/quality.py` | `src/spp_maker_qlip/pot_quality.py` | `ORIGINAL_TO_SPP_MAKER` | POT quality metrics absent from ipcsp; similarity 0.1199 |
| `src/llm_csp/spp/library.py` | selected behavior from `src/spp_maker/qlip_package.py` plus new packaging adapter | `ORIGINAL_TO_SPP_MAKER` | No equivalent packaging API; source-file similarity 0.0791 |

## Conclusion and permission boundary

No observable evidence identifies packaged SPP source code as copied from or
derived in expression from `ipcsp-spp`. On the available evidence, every
migrated module is classified `ORIGINAL_TO_SPP_MAKER` relative to that codebase.
The common SPP scientific method and POT format remain related subject matter;
the appropriate paper citation and any non-code intellectual-property lineage
still require human confirmation.

No `ipcsp-spp` software permission is currently identified as necessary for
the selected source code. This finding does not license SPP-Maker-QLIP: its own
rights holder and any institution must still authorize redistribution. The
separately blocked POT assets are outside this code-lineage conclusion.
