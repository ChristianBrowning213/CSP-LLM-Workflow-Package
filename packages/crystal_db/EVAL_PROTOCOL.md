# Phase 4 Evaluation Protocol

This protocol defines how Crystal-DB Phase 4 evaluates CSP candidates with RAG assist and reports results.

## Rediscovery Definition

A candidate is labeled **rediscovered** when its novelty distance is less than or equal to the configured threshold. The best-match structure_id is reported with provenance to make the rediscovery claim auditable. A candidate is labeled **novel** when the best-match distance is above the threshold.

## Threshold Rationale

Novelty thresholds are not arbitrary. Use the `calibrate-novelty` command to compute distance distributions for:
- self vs self (sanity, should be 0)
- near-duplicates (same chemical system)
- random pairs

The recommended default threshold is the **p95** of the near-duplicate distribution. This captures most same-chemsys variations while keeping random pairs above the threshold. When near-duplicate samples are missing, the calibration report will fall back to random distribution statistics and explicitly mark the limitation.

## Recommended Reporting Language

Use consistent phrasing in supervisor-facing reports:
- "Novelty: novel" when best distance > threshold
- "Novelty: rediscovered" when best distance <= threshold, followed by:
  - best match structure_id
  - distance
  - provenance (source, source_id, retrieved_at)

Always distinguish between:
- **Proposed candidates** (from CSP runs)
- **Retrieved comparators** (known structures from the DB)

Do not include restricted CIF content in reports or bundles. If a comparator has `allow_export = false`, mark it as redacted in the report output.
