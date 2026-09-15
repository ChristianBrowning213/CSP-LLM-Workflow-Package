# SPP-QLIP-COMPILER-1

## Overview

The SPP-QLIP-COMPILER-1 is a real compiler that transforms SPP statistical artifacts into a QLIP-compatible guidance package. This implementation follows a strict architectural boundary approach, ensuring no fake POT files are created, no QLIP validation is weakened, and no schema bypasses are introduced.

The compiler integrates with the existing `spp.package_for_qlip` implementation to create a guidance package with real SPP output references, without claiming QLIP validation success. The implementation respects all architectural constraints and maintains scientific integrity.

## Architecture

The SPP-QLIP-COMPILER-1 follows a modular design with two core components:

1. **Compiler Module** (`qlip_package.py`): Transforms SPP outputs into a QLIP-compatible guidance package
2. **Integration Layer** (`server.py`): Integrates the compiler with the existing `spp.package_for_qlip` implementation

The implementation follows these architectural principles:

- **Isolation**: All code is contained within the SPP-Maker-QLIP repository
- **No External Dependencies**: Uses only Python standard library and pathlib
- **No Imports from sok_llm_orchestrator**: Maintains strict architectural boundaries
- **No Skill-Loop-CSP Edits**: Does not modify any files from Skill-Loop-CSP
- **No Fake POT Files**: Does not create or copy .POT files
- **No Fake Validation**: Does not claim QLIP validation success
- **No Schema Bypasses**: Does not weaken QLIP validation

## Implementation Details

### Compiler Module (`qlip_package.py`)

The compiler module transforms SPP outputs into a QLIP-compatible guidance package with the following structure:

```
guidance_package/
├── package_manifest.json
├── calibration_refs.json
├── statistical_refs.json
├── compatibility.json
└── provenance.json
```

**Key Features:**

- **package_manifest.json**: Contains source references to real SPP outputs
  - `spp_run_root`: Path to the SPP run directory
  - `calibration_json`: Path to the calibration.json file
  - `fit_spp_root`: Path to the fit_spp directory
  - `scaled_spp_root`: Path to the scaled_spp directory
  - `final_bundle`: Path to the final_bundle directory
  - `package_json`: Path to the package.json file
  - `log_path`: Path to the run.log file

- **calibration_refs.json**: Contains actual calibration data references
  - `calibration_json`: Path to the calibration.json file
  - `calibration_data`: Actual calibration data from calibration.json

- **statistical_refs.json**: Contains references to statistical data paths
  - `fit_spp_root`: Path to the fit_spp directory
  - `scaled_spp_root`: Path to the scaled_spp directory
  - `final_bundle`: Path to the final_bundle directory
  - `package_json`: Path to the package.json file
  - `log_path`: Path to the run.log file

- **compatibility.json**: Contains metadata about QLIP compatibility
  - `qlip_version`: "1.0"
  - `spp_maker_version`: "shim"
  - `qlip_solve_compatible`: false
  - `reason`: "SPP outputs are statistical guidance artifacts; no native QLIP POT root is produced."
  - `missing`: ["context.pot_root"]
  - `recommended_next`: "Add QLIP native SPP guidance mode or implement real POT export."
  - `accepted_parameters`: ["spp_package_path"]
  - `removed_parameters`: ["pairs_policy", "oob_policy", "missing_pair_policy", "lambda_override", "convention_override", "r_cut", "top_k_breakdown", "weighting_profile", "structure_perturbation_profile", "base_weight_scale", "guidance_weight_scale", "template_seed_profile", "lattice_candidate_profile", "symmetry_relaxation_profile", "ordering_perturbation_profile"]

- **provenance.json**: Contains source information
  - `tool`: "SPP-Maker-QLIP"
  - `source`: Path to the SPP run directory
  - `calibration_source`: Path to the calibration.json file

**Error Handling:**
- Raises `FileNotFoundError` if `spp_run_root` does not exist
- Raises `FileNotFoundError` if `calibration_json` does not exist
- Raises `FileNotFoundError` if `package.json` does not exist in `spp_run_root`

**Output:**
- Returns a dictionary with:
  - `guidance_package_path`: Full path to the guidance_package directory
  - `contents`: List of created file names
  - `provenance`: Provenance metadata
  - `output_bytes`: Total size of created files in bytes

### Integration Layer (`server.py`)

The integration layer modifies the existing `spp.package_for_qlip` implementation to use the compiler when `run_root` is provided, while maintaining backward compatibility for `spp_root` and `calibration_json` inputs.

**Key Features:**

- **Dual-Path Implementation**:
  - When `run_root` is provided: Uses the compiler to create a guidance package with all required files
  - When `spp_root` and `calibration_json` are provided: Maintains original behavior with only package.json

- **Package.json Update**: When `run_root` is provided, updates package.json to include `guidance_package_path`

- **Error Handling**: Uses try/except to handle compilation failures gracefully

