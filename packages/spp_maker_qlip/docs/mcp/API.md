# SPP_Maker MCP API

Server name: `spp-maker`  
Transport: `stdio`

All tools return the same envelope:

```json
{
  "ok": true,
  "trace_id": "trace_...",
  "tool_name": "spp.run_pipeline",
  "result": {},
  "error": null,
  "warnings": []
}
```

Error envelope shape:

```json
{
  "ok": false,
  "trace_id": "trace_...",
  "tool_name": "spp.run_pipeline",
  "result": null,
  "error": {
    "type": "validation_error|execution_error",
    "message": "string",
    "code": "string",
    "details": [{"path": "$.field", "message": "string", "expected": "string|null", "received": "string|null"}]
  },
  "warnings": []
}
```

Input normalization (non-brittle behavior):
- Tools accept canonical request objects and also tolerate common wrapper/alias mistakes.
- Wrapper accepted: top-level `{"arguments": {...}}`.
- Common camelCase aliases are normalized (for example `cifDir` -> `cif_dir`, `outDir` -> `out_dir`, `sppRoot` -> `spp_root`, `artifactRoot` -> `artifact_root`).
- For `spp.run_pipeline`, common top-level fields are hoisted into nested sections:
  - fit fields -> `fit.*`
  - calibration fields -> `calibration.*`
  - filter fields -> `filters.*`
  - `publish_to` -> `publish.publish_to`
- Unknown keys are dropped (not fatal) and emitted as warnings with code `unknown_key_filtered`.

## Tool: `spp.run_pipeline`

### Params (JSON-schema-like)

```json
{
  "trace_id": "string|null",
  "cif_dir": "string (required)",
  "out_dir": "string (required)",
  "name": "string (required)",
  "fit": {
    "fit_method": "neighbors|supercell_gr",
    "r_cut": "number|null",
    "knn": "integer|null",
    "min_d": "number|null",
    "d_min": "number",
    "d_max": "number",
    "alpha": "number",
    "supercell_target_len": "number",
    "r_max": "number",
    "bin_width": "number",
    "sigma": "number",
    "truncate_sigma": "number",
    "gr_eps": "number",
    "max_pairs": "integer|null"
  },
  "covalent": {"enabled": "boolean", "rules_path": "string|null"},
  "calibration": {
    "score_method": "neighbors|supercell_gr",
    "mode": "structure_median|edge_median|quantile",
    "target": "number (required)",
    "q": "number",
    "max_calib": "integer|null",
    "convention": "reward|penalty",
    "min_lambda": "number",
    "max_lambda": "number",
    "bandpass": {
      "enabled": "boolean",
      "d_lo": "number|null",
      "d_hi": "number|null",
      "sigma_lo": "number|null",
      "sigma_hi": "number|null"
    }
  },
  "filters": {
    "meta_csv": "string|null",
    "property_filter": "string|null",
    "property_mode": "include|exclude"
  },
  "publish": {"publish_to": "string|null"},
  "timeout_seconds": "integer|null",
  "dry_run": "boolean",
  "debug": "boolean"
}
```

### Result

```json
{
  "run_id": "string",
  "run_root": "string",
  "final_bundle": "string",
  "content_hash": "string",
  "paths": {
    "fit_spp_root": "string",
    "calibration_json": "string",
    "scaled_spp_root": "string",
    "package_json": "string"
  },
  "published": {"spp": "string", "guidance": "string", "package": "string"} | null,
  "provenance": {
    "git_sha": "string|null",
    "tool": "SPP_Maker",
    "tool_version": "string",
    "params_hash": "string|null",
    "content_hash": "string|null"
  },
  "log_path": "string|null",
  "dry_run": "boolean",
  "cif_count": "integer",
  "output_bytes": "integer|null"
}
```

### Example request

```json
{
  "trace_id": "trace_demo_run",
  "cif_dir": "tests/fixtures/cifs",
  "out_dir": "out/mcp_demo",
  "name": "demo_run",
  "fit": {"fit_method": "neighbors"},
  "calibration": {"target": 5.0},
  "dry_run": true
}
```

### Example response

```json
{
  "ok": true,
  "trace_id": "trace_demo_run",
  "tool_name": "spp.run_pipeline",
  "result": {
    "run_id": "20260305_121314_demo_run_ab12cd34",
    "run_root": "out/mcp_demo/SPP_Runs/20260305_121314_demo_run_ab12cd34",
    "final_bundle": "out/mcp_demo/Final_QLIP_output/20260305_121314_demo_run_ab12cd34",
    "content_hash": "8f8b7d...",
    "paths": {
      "fit_spp_root": "out/mcp_demo/SPP_Runs/20260305_121314_demo_run_ab12cd34/fit/spp_root",
      "calibration_json": "out/mcp_demo/SPP_Runs/20260305_121314_demo_run_ab12cd34/calibrate/calibration.json",
      "scaled_spp_root": "out/mcp_demo/SPP_Runs/20260305_121314_demo_run_ab12cd34/calibrate/scaled_spp_root",
      "package_json": "out/mcp_demo/SPP_Runs/20260305_121314_demo_run_ab12cd34/package/package.json"
    },
    "published": null,
    "provenance": {
      "git_sha": "abc123...",
      "tool": "SPP_Maker",
      "tool_version": "0.1.0",
      "params_hash": "b43e...",
      "content_hash": "8f8b7d..."
    },
    "log_path": "out/mcp_demo/logs/20260305_121314_demo_run_ab12cd34.jsonl",
    "dry_run": true,
    "cif_count": 2,
    "output_bytes": 0
  },
  "error": null,
  "warnings": []
}
```

