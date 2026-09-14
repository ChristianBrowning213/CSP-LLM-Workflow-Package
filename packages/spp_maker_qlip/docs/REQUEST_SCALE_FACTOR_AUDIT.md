# Request scale-factor audit

The frozen Li2FeO3 v4 workflow used `lambda=0.0026530452898991244`. That number was computed as `1 / median(structure score)` after scoring the 30-CIF request corpus with the shifted histogram request POT, `score_method=neighbors`, and `r_cut=11 A`. It was then multiplied into every stored request-pair potential. It is therefore a corpus-specific objective calibration, not a physical-unit conversion and not a mapping to the legacy ICSD regulator scale.

The old local and global artifacts differ in histogram meaning, radial grid, smoothing, baseline, and short-range treatment. Consequently, the scalar cannot establish cross-corpus commensurability. In the audited Li2FeO3 objective, the broad prior's weighted RMS exceeded the request RMS by 72.5--1675.7 times, depending on pair.

For `dmytro_gr_v1`, corpus-score lambda scaling is forbidden. Local and global inputs are both represented as `-ln(g+1e-12)` on the same 200-bin grid. Pair-level weights are then explicit metadata: local weight 1; global weak-prior weight in the fixed range 0.05--0.20; global-only weight 1 only when local evidence is absent or invalid. The outer QLIP objective weight, if used, remains a separately reported solver coefficient rather than being compiled into POT files.
