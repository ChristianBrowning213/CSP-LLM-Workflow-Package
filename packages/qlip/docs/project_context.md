# QLIP project context

## Purpose
QLIP is a small MILP-based lattice allocation tool for crystal motif placement and proximity-constrained structure generation.

## Code layout
- src/qlip/: runtime code and CLI entrypoint.
- tools/: generators and one-off scripts for producing motif artifacts and data prep.
- src/qlip/experimental/: quarantined or unfinished modules (not part of the stable API).

## CLI prerequisites
- A MILP solver (HiGHS or GLPK recommended; Gurobi optional).
- SPP POT files for all required element pairs (see --spp-pot-dir / QLIP_SPP_POT_DIR).

## CLI usage
- Help: PYTHONPATH=src; py -3.11 -m qlip --help
- Example: PYTHONPATH=src; py -3.11 -m qlip --chem SrTiO3 --grid 2

## Motifs
Motif runs require artifacts (motifs.json, instances.json). Use --motif-dir to point at a directory with those files.
