# Material Test Candidate Audit

## 1. Executive summary

- Scanned DB: `C:\Users\brown\Documents\GitHub\Crystal-DB\data\phase6_mp_10k.db`
- Scanned SPP roots: `C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP\QLIP_Outputs\SPP\runs`
- Candidates scored: 9955
- Full-success candidates: 652
- SPP-block candidates: 3912

This v2 audit is deliberately stricter than pair coverage. It scores exact reduced-formula presence, representative IDs, robocrys/text embedding/fingerprint evidence, export policy, formula sanity, element risk, POT-root specificity, and demo usefulness.

## 2. Recommended final smoke suite

1. Expected complete: `CoAs2` - Generate a CoAs2 safflorite-like arsenide candidate using retrieved structural analogues, SPP-derived POT guidance, QLIP optimisation, and novelty checking.
2. Expected complete: `CaTiO3` - Generate a CaTiO3 perovskite-like oxide candidate using retrieved structural analogues, SPP-derived POT guidance, QLIP optimisation, and novelty checking.
3. Expected complete: `BaTiO3` - Generate a BaTiO3 perovskite-like oxide candidate using retrieved structural analogues, SPP-derived POT guidance, QLIP optimisation, and novelty checking.
1. Expected partial: `ZnS` - No exact reduced-formula Crystal-DB entry in the active DB.
2. Expected partial: `LiCoO2` - No exact reduced-formula Crystal-DB entry in the active DB.
3. Expected partial: `TiO2` - No exact reduced-formula Crystal-DB entry in the active DB.
4. Expected partial: `ZnO` - No exact reduced-formula Crystal-DB entry in the active DB.
5. Expected partial: `BrCl` - Crystal-DB has entries, but published POT roots are missing required pairs.
6. Expected partial: `CeF3` - Crystal-DB has entries, but published POT roots are missing required pairs.
7. Expected partial: `Al2O3` - Candidate has static Crystal-DB/POT-like evidence, but no configured-run evidence yet proves that SPP emits a solve-compatible QLIP request_ref.
8. Expected partial: `Fe2O3` - Candidate has static Crystal-DB/POT-like evidence, but no configured-run evidence yet proves that SPP emits a solve-compatible QLIP request_ref.
1. Edge case: `ABO3` - Prototype request should be rejected or clarified before SPP/QLIP because POT pairs require concrete elements.
2. Edge case: `UnobtainiumO2` - Non-real/non-indexed composition should be blocked before retrieval/POT handoff.

## 3. Expected-complete tests

| formula | confidence | demo quality | selected root family | representative IDs | reason |
|---|---:|---:|---|---|---|
| CoAs2 | 90 | 100 | exact | mp-049e6343 | High-confidence concrete material with Crystal-DB evidence and complete compatible POT coverage. Uses an exact/narrow published POT root. |
| CaTiO3 | 88 | 100 | ABO3_family | mp-45ce5f93 | High-confidence concrete material with Crystal-DB evidence and complete compatible POT coverage. Uses the published ABO3-family root with complete required-pair coverage. |
| BaTiO3 | 88 | 100 | ABO3_family | mp-d8426545 | High-confidence concrete material with Crystal-DB evidence and complete compatible POT coverage. Uses the published ABO3-family root with complete required-pair coverage. |

## 4. Expected-partial tests

| formula | confidence | demo quality | selected root family | representative IDs | reason |
|---|---:|---:|---|---|---|
| ZnS | 0 | 0 | broad |  | No exact reduced-formula Crystal-DB entry in the active DB. |
| LiCoO2 | 0 | 0 | ABO3_family |  | No exact reduced-formula Crystal-DB entry in the active DB. |
| TiO2 | 0 | 0 | broad |  | No exact reduced-formula Crystal-DB entry in the active DB. |
| ZnO | 0 | 0 | broad |  | No exact reduced-formula Crystal-DB entry in the active DB. |
| BrCl | 67 | 1 | unknown | mp-575ad763, mp-e6bc99a4 | Crystal-DB has entries, but published POT roots are missing required pairs. |
| CeF3 | 67 | 1 | unknown | mp-39fb0507, mp-f3ff022e | Crystal-DB has entries, but published POT roots are missing required pairs. |
| Al2O3 | 84 | 72 | broad | mp-989da596 | Candidate has static Crystal-DB/POT-like evidence, but no configured-run evidence yet proves that SPP emits a solve-compatible QLIP request_ref. |
| Fe2O3 | 84 | 72 | broad | mp-738d7edb | Candidate has static Crystal-DB/POT-like evidence, but no configured-run evidence yet proves that SPP emits a solve-compatible QLIP request_ref. |

