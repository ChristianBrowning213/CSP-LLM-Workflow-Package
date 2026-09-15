# Optional Benchmark Backends

The base SCA install stays lightweight:

```bash
pip install -e .
```

Heavy surrogate/MLIP libraries are optional extras. Install only the backends you
intend to run:

```bash
pip install -e .[alignn]
pip install -e .[chgnet]
pip install -e .[matgl]
pip install -e .[mlip]
pip install -e .[benchmark-full]
pip install -e .[advanced-mlip]
pip install -e .[benchmark-advanced]
```

The `benchmark-full` extra installs ALIGNN, CHGNet, and MatGL/M3GNet support. It
does not install MACE or SevenNet. Use `advanced-mlip` for MACE/SevenNet, or
`benchmark-advanced` for the common full stack plus advanced MLIP packages.

You can also install the advanced packages from:

```bash
pip install -r requirements-advanced-mlip.txt
```

## Verify Local Readiness

Use:

```bash
python -m sca.cli verify-backends
```

This command checks import availability and configured local model paths without
loading model weights, downloading models, or running predictions. It is safe for
CI and container startup checks.

## Model Downloads

Benchmark execution should not perform hidden model downloads. If a backend needs
weights, set them up explicitly before running benchmarks.

- ALIGNN: install with `pip install -e .[alignn]`. If the Python API is not
  compatible in your environment, set `SCA_ALIGNN_COMMAND` to a local command.
- CHGNet: install with `pip install -e .[chgnet]`. CHGNet may manage pretrained
  weights through its own public API; run any required CHGNet setup explicitly
  before benchmark execution.
- MatGL/M3GNet: install with `pip install -e .[matgl]`. By default,
  `m3gnet_static` tries MatGL 4.x M3GNet MatPES foundation potentials first,
  preferring `M3GNet-PES-MatPES-PBE-2025.2`, then r2SCAN, then legacy MP
  2021.2.8 names. The ANI subset model is not selected by default because it
  does not cover general inorganic crystal chemistries. Set `SCA_M3GNET_MODEL`
  or `SCA_M3GNET_PRETRAINED` to force an explicit MatGL model name or serialized
  model path.
- MACE local file mode: set `SCA_MACE_MODEL` to a local model file.
- MACE pretrained mode: set `SCA_MACE_PRETRAINED`, for example `small` or
  `medium`, to opt into MACE's pretrained loader.
- SevenNet local file mode: set `SCA_SEVENNET_MODEL` to a local model file.
- SevenNet pretrained mode: set `SCA_SEVENNET_PRETRAINED`, for example
  `7net-0`, to opt into SevenNet's pretrained loader.

Pretrained modes may cause the upstream backend package to download or cache
weights according to that package's behavior. SCA only enters pretrained mode
when the corresponding `SCA_*_PRETRAINED` variable is set.

## Full Benchmark Pattern

```bash
python -m sca.cli verify-backends

python -m sca.cli benchmark manifest examples/cif_manifest.csv \
  --evaluators pre_dft_validity,structure_match,alignn,chgnet_static,m3gnet_static,spp,mlip_ensemble \
  --spp-artifact examples/spp.v1.json \
  --out reports/full_benchmark.csv \
  --jsonl reports/full_benchmark.jsonl
```

All surrogate and MLIP results are pre-DFT screening metrics. They are not DFT
energies and do not prove thermodynamic stability.
