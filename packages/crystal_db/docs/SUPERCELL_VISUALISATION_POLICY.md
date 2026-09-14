# Supercell visualisation policy

`DISPLAY_SUPERCELL_POLICY_V1` applies only to paper visualization. It never replaces, edits, relaxes, or feeds back into a retrieved or generated raw CIF.

For layered structures, candidate repeats are `(1,1,1)`, `(1,1,2)`, `(1,1,3)`, `(2,2,1)`, and `(2,2,2)`. For spinels they are `(1,1,1)`, `(2,2,1)`, and `(2,2,2)`. Candidates producing 36--96 displayed atoms are eligible; the repeat producing an atom count closest to 48 is selected, with listed order as the deterministic tie-break. If none lies in the interval, the closest-to-48 candidate is used.

The repeat is written to a new derived CIF and rendered in VESTA with fixed rotations `(x,y,z)=(18,-28,8)` degrees. The manifest records raw hashes before and after, the derived hash, repeat, displayed atom count, renderer, and render hash. Raw CIF hash equality is a hard acceptance condition.