## 5. Edge cases

- `ABO3`: Generate an ABO3 perovskite-like crystal without specifying concrete A and B elements. Reason: Prototype request should be rejected or clarified before SPP/QLIP because POT pairs require concrete elements.
- `UnobtainiumO2`: Generate an UnobtainiumO2 oxide candidate using Crystal-DB retrieval and QLIP. Reason: Non-real/non-indexed composition should be blocked before retrieval/POT handoff.

## 6. Excluded but tempting candidates

| formula | reasons | note |
|---|---|---|
| Ba5Ga6 | broad_pot_root_not_demo_specific | confidence=89, demo_quality=15 |
| Ac2O3 | contains_radioactive_or_unwanted_elements, broad_pot_root_not_demo_specific | confidence=49, demo_quality=0 |
| AcCu3 | contains_radioactive_or_unwanted_elements, broad_pot_root_not_demo_specific | confidence=49, demo_quality=0 |
| LiCoO2 | no_exact_crystaldb_reduced_formula, no_representative_structure_id | confidence=0, demo_quality=0 |
| TiO2 | no_exact_crystaldb_reduced_formula, no_representative_structure_id | confidence=0, demo_quality=0 |
| ZnO | no_exact_crystaldb_reduced_formula, no_representative_structure_id | confidence=0, demo_quality=0 |
| ZnS | no_exact_crystaldb_reduced_formula, no_representative_structure_id | confidence=0, demo_quality=0 |
| CeO2 | broad_pot_root_not_demo_specific | confidence=84, demo_quality=71 |
| CoO | broad_pot_root_not_demo_specific | confidence=84, demo_quality=71 |
| Al2S3O12 | large_reduced_formula | confidence=76, demo_quality=64 |
| BaS4O13 | large_reduced_formula | confidence=76, demo_quality=64 |
| Cu2S3O12 | large_reduced_formula | confidence=76, demo_quality=64 |
| Fe2S3O12 | large_reduced_formula | confidence=76, demo_quality=64 |
| Ga2S3O12 | large_reduced_formula | confidence=76, demo_quality=64 |
| Ba2As6O11 | large_reduced_formula | confidence=76, demo_quality=63 |
| Fe4As5O13 | large_reduced_formula | confidence=76, demo_quality=63 |
| Fe7As6O24 | large_reduced_formula | confidence=76, demo_quality=63 |
| Al2Se3O12 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba11In6O3 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba2Nb15O32 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba2Ti13O22 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba2Ti6O13 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba3Nb16O23 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba3Ti20O40 | large_reduced_formula | confidence=76, demo_quality=58 |
| Ba4Fe4O11 | large_reduced_formula | confidence=76, demo_quality=58 |

## 7. Why ZnS/LiCoO2 should remain negative/blocked for now

`ZnS` and `LiCoO2` should not be used as expected-complete demos against `data\phase6_mp_10k.db`: the audit found no exact reduced-formula Crystal-DB entries for either material. Because the workflow is Crystal-DB retrieval -> SPP handoff -> QLIP, they are blocked before a truthful QLIP handoff. They are useful negative controls until matching Crystal-DB entries and compatible published POT roots are available.

## 8. Exact PowerShell smoke-suite command for Skill-Loop-CSP

```powershell
$suite = Get-Content C:\Users\brown\Documents\GitHub\Crystal-DB\artifacts\skill_loop_smoke_suite.json | ConvertFrom-Json
Set-Location C:\Users\brown\Documents\GitHub\Skill-Loop-CSP
foreach ($run in $suite.runs) {
  python -m sok_llm_orchestrator.cli --config my_live_config.yaml --workspace test_workdir\material_capability_smoke_v1 run --mode live --with-spp true --query $run.goal
}
```

Ready-to-run suite file: `C:\Users\brown\Documents\GitHub\Crystal-DB\artifacts\skill_loop_smoke_suite.json`
