# Material Capability Audit

## 1. Executive summary

Scanned Crystal-DB database: `C:\Users\brown\Documents\GitHub\Crystal-DB\data\phase6_mp_10k.db`.
Scanned SPP runs directory: `C:\Users\brown\Documents\GitHub\SPP-Maker-QLIP\QLIP_Outputs\SPP\runs`.

- Unique concrete formulas in Crystal-DB: 9955
- Likely end-to-end complete formulas: 6043
- Blocked by missing POT-root coverage: 3912

A formula is marked `likely_complete` only when Crystal-DB has at least one entry and at least one published, compatibility-passing SPP root contains every unordered self/cross pair required by the formula element set.

## 2. Likely end-to-end supported materials

| formula | elements | count | best_pot_root | missing_pairs | notes |
|---|---|---:|---|---|---|
| CoAs2 | As, Co | 1 | 20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| CaTiO3 | Ca, O, Ti | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Br | Br | 2 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Ac | Ac | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Ag | Ag | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Al | Al | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| As | As | 1 | 20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Au | Au | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| B | B | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Ba | Ba | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Be | Be | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Bi | Bi | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| C | C | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Ca | Ca | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Cd | Cd | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Ce | Ce | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Cl | Cl | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Co | Co | 1 | 20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Cr | Cr | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Cs | Cs | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Cu | Cu | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Dy | Dy | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Er | Er | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| Eu | Eu | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |
| F | F | 1 | 20260217_163120_ABO3_all_dmytro_89e2b237 |  | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked.; Best POT root is broad; pair coverage is complete but not composition-specific. |

## 3. Blocked materials and why

| formula | elements | count | best_pot_root | missing_pairs | notes |
|---|---|---:|---|---|---|
| Ar | Ar | 1 |  | Ar-Ar | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| BrCl | Br, Cl | 2 |  | Br-Cl | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| CeF3 | Ce, F | 2 |  | Ce-F | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Ac2S3 | Ac, S | 1 |  | Ac-S | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Ac3In | Ac, In | 1 |  | Ac-In | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Ac3Tl | Ac, Tl | 1 |  | Ac-Tl | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcAg | Ac, Ag | 1 |  | Ac-Ag | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcAg3 | Ac, Ag | 1 |  | Ac-Ag | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcAu3 | Ac, Au | 1 |  | Ac-Au | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcBr3 | Ac, Br | 1 |  | Ac-Br | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcCl3 | Ac, Cl | 1 |  | Ac-Cl | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcF3 | Ac, F | 1 |  | Ac-F | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcGe3 | Ac, Ge | 1 |  | Ac-Ge | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcH2 | Ac, H | 1 |  | Ac-H | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcH3 | Ac, H | 1 |  | Ac-H | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcHg3 | Ac, Hg | 1 |  | Ac-Hg | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcI3 | Ac, I | 1 |  | Ac-I | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcIn3 | Ac, In | 1 |  | Ac-In | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AcN | Ac, N | 1 |  | Ac-N | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| AgPt | Ag, Pt | 1 |  | Ag-Pt | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Al11Re4 | Al, Re | 1 |  | Al-Re | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Al12Re | Al, Re | 1 |  | Al-Re | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Al12Tc | Al, Tc | 1 |  | Al-Tc | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Al13Os4 | Al, Os | 1 |  | Al-Os | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |
| Al13Ru4 | Al, Ru | 1 |  | Al-Ru | No export-allowed entries found for this formula; csp_pack may retrieve but CIF export can be policy-blocked. |

## 4. Recommended smoke-test suite

1. `CoAs2`: Generate a CoAs2 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Crystal-DB entries and complete published POT-pair coverage are available.
2. `CaTiO3`: Generate a CaTiO3 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Crystal-DB entries and complete published POT-pair coverage are available.
3. `Ag2SeO3`: Generate a Ag2SeO3 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Additional complete concrete formula with Crystal-DB entries and complete POT-pair coverage.
4. `Ag3AsF12`: Generate a Ag3AsF12 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Additional complete concrete formula with Crystal-DB entries and complete POT-pair coverage.
5. `AgSO4`: Generate a AgSO4 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Additional complete concrete formula with Crystal-DB entries and complete POT-pair coverage.
6. `Al11TlO17`: Generate a Al11TlO17 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Additional complete concrete formula with Crystal-DB entries and complete POT-pair coverage.
7. `ZnS`: Generate a ZnS candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: No exact reduced-formula Crystal-DB entries were found in the selected database; do not hand off to QLIP.
8. `LiCoO2`: Generate a LiCoO2 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: No exact reduced-formula Crystal-DB entries were found in the selected database; do not hand off to QLIP.
9. `BrCl`: Generate a BrCl candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Crystal-DB has entries, but published POT-pair coverage is incomplete.
10. `CeF3`: Generate a CeF3 candidate using retrieved Crystal-DB analogues, SPP POT guidance, QLIP optimisation, and novelty checking.
   Reason: Crystal-DB has entries, but published POT-pair coverage is incomplete.
