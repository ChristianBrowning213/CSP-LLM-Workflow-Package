# Guided SPP Failure Diagnostic

## Scope

This diagnostic covers the guided text entrypoint failure seen through:

```powershell
python scripts\run_system_from_terminal.py --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_guided_before --run-id run_001 "Generate a plausible BaTiO3 oxide perovskite candidate with the requested chemistry and broad perovskite-like design intent."
```

Observed failure:

```text
spp_corpus_unavailable:no_export_ready_candidate_and_no_regularisation_fallback
```

The no-guidance control succeeded, and earlier full-100 regularised runs succeeded.

## Root Cause

The regularisation fallback was missing from the guided text entrypoint invocation.

The fallback path itself was present and valid:

```text
C:\Users\brown\Downloads\SPP\SPP\SPP\SPP
```

The earlier full-100 regularised run worked because its runner supplied Config C execution overrides explicitly:

```json
{
  "allow_partial_spp_guidance": true,
  "allow_qlip_without_spp": true,
  "spp_regularisation_dir": "C:\\Users\\brown\\Downloads\\SPP\\SPP\\SPP\\SPP",
  "spp_regularisation_weight": 2.0,
  "spp_missing_pair_policy": "soft_repulsive",
  "spp_guidance_weight": 10.0,
  "runtime_spp_guidance_weight": 10.0
}
```

Before the fix, `scripts/run_system_from_terminal.py`, `scripts/run_system_from_file.py`, and the shared text entrypoint defaulted `regularisation_spp_dir` to `None`. As a result, guided terminal/file runs did not load the same Config C fallback used by `scripts/run_full_100_skill_loop_benchmark.py`.

## Crystal-DB Export-Ready Status

Crystal-DB retrieval did return a candidate. The failure was not caused by an empty retrieval result.

Fresh guided failure artifacts showed:

```json
{
  "candidate_id": "mp-1",
  "allow_export": 0,
  "cif_export_status": "blocked",
  "cif_export_error": "policy_blocked",
  "cif_export_path": null
}
```

The SPP corpus selection therefore had:

```json
{
  "exportable_count": 0,
  "blocked_count": 1,
  "blocked_ids": ["mp-1"],
  "selection_reason": "no_export_ready_candidate_available"
}
```

No CIF was staged for SPP guidance, and without a configured regularisation fallback the pipeline correctly stopped with:

```text
spp_corpus_unavailable:no_export_ready_candidate_and_no_regularisation_fallback
```

## Why The Previous Full-100 Run Worked

The previous regularised full-100 text-entrypoint run had the same retrieval/corpus outcome for this prompt: the retrieved candidate was policy-blocked and no export-ready CIF was staged.

It still succeeded because the manifest included Config C regularisation execution overrides. The pipeline then wrote:

```text
spp_regularisation_fallback.json
```

with:

```json
{
  "reason": "configured_regularisation_partial_guidance",
  "regularisation_spp_dir": "C:\\Users\\brown\\Downloads\\SPP\\SPP\\SPP\\SPP",
  "regularisation_weight": 2.0,
  "missing_pair_policy": "soft_repulsive"
}
```

The QLIP request proceeded with partial regularisation guidance and generated a CIF.

## Fix Applied

The text entrypoints now default to the same Config C fallback used by the full-100 benchmark runner.

Changed files:

- `src/sok_llm_orchestrator/system_entrypoint.py`
- `scripts/run_system_from_terminal.py`
- `scripts/run_system_from_file.py`
- `src/sok_llm_orchestrator/orchestrator/pipeline.py`
- `tests/test_system_text_entrypoints.py`
- `tests/test_full_100_regularisation_config.py`
- `diagnostics/skill_loop_guided_spp_failure_diagnostic.md`

Implementation details:

- `run_system_text` now defaults `regularisation_spp_dir` to `CONFIG_C_REGULARISATION_SPP_DIR`.
- The fallback is only applied when guided SPP is enabled.
- Terminal and file CLIs now default `--regularisation-spp-dir` from Config C.
- Passing an empty regularisation argument disables fallback explicitly for diagnostic runs.
- The pipeline now emits `spp_corpus_unavailable_diagnostics.json` before raising the no-corpus/no-fallback failure.
- The raw stub pipeline behavior was left unchanged; no global fake CrystalDB export override is introduced by this fix.

The diagnostic JSON records retrieval export status, corpus selection, staged CIFs, fallback configuration, required regularisation pair-file status, SPP/Crystal-DB/QLIP command settings, cwd, and relevant environment values.

## Validation

### Failing Guided Command Before Fix

Command:

```powershell
python scripts\run_system_from_terminal.py --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_guided_before --run-id run_001 "Generate a plausible BaTiO3 oxide perovskite candidate with the requested chemistry and broad perovskite-like design intent."
```

