# QLIP Integration (Recommended + Advanced)

## Recommended: one command

Run the full pipeline with a single command:

```bash
python -m spp_maker.cli run \
  --name ABO3_run \
  --cif_dir data/mp_ABO3_fe/cifs \
  --out_dir out \
  --fit_method supercell_gr \
  --calib_score_method neighbors \
  --target 10.0 \
  --max_calib 200 \
  --publish_to QLIP_Outputs
```

Then use the bundle in:

```text
out/Final_QLIP_output/<run_id>/
```

Minimal QLIP snippet:

```python
from qlip.spp import SPPCollection

spp_dir = "./spp_root"
collection = SPPCollection(spp_dir)
collection.load(task.pairs)
allocation.spp_collection = collection
```

## Advanced / debugging: manual steps

If you need to debug stages separately:

1. `spp-maker fit ...`
2. `spp-maker calibrate ... --write_scaled_root ...`
3. `python scripts/publish_qlip_outputs.py --kind spp ...`
4. `python scripts/publish_qlip_outputs.py --kind guidance ...`
5. bind artifacts with `package.json`

The recommended path is still `spp-maker run`, which handles all of these stages deterministically.
