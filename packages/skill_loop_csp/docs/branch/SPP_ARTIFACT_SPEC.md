# SPP Artifact Spec

Schema: `spp.artifact.v1`.

Required fields:

- corpus hash,
- weighting policy,
- bin policy,
- smoothing parameters,
- calibration summary,
- neighbor policy,
- cutoff/downweight policy,
- shrink-protection flags.

Artifacts are hash-addressable and tied to corpus manifests to preserve reproducibility.