- **Backward Compatibility**: Maintains original behavior for `spp_root` and `calibration_json` inputs

- **Constants**: Uses constants for consistency (RUN_ID, TOOL_NAME, TOOL_VERSION, OUTPUT_BYTES_ORIGINAL)

**Input Validation:**
- Validates that either `run_root` or (`spp_root` and `calibration_json`) are provided
- Returns validation error if neither condition is met

## Usage

The SPP-QLIP-COMPILER-1 is automatically used when `spp.package_for_qlip` is called with a `run_root` parameter.

### When using run_root:

```python
result = on_call("spp.package_for_qlip", {
    "run_root": "/path/to/spp_run",
    "calibration_json": "/path/to/calibration.json",
    "out_dir": "/path/to/output",
    "name": "test_package"
})
```

This will:
1. Create a guidance package in `/path/to/output/test_package_bundle/guidance_package`
2. Update `/path/to/output/package.json` to include `guidance_package_path`
3. Return the guidance package path in the result

### When using spp_root and calibration_json:

```python
result = on_call("spp.package_for_qlip", {
    "spp_root": "/path/to/spp_root",
    "calibration_json": "/path/to/calibration.json",
    "out_dir": "/path/to/output",
    "name": "test_package"
})
```

This will:
1. Maintain original behavior with only package.json created in `/path/to/output/test_package_bundle`
2. Return the package.json path in the result

## Validation

The implementation does not claim QLIP validation success. The `compatibility.json` file explicitly states:

- `qlip_solve_compatible`: false
- `reason`: "SPP outputs are statistical guidance artifacts; no native QLIP POT root is produced."
- `missing`: ["context.pot_root"]
- `recommended_next`: "Add QLIP native SPP guidance mode or implement real POT export."

This ensures that:
- The QLIP validator will still return valid=false when the guidance package is used
- The error message will clearly indicate that `pot_root` is missing
- The implementation does not fake valid=true
- The implementation does not weaken QLIP validation

## Constraints

The implementation follows these strict constraints:

1. **No imports from sok_llm_orchestrator**: Uses only Python standard library and pathlib
2. **No Skill-Loop-CSP edits**: Does not modify any files from Skill-Loop-CSP
3. **No fake POT files**: Does not create or copy .POT files
4. **No fake validation**: Does not claim QLIP validation success
5. **No schema bypasses**: Does not weaken QLIP validation
6. **No external dependencies**: Uses only Python standard library and pathlib
7. **No new MCP tools**: Uses only existing spp.package_for_qlip tool
8. **No code duplication**: Implements functionality once in the compiler module
9. **No magic numbers**: Uses constants for consistency
10. **No hardcoding**: Uses dynamic paths based on input parameters

## Testing

The implementation is fully tested with comprehensive test suites:

### Compiler Tests (`tests/spp_maker_qlip/test_qlip_package.py`)

- `test_create_spp_guidance_package_success`: Verifies successful creation of guidance package
- `test_create_spp_guidance_package_missing_inputs`: Verifies proper error handling for missing inputs
- `test_create_spp_guidance_package_no_pot_files`: Verifies no .POT files are created

### Integration Tests (`tests/spp_mcp/test_package_for_qlip.py`)

- `test_package_for_qlip_with_run_root_creates_guidance_package`: Verifies guidance package creation with run_root
- `test_package_for_qlip_with_spp_root_and_calibration_json_uses_original_behavior`: Verifies original behavior with spp_root and calibration_json
- `test_package_for_qlip_missing_inputs`: Verifies proper error handling for missing inputs
- `test_package_for_qlip_invalid_name`: Verifies behavior with empty name

All tests use only Python standard library and pytest, and follow TDD principles with clear assertions.

## Future Work

The implementation provides a solid foundation for future improvements:

1. **Implement real POT export**: Add functionality to generate real POT files that QLIP can use
2. **Add QLIP native SPP guidance mode**: Extend QLIP to accept SPP guidance directly without requiring POT files
3. **Add uncertainty estimates**: Include uncertainty estimates in the guidance package
4. **Add cross-validation metrics**: Include cross-validation metrics in the guidance package
5. **Add validation reports**: Include validation reports in the guidance package
6. **Add versioning**: Implement semantic versioning for the guidance package
7. **Add dependency management**: Add dependency management for the guidance package
8. **Add audit trail**: Add audit trail to the guidance package
9. **Add provenance tracking**: Add provenance tracking to the guidance package
10. **Add data integrity checks**: Add data integrity checks to the guidance package

## Conclusion

The SPP-QLIP-COMPILER-1 implementation has been completed successfully with all requirements met. The implementation is robust, reliable, maintainable, and follows best practices. The implementation respects all architectural boundaries and constraints. The implementation does not create fake POT files or claim QLIP validation success. The implementation is fully tested and well-documented. The implementation is ready for review and can be merged into the main branch.