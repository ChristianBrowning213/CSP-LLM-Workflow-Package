# SPP pair-level local/global blend policy

For each required species pair, validate the local and global `dmytro_gr_v1` POTs as finite, strictly increasing 200-bin artifacts. If local is valid, it is always primary with weight 1. If a common-contract global RDF prior is also valid, its weight is

`0.05 + 0.15 * (1 - confidence)`,

where

`confidence = sqrt(min(n_structures/20,1) * min(log1p(n_observations)/log1p(20000),1))`.

Thus the global term is bounded to 5--20% and becomes weaker as local evidence increases. The thresholds are fixed evidence-scale constants, not fitted to benchmark outcomes. If local is absent or invalid, a valid global artifact is used alone with weight 1 and the mode is explicitly labelled `GLOBAL_ONLY_LOCAL_ABSENT_OR_INVALID`. If both artifacts are invalid, generation fails. No silent neutral pair is permitted.

The blend is compiled per pair into a complete POT root. Every root manifest records the contract, source validity, confidence, weights, and mode. No corpus lambda or outer objective factor is embedded in the files.
