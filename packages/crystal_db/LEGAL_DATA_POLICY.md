# Legal & Data Policy

This document describes how Crystal-DB enforces legal/data governance for crystal structure records.

## Policy Rules

Each source is mapped to a policy in `policies.yaml`. Policies define whether raw CIF can be stored, returned, and exported.

Policy fields:
- `allow_cif_store`: store raw CIF text in the database
- `allow_cif_return`: return CIF via `get` or in any CLI output
- `allow_derivatives`: store derived descriptors/fingerprints
- `allow_export`: allow exporting run bundles containing that record
- `license_notes`: human-readable license/usage notes

## Enforcement Points

Crystal-DB enforces policies in code:
- `get_structure` returns `cif_text=null` when `allow_cif_return=false` or record is restricted.
- Audit logs always redact `cif_text` from tool inputs/outputs.
- Exports (`export-run`) contain redacted tool traces and never include CIF payloads.
- All outputs include `source`, `source_id`, `retrieved_at`, and `license_notes`.

## Allowed Sources

Defined in `policies.yaml`:
- `synthetic`: unrestricted, for testing
- `local_cif`: local files; export disabled by default
- `restricted`: CIF return disabled and export disabled
- `default`: deny storage/return if a policy is unknown

## How to Set Policy for Ingest

Use the `--policy` flag during ingestion:

```powershell
python -m crystal_db ingest-folder --db data\crystal_phase0.db --path data\cifs --source local_cif --policy local_cif
```

If a CIF is restricted, you should select the `restricted` policy or add a new policy to `policies.yaml`.

## Notes

- Policy rules are enforced uniformly across CLI tools, agent answers, and audit/export logs.
- If a policy changes, re-ingestion is recommended to update stored fields.
