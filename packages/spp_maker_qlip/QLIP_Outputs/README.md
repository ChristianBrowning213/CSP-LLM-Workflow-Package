# QLIP_Outputs

`QLIP_Outputs/` is the canonical handoff bundle for all QLIP-facing artifacts.

## Registry layout

```text
QLIP_Outputs/
  index.json
  schema/
    qlip_outputs_index.schema.json
  INTEGRATION.md
  SPP/
    latest.txt
    runs/<run_id>/...
  GUIDANCES/
    latest.txt
    runs/<run_id>/...
  CONSTRAINTS/
    latest.txt
    runs/<run_id>/...
  PACKAGES/
    latest.txt
    runs/<run_id>/...
```

- `index.json` is the machine-readable registry of published runs.
- `latest.txt` pointers are per-kind and store POSIX-style relative paths.
- `schema/qlip_outputs_index.schema.json` documents the v1 index shape.

## Artifact kinds

- `spp`:
  - run payload includes `spp_root/`, `manifest.json`, `compat_report.txt`, `publish_meta.json`.
- `guidance`:
  - run payload includes `artifact_root/` and `publish_meta.json`.
- `constraint`:
  - run payload includes `artifact_root/` and `publish_meta.json`.
- `package`:
  - run payload includes `artifact_root/`, `package.json`, and `publish_meta.json`.

## Publish examples

Publish SPP:

```bash
python scripts/publish_qlip_outputs.py \
  --kind spp \
  --spp_root out/demo_prop_spp/demo/spp_all \
  --name spp_all
```

Publish guidance:

```bash
python scripts/publish_qlip_outputs.py \
  --kind guidance \
  --artifact_root path/to/guidance_dir \
  --name g1
```

Publish constraint:

```bash
python scripts/publish_qlip_outputs.py \
  --kind constraint \
  --artifact_root path/to/constraint_dir \
  --name c1
```

## Listing registry contents

```bash
python scripts/qlip_outputs_list.py --qlip_outputs QLIP_Outputs
```

## QLIP consumption

Use `INTEGRATION.md` for integration snippets and expected SPP folder format.