Result:

```text
FAILED
spp_corpus_unavailable:no_export_ready_candidate_and_no_regularisation_fallback
```

### No-Guidance Control

Command:

```powershell
python scripts\run_system_from_terminal.py --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_no_guidance_control --run-id run_001 --with-guidance false "Generate a plausible BaTiO3 oxide perovskite candidate with the requested chemistry and broad perovskite-like design intent."
```

Result:

```text
SUCCEEDED
```

Generated CIF:

```text
C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_no_guidance_control\run_001\workspace\runs\033a837b-c5e4-514c-bc0a-3ad32deb2808\artifacts\qlip\solution.cif
```

### Guided Command After Fix

Command:

```powershell
python scripts\run_system_from_terminal.py --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_guided_after_current --run-id run_001 "Generate a plausible BaTiO3 oxide perovskite candidate with the requested chemistry and broad perovskite-like design intent."
```

Result:

```text
SUCCEEDED
```

Generated CIF:

```text
C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_guided_after_current\run_001\workspace\runs\e71a559a-d89a-527a-a3a5-b9126eb2c6eb\artifacts\qlip\solution.cif
```

The after-fix manifest includes Config C fallback overrides, and `spp_regularisation_fallback.json` confirms partial regularisation guidance.

### Forced No-Fallback Diagnostic After Fix

PowerShell required the empty value form below:

```powershell
python scripts\run_system_from_terminal.py --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_guided_no_fallback_after_current --run-id run_001 --regularisation-spp-dir= "Generate a plausible BaTiO3 oxide perovskite candidate with the requested chemistry and broad perovskite-like design intent."
```

Result:

```text
FAILED
spp_corpus_unavailable:no_export_ready_candidate_and_no_regularisation_fallback
```

Diagnostic artifact:

```text
C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs\debug_guided_no_fallback_after_current\run_001\workspace\runs\9418ff1b-76bc-548d-9311-f106b6c8550f\artifacts\spp_corpus_unavailable_diagnostics.json
```

Key diagnostic facts:

```json
{
  "retrieval_candidate_count": 1,
  "export_ready_candidate_count": 0,
  "retrieval_export_rows": [
    {
      "structure_id": "mp-1",
      "cif_export_status": "blocked",
      "cif_export_error": "policy_blocked",
      "allow_export": 0
    }
  ],
  "regularisation_fallback": {
    "configured": false,
    "allow_qlip_without_spp": false,
    "path_exists": false
  }
}
```

### Focused Tests

Command:

```powershell
$env:TMP="$($PWD.Path)\.pytest_tmp_env"; $env:TEMP="$($PWD.Path)\.pytest_tmp_env"; New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null; .\.venv\Scripts\python.exe -m pytest tests\test_system_text_entrypoints.py tests\test_full_100_regularisation_config.py tests\e2e\test_spp_blocked_corpus_fallback_stub.py -q --basetemp "$($PWD.Path)\.pytest_tmp"
```

Result:

```text
23 passed in 2.44s
```

### Full Test Attempt

Command:

```powershell
$env:TMP="$($PWD.Path)\.pytest_tmp_env"; $env:TEMP="$($PWD.Path)\.pytest_tmp_env"; New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null; .\.venv\Scripts\python.exe -m pytest -q --basetemp "$($PWD.Path)\.pytest_tmp"
```

Result:

```text
65 failed, 747 passed, 15 skipped, 14 warnings in 284.00s
```

First failing test:

```text
tests/e2e/test_cli_run_structured_task_spec_stub.py::test_cli_run_structured_task_spec_stub
KeyError: 'objective'
```

This first failure is outside the guided text-entrypoint fallback path: it concerns the historical top-level QLIP request `objective` field expected by a broader CLI stub test. The full-suite run also reported unrelated failures in agentic import-safety, SPP packaging, Phase 1 objective mapping, and stub pipeline areas. Per the repository halt rule, no unrelated broad-suite repair was attempted.

## Exact SCA Full Intent Benchmark Command

For an auditable full intent benchmark run from the Skill-Loop-CSP repo after this fix:

```powershell
python scripts\run_system_from_file.py local_runs\full_100_seeded_20260626_prompts.txt --out-root C:\Users\brown\Documents\GitHub\Structured_Crystal_Analyser\local_runs --batch-id full_100_text_entrypoint_regularised --spp-guidance-weight 10.0 --regularisation-weight 2.0 --missing-pair-policy soft_repulsive --regularisation-spp-dir "C:\Users\brown\Downloads\SPP\SPP\SPP\SPP"
```

The explicit `--regularisation-spp-dir` is still recommended for benchmark audit logs, even though the terminal and file entrypoints now default to the Config C path.
