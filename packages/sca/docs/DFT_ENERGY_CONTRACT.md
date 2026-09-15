# DFT Energy Contract

Physical energy arithmetic is allowed only for compatible calculations. A
`DFTCompatibilityFingerprint` records:

- engine family and energy convention;
- XC functional;
- pseudopotential family;
- Hubbard U mapping/convention;
- dispersion treatment;
- correction scheme.

Comparison returns `COMPATIBLE`, `INCOMPATIBLE`, or `UNKNOWN`, with field-level reasons. Formation
energy and hull analysis refuse `INCOMPATIBLE` and `UNKNOWN` sets rather than mixing values.

Formation energy is calculated as

```text
Delta E_f = E_compound - sum_i n_i mu_i
```

Each `mu_i` record includes the element, reference phase, energy per atom, compatibility
fingerprint, source, and provenance. Both total and per-atom formation energy are reported.

ALIGNN's predicted formation energy is a separate surrogate metric. It must never populate this
physical DFT contract, and DFT relaxation alone does not supply formation energy.