## Tool: `spp.check_compat`

### Params

```json
{"trace_id": "string|null", "spp_root": "string (required)", "strict": "boolean", "debug": "boolean"}
```

### Result

```json
{"ok": "boolean", "files_checked": "integer", "failed_count": "integer", "failures": [{"path": "string", "reason": "string", "line_no": "integer|null"}]}
```

### Example request

```json
{"spp_root": "out/demo/spp_root", "strict": true}
```

### Example response

```json
{
  "ok": true,
  "trace_id": "trace_9f2a...",
  "tool_name": "spp.check_compat",
  "result": {"ok": true, "files_checked": 12, "failed_count": 0, "failures": []},
  "error": null,
  "warnings": []
}
```

## Tool: `spp.package_for_qlip`

### Params

```json
{
  "trace_id": "string|null",
  "run_root": "string|null",
  "spp_root": "string|null",
  "calibration_json": "string|null",
  "out_dir": "string (required)",
  "name": "string (required)",
  "include_registry_snapshot": "boolean",
  "debug": "boolean"
}
```

Validation rule: provide either `run_root` or (`spp_root` + `calibration_json`).

### Result

```json
{
  "run_id": "string",
  "final_bundle_path": "string",
  "package_json_path": "string",
  "contents": ["string", "..."],
  "provenance": {"git_sha": "string|null", "tool": "SPP_Maker", "tool_version": "string", "params_hash": "string|null", "content_hash": "string|null"},
  "output_bytes": "integer"
}
```

### Example request

```json
{
  "spp_root": "out/demo/spp_root",
  "calibration_json": "out/demo/calibration.json",
  "out_dir": "out",
  "name": "demo_pkg"
}
```

### Example response

```json
{
  "ok": true,
  "trace_id": "trace_2e7c...",
  "tool_name": "spp.package_for_qlip",
  "result": {
    "run_id": "20260305_121530_demo_pkg_5a0f4f73",
    "final_bundle_path": "out/Final_QLIP_output/20260305_121530_demo_pkg_5a0f4f73",
    "package_json_path": "out/Final_QLIP_output/20260305_121530_demo_pkg_5a0f4f73/package.json",
    "contents": ["README.txt", "compat_report.txt", "guidance/calibration.json", "package.json"],
    "provenance": {"git_sha": "abc123...", "tool": "SPP_Maker", "tool_version": "0.1.0", "params_hash": null, "content_hash": null},
    "output_bytes": 9842
  },
  "error": null,
  "warnings": []
}
```

## Tool: `spp.publish_to_qlip_outputs`

### Params

```json
{
  "trace_id": "string|null",
  "kind": "spp|guidance|package|constraint",
  "artifact_root": "string (required)",
  "qlip_outputs_path": "string (required)",
  "name": "string (required)",
  "overwrite": "boolean",
  "strict_compat": "boolean",
  "copy_mode": "copy|symlink",
  "set_latest": "boolean",
  "debug": "boolean"
}
```

### Result

```json
{
  "published_run_id": "string",
  "published_path": "string",
  "index_json_path": "string",
  "latest_pointer_path": "string",
  "latest_pointer_value": "string",
  "provenance": {"git_sha": "string|null", "tool": "SPP_Maker", "tool_version": "string", "params_hash": "string|null", "content_hash": "string|null"}
}
```

### Example request

```json
{
  "kind": "spp",
  "artifact_root": "out/demo/spp_root",
  "qlip_outputs_path": "QLIP_Outputs",
  "name": "demo_publish",
  "overwrite": false
}
```

### Example response

```json
{
  "ok": true,
  "trace_id": "trace_7bc1...",
  "tool_name": "spp.publish_to_qlip_outputs",
  "result": {
    "published_run_id": "20260305_121645_demo_publish_93f8a61f",
    "published_path": "QLIP_Outputs/SPP/runs/20260305_121645_demo_publish_93f8a61f",
    "index_json_path": "QLIP_Outputs/index.json",
    "latest_pointer_path": "QLIP_Outputs/SPP/latest.txt",
    "latest_pointer_value": "SPP/runs/20260305_121645_demo_publish_93f8a61f",
    "provenance": {"git_sha": "abc123...", "tool": "SPP_Maker", "tool_version": "0.1.0", "params_hash": null, "content_hash": null}
  },
  "error": null,
  "warnings": []
}
```
