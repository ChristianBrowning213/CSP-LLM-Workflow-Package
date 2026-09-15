# Run The System From Text

These entrypoints run the existing CSP pipeline from a plain-language request and place outputs under `local_runs/`.

Terminal text:

```powershell
.\.venv\Scripts\python.exe scripts\run_system_from_terminal.py "Find a stable TiO2 crystal candidate"
```

Text file:

```powershell
.\.venv\Scripts\python.exe scripts\run_system_from_file.py request.txt
```

The file runner treats each non-empty, non-comment line as one request. Lines beginning with `#` are ignored.

Useful options:

```powershell
--mode live
--mode stub
--out-root local_runs
--run-id smoke_batio3_text_entrypoint
--batch-id smoke_batch_text_entrypoint
--config config.yml
--with-guidance true
--fail-on-pipeline-failure
--stop-on-error
```

Each run creates a timestamped directory containing a workspace and `summary.json`. The summary records the original text, pipeline status, manifest path, and any generated CIF files found in the run directory.

Batch runs also write `batch_summary.json`, `batch_summary.md`, `generation_log.csv`, `generation_log.jsonl`, and `generated_cifs_manifest.csv`.

Exit-code policy:

- By default, the scripts exit `0` once the entrypoint completes and writes its summary files, even if the underlying pipeline status is `FAILED`.
- Use `--fail-on-pipeline-failure` for CI-style strict behavior. In that mode, a recorded pipeline failure exits `2` after summaries are written.
- Script/internal failures before or while writing summaries exit `1`.

A failure such as `spp_corpus_unavailable:no_export_ready_candidate` means the live system could not stage/export local SPP evidence for that request. It is recorded in the summary as a pipeline failure; it does not mean the entrypoint script failed.
