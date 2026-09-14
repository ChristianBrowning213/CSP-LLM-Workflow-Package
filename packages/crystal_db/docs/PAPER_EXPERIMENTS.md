# Paper Experiments (Phase 6)

This document defines the evaluation setup for Phase 6 multi-index retrieval.

## Datasets

- `data/gold/`: small synthetic fixtures for regression and fast evaluation.
- Local corpus: your working SQLite DB (synthetic or real), respecting policy.

## Metrics

- Top-k hit rate: fraction of queries where the target appears in top-k.
- MRR: mean reciprocal rank of the correct target.
- Chemsys hit rate: top-1 neighbor shares the same chemical system.
- Motif overlap (weak label): CrystalCard motif overlap ratio.
- Latency: average retrieval time (ms) for each index and hybrid.
- Storage: DB file size and embedding table sizes.

## Recommended Plots/Tables

- Retrieval comparison table: text vs struct vs seq vs hybrid (top-k, MRR, latency).
- Bar chart: chemsys hit rate per index.
- Latency histogram for each retrieval surface.

## Reporting

- Save JSON + Markdown in `reports/phase6_eval_<timestamp>/`.
- Include configuration details (models, versions, thresholds).
