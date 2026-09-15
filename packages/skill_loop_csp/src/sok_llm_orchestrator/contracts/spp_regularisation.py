from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


CONFIG_C_SPP_GUIDANCE_WEIGHT = 10.0
CONFIG_C_REGULARISATION_WEIGHT = 2.0
CONFIG_C_MISSING_PAIR_POLICY = "soft_repulsive"


class RegulatorSPPConfigurationError(RuntimeError):
    """Raised when the configured broad regulator artifact cannot be resolved."""


def resolve_regulator_spp_dir(*, require_exists: bool = True) -> Path:
    """Resolve the regulator from configuration without an absolute host path."""
    attempted: list[Path] = []
    configured = os.getenv("SKILL_LOOP_REGULATOR_SPP_ROOT")
    if configured:
        attempted.append(Path(configured).expanduser())
    default_config = Path(__file__).resolve().parents[3] / "config" / "workflow" / "default.json"
    portable_locator = Path("Downloads") / "SPP" / "SPP" / "SPP" / "SPP"
    if default_config.is_file():
        payload = json.loads(default_config.read_text(encoding="utf-8"))
        raw_locator = payload.get("regulator", {}).get("portable_legacy_locator")
        if isinstance(raw_locator, str) and raw_locator.strip():
            portable_locator = Path(raw_locator)
    attempted.append(Path.home() / portable_locator)
    for candidate in attempted:
        resolved = candidate.resolve()
        if resolved.is_dir() and any(resolved.rglob("*.POT")):
            return resolved
    if not require_exists:
        return attempted[0].resolve()
    rendered = ", ".join(str(path.resolve()) for path in attempted)
    raise RegulatorSPPConfigurationError(
        "Broad regulator SPP corpus not found. Set SKILL_LOOP_REGULATOR_SPP_ROOT "
        f"to a directory containing POT files. Attempted: {rendered}"
    )


CONFIG_C_REGULARISATION_SPP_DIR = str(resolve_regulator_spp_dir(require_exists=False))

_FORMULA_ELEMENT_RE = re.compile(r"([A-Z][a-z]?)(?:\d*)")


def _as_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def formula_pairs(formula: str | None) -> list[str]:
    elements: list[str] = []
    for match in _FORMULA_ELEMENT_RE.finditer(str(formula or "")):
        element = match.group(1)
        if element not in elements:
            elements.append(element)
    pairs: list[str] = []
    for left in elements:
        for right in elements:
            pair = "-".join(sorted((left, right)))
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def _canonical_pair_key(pair: str) -> str:
    if "-" not in pair:
        return _canonical_element_symbol(pair)
    left, right = pair.split("-", 1)
    return "-".join(sorted((_canonical_element_symbol(left), _canonical_element_symbol(right)), key=str.lower))


def _canonical_element_symbol(symbol: str) -> str:
    stripped = str(symbol).strip()
    if not stripped:
        return stripped
    return stripped[:1].upper() + stripped[1:].lower()


def regularised_partial_spp_config(overrides: Mapping[str, Any]) -> dict[str, Any] | None:
    regularisation_dir = overrides.get("spp_regularisation_dir") or overrides.get("spp_regularization_dir")
    regularisation_weight = _as_optional_float(
        overrides.get("spp_regularisation_weight", overrides.get("spp_regularization_weight"))
    )
    if not isinstance(regularisation_dir, str) or not regularisation_dir.strip():
        return None
    if not isinstance(regularisation_weight, float) or regularisation_weight <= 0:
        return None
    allow_partial = overrides.get("allow_partial_spp_guidance", True)
    if isinstance(allow_partial, str):
        allow_partial = allow_partial.strip().lower() not in {"0", "false", "no", "off"}
    if allow_partial is False:
        return None
    return {
        "pot_root": str(overrides.get("spp_pot_root") or overrides.get("pot_root") or "").strip(),
        "regularisation_spp_dir": regularisation_dir.strip(),
        "regularisation_weight": float(regularisation_weight),
        "missing_pair_policy": str(overrides.get("spp_missing_pair_policy") or "neutral"),
        "spp_guidance_weight": float(
            _as_optional_float(
                overrides.get("runtime_spp_guidance_weight", overrides.get("spp_guidance_weight"))
            )
            or 1.0
        ),
        "spp_cutoff": float(_as_optional_float(overrides.get("spp_cutoff")) or 11.0),
    }


def find_spp_pot_root(allowed_roots: list[Path] | tuple[Path, ...], formula: str | None) -> str | None:
    required_pairs = {_canonical_pair_key(pair) for pair in formula_pairs(formula)}
    if not required_pairs:
        return None
    candidates: list[Path] = []
    for root in allowed_roots:
        resolved = Path(root).resolve()
        if not resolved.exists():
            continue
        if resolved.is_dir():
            candidates.append(resolved)
        if resolved.name == "spp_root":
            candidates.append(resolved)
        candidates.extend(path for path in resolved.rglob("spp_root") if path.is_dir())
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        available_pairs = {_canonical_pair_key(path.stem) for path in candidate.rglob("*.POT")}
        if required_pairs <= available_pairs:
            return str(candidate)
    return None


def apply_regularised_partial_spp_guidance(
    request: dict[str, Any],
    *,
    formula: str | None,
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Attach the broad regulator without discarding request-specific SPP guidance.

    A request built from a fitted SPP package already contains the canonical
    ``objective.energy_spp`` invocation and its POT root in ``context``.  The
    regulator is an additive QLIP input, so this function augments that
    invocation.  It constructs partial/fallback metadata only when no local
    request POT root is present.
    """
    cfg = regularised_partial_spp_config(overrides)
    if cfg is None:
        return request
    patched = json.loads(json.dumps(request))
    context = patched.get("context")
    if not isinstance(context, dict):
        context = {}
    pot_root = str(cfg.get("pot_root") or context.get("pot_root") or "").strip()
    problem = patched.setdefault("problem", {})
    if isinstance(problem, dict):
        problem["objective"] = {"type": "spp_energy"}
    if pot_root:
        context["pot_root"] = pot_root
        patched["context"] = context
    guidance = patched.get("guidance")
    if not isinstance(guidance, list):
        guidance = []
    existing = next(
        (
            item
            for item in guidance
            if isinstance(item, dict) and item.get("id") == "objective.energy_spp"
        ),
        None,
    )
    guidance_item = json.loads(json.dumps(existing)) if existing is not None else {
        "id": "objective.energy_spp",
        "params": {},
    }
    guidance_item["weight"] = float(cfg["spp_guidance_weight"])
    params = guidance_item.get("params")
    if not isinstance(params, dict):
        params = {}
    params["regularisation_spp_dir"] = str(cfg["regularisation_spp_dir"])
    params["regularisation_weight"] = float(cfg["regularisation_weight"])
    if not pot_root:
        params.update(
            {
                "pot_root": "",
                "mode": "partial",
                "supported_pairs": [],
                "missing_pairs": formula_pairs(formula),
                "missing_pair_policy": str(cfg["missing_pair_policy"]),
                "missing_pair_penalty": 0.0,
                "strict_pair_coverage": False,
                "spp_cutoff": float(cfg["spp_cutoff"]),
            }
        )
    guidance_item["params"] = params
    guidance = [item for item in guidance if not (isinstance(item, dict) and item.get("id") == "objective.energy_spp")]
    guidance.append(guidance_item)
    patched["guidance"] = guidance
    return patched
