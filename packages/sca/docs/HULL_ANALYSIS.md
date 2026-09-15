# Compatible DFT Convex Hull

`sca.dft.analysis.hull` is deliberately separate from the existing surrogate `predicted_hull`
evaluator. A DFT hull bundle stores chemical system, material ID, formula, total/per-atom energy,
formation energy when available, compatibility fingerprint, source, and provenance.

The phase diagram combines the candidate with compatible competing-phase entries through
pymatgen. It returns raw `energy_above_hull_eV_atom`, on-hull state, decomposition products,
decomposition energy, reference count, and status.

- Missing elemental terminals or insufficient competitors: `NOT_COMPUTABLE`.
- Incompatible energy settings: `NOT_COMPUTABLE_INCOMPATIBLE_REFERENCES`.
- No surrogate fallback occurs under either status.

Optional `ON_HULL`, `NEAR_HULL`, and `ABOVE_HULL` labels use thresholds stored in every result.
They are descriptive configuration, not universal physical laws. Raw E_hull always remains
available. E_hull is thermodynamic context at the chosen theory/settings; it is not proof of
kinetic accessibility, finite-temperature persistence, or experimental synthesizability.

