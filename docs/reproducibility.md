# Reproducibility

Reproducibility guidance, validated configurations, and provenance requirements
are documented as each research subsystem is migrated and regression-tested.

Validation results record the external backend name, its reported installed
version, the exact SCA revision against which the adapter was validated, and
the adapter schema version. The validated SCA contract is commit
`e5b291312151f34949a5e6ef0f43bebfeb752bc9`; upgrades require renewed direct
SCA/adapter parity checks.

For deterministic comparisons, callers should provide `run_id` because SCA
generates a UUID when it is omitted. Validation does not rewrite CIFs or emit
reports. ALIGNN must remain disabled unless its separate model/runtime is part
of the declared experiment. CHGNet is outside the supported validation path.

Scientific corpora, fitted potentials, benchmark products, model weights, and
experiment outputs remain external or runtime-generated assets.

The workflow writes the structured request/configuration, normalized retrieval
records and source IDs, evidence paths, required pairs, request/regulator POT
hashes, exact QLIP request/result/status/objective, generated CIF hash, and
validation provenance beneath one caller-owned run root. Deterministic run IDs
hash scientific request/configuration but exclude the output location.

The offline regression fixes the SrTiO3 design space and six POT files, disables
request fitting, uses unit regulator/outer weights, and verifies the QLIP
objective and independent periodic score. Retrieval metadata is synthetic;
QLIP, POT loading/scoring, and SCA validation remain real.
