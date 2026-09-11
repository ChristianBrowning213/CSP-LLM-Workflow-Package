# SCA validation contract

## Frozen backend

- Repository: `Structured_Crystal_Analyser`
- Remote: `https://github.com/ChristianBrowning213/Structured_Crystal_Analyser.git`
- Branch inspected: `main`
- Commit: `e5b291312151f34949a5e6ef0f43bebfeb752bc9`
- Distribution/import name: `sca`
- Reported version: `0.1.0`
- Source status at both migration gates: clean

SCA remains an external scientific interface. No SCA implementation, model,
benchmark, report, corpus, or cache is copied into this repository. Ticket 11
removed the root Git dependency and `validation` extra because the frozen SCA
repository has no explicit licence. The commit below remains compatibility
provenance only; public users are not directed to install it. The adapter loads
a separately authorized compatible installation lazily when one is present.

## Actual supported interfaces

At the frozen revision the general facade is:

```python
evaluate_one_cif(
    cif_path: str | Path,
    target_formula: str | None = None,
    target_space_group: str | None = None,
    method: str | None = None,
    query_id: str | None = None,
    require_spacegroup: bool = False,
    run_alignn: bool = False,
    reference_structures: dict[str, pymatgen.core.Structure] | None = None,
    run_id: str | None = None,
) -> tuple[CrystalEvalRecord, Structure | None]
```

It reads one CIF path and returns an SCA Pydantic record plus the parsed
Pymatgen structure, or `None` for the structure after parse/species failure.
Missing and malformed files normally become records with `parse_ok=False` and
`error_type`/`error_message`. Exceptions escaping the pipeline are possible and
are normalized by the LLM-CSP adapter as evaluation failures. If no `run_id` is
provided SCA generates a UUID. The selected function has no output-directory
argument and writes no report or modified CIF; it reads the input without
mutating it.

The topology function is:

```python
family_topology_metrics(
    structure: pymatgen.core.Structure,
    policy: str,
) -> tuple[dict[str, Any], dict[str, Any]]
```

It uses Pymatgen `CrystalNN` and returns scientific metrics plus diagnostic
details. Frozen policies are `ROCKSALT`, `FLUORITE`, `PEROVSKITE_3D`, `SPINEL`,
`OLIVINE`, `LAYERED_OXIDE`, `ARGYRODITE_ORDERED`,
`HALIDE_PEROVSKITE_3D`, `NASICON_ORDERED`, and
`GENERIC_SCAFFOLD_ONLY`. Scientific statuses are `PASS`, `PARTIAL`, `FAIL`, or
`NOT_APPLICABLE`. SCA's benchmark facade rejects unknown policies; the adapter
does the same before calling the lower-level function.

## Public LLM-CSP adapter

```python
from llm_csp.validation import validate_cif, validate_family_topology
```

`validate_cif` mirrors all supported general-pipeline arguments. It returns a
`ValidationResult` containing status, parseability, SCA's pre-DFT validity,
composition, general metrics, warnings/errors, backend provenance, and the full
unchanged SCA record under `details["sca_record"]`.

`validate_family_topology` accepts a Pymatgen structure and policy and returns a
`TopologyValidationResult` containing availability, SCA topology status,
derived match state (`PASS=True`, `FAIL/PARTIAL=False`,
`NOT_APPLICABLE=None`), exact metrics/details, warnings/errors, and provenance.

Both result envelopes include adapter schema `llm_csp.validation.v1`, backend
name, installed SCA version when discoverable, and the revision against which
the adapter was validated. The validated revision is contract provenance, not
a claim that an arbitrary runtime checkout has that Git state.

## Failure semantics

- `backend_unavailable`: SCA or a required import dependency cannot load.
- `parse_failure`: SCA returned a record with `parse_ok=False`; its error is
  preserved.
- `evaluation_failure`: an exception escaped an available SCA call.
- `unsupported_policy`: the requested family is outside SCA's frozen catalog.
- `evaluated`: SCA completed. Scientific validity or topology may still be
  false, `PARTIAL`, `FAIL`, or `NOT_APPLICABLE`; these are not backend failures.

No fallback validator, geometry repair, threshold change, retry, or fabricated
metric is used.

## Dependencies, network, and artifacts

SCA 0.1.0 declares pandas, Pydantic, Pymatgen, Rich, tqdm, and Typer. General
validation and topology are local/in-memory after installation and require no
network access. Reference novelty is evaluated only when caller-supplied
structures are provided.

`run_alignn=False` is the supported default and does not invoke ALIGNN. Setting
it true opts into SCA's separately optional ALIGNN package/model or configured
subprocess and may entail external model availability. CHGNet is not called by
either supported interface and remains a separate optional SCA feature. No
CHGNet/ALIGNN weights are packaged here.

The calls do not write artifacts. If later SCA APIs add report output, the
LLM-CSP boundary must require a caller-owned output root before exposing it.

## Versioning risk

Only these two SCA interfaces are supported. Later workflow code must not import
arbitrary `sca.evaluators` modules. An SCA upgrade requires contract and parity
tests before changing the pinned revision.

## Ticket 7 verification

- Validation unit tests: 6 passed.
- Validation integration tests: 5 passed.
- Installed-wheel validation tests: 11 passed outside the source trees.
- Repository-wide gate: 129 passed and 1 skipped.
- Synthetic NaCl general parity: full SCA record equal; parse, target formula,
  geometry, bond score, validity, and rank score unchanged.
- Synthetic NaCl `ROCKSALT` topology parity: direct and adapter metrics/details
  equal, with `PASS` and all three frozen checks true.
- Installed QLIP SrTiO3 handoff: solve `OPTIMAL`, objective
  `4.883033620558714`; validation `evaluated`, parseable, target formula match,
  geometry valid, and pre-DFT valid.

Installed paths were beneath
`C:\Users\brown\AppData\Local\Temp\ticket7-installed-e8f5573dd4654e239ad9e8784c43870c\venv\Lib\site-packages`
for `llm_csp`, `llm_csp.validation`, `qlip`, and `sca`.