11. `ABO3`: Ask for a generic ABO3 perovskite prototype without concrete A/B elements; expected behavior is to require a concrete composition before QLIP.
   Reason: Ask for a generic ABO3 perovskite prototype without concrete A/B elements; expected behavior is to require a concrete composition before QLIP.
12. `UnobtainiumO2`: Ask for UnobtainiumO2; expected behavior is blocked_no_crystaldb_entries and no POT-root handoff.
   Reason: Ask for UnobtainiumO2; expected behavior is blocked_no_crystaldb_entries and no POT-root handoff.

## 5. POT-root coverage summary

| run_id | name | pairs | compat | elements_sample |
|---|---|---:|---|---|
| 20260217_163120_ABO3_all_dmytro_89e2b237 | ABO3_all_dmytro | 2249 | 2249 passed / 0 failed | Ac, Ag, Al, As, Au, B, Ba, Be, Bi, Br, C, Ca, ... |
| 20260217_163513_ABO3_all_scaled_c7713143 | ABO3_all_dmytro | 2249 | 2249 passed / 0 failed | Ac, Ag, Al, As, Au, B, Ba, Be, Bi, Br, C, Ca, ... |
| 20260217_171159_ABO3_all_scaled_neighbors_nobandpass_b1c2f8ec | ABO3_all_dmytro | 2249 | 2249 passed / 0 failed | Ac, Ag, Al, As, Au, B, Ba, Be, Bi, Br, C, Ca, ... |
| 20260218_133619_ABO3_dmytro_fit_neighbors_calib_scaled_0ac34dfc | ABO3_dmytro_fit_neighbors_calib | 2249 | 2249 passed / 0 failed | Ac, Ag, Al, As, Au, B, Ba, Be, Bi, Br, C, Ca, ... |
| 20260514_090416_CoAs2_safflorite_dmytro_fit_neighbors_calib_scaled_285e1305 | CoAs2_safflorite_dmytro_fit_neighbors_calib | 3 | 3 passed / 0 failed | As, Co |

## 6. Crystal-DB coverage summary

- Database structures represented in formula groups: 10000
- Export-allowed entries represented in formula groups: 0
- Stored-CIF entries represented in formula groups: 10000

Top formulas by Crystal-DB count:

| formula | elements | count | status |
|---|---|---:|---|
| Ag2SeO3 | Ag, O, Se | 2 | likely_complete |
| Ag3AsF12 | Ag, As, F | 2 | likely_complete |
| AgRhF6 | Ag, F, Rh | 2 | blocked_missing_pot_root |
| AgSO4 | Ag, O, S | 2 | likely_complete |
| Al11TlO17 | Al, O, Tl | 2 | likely_complete |
| AlV2O4 | Al, O, V | 2 | likely_complete |
| Ba2Ce3Si3O12F | Ba, Ce, F, O, Si | 2 | blocked_missing_pot_root |
| Ba3Cr2O8 | Ba, Cr, O | 2 | likely_complete |
| Ba3Sn2O7 | Ba, O, Sn | 2 | likely_complete |
| Ba3Tm4O9 | Ba, O, Tm | 2 | likely_complete |
| Ba5Ga6 | Ba, Ga | 2 | likely_complete |
| Ba5Ga6H2 | Ba, Ga, H | 2 | blocked_missing_pot_root |
| BaBiF7 | Ba, Bi, F | 2 | likely_complete |
| BaFe2As2 | As, Ba, Fe | 2 | likely_complete |
| BaNb2O6 | Ba, Nb, O | 2 | likely_complete |
| BeH12N4Cl2 | Be, Cl, H, N | 2 | blocked_missing_pot_root |
| Bi3PO7 | Bi, O, P | 2 | likely_complete |
| Br | Br | 2 | likely_complete |
| BrCl | Br, Cl | 2 | blocked_missing_pot_root |
| Ca16Sb11 | Ca, Sb | 2 | likely_complete |

## 7. Next data-generation targets

- Generate/publish narrow POT roots for high-priority blocked binaries and ternaries found in Crystal-DB.
- Generate concrete roots for requested smoke-test systems that are currently unsupported, especially `ZnS` and `LiCoO2` if they remain product test cases.
- Keep generic prototypes such as `ABO3` out of QLIP handoff until concrete A/B/O elements are selected.
- Add a CI smoke matrix that uses only formulas marked `likely_complete` in this artifact.
