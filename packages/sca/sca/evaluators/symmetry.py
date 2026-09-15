"""Space-group extraction and consistency checks."""

from __future__ import annotations

import re
from collections.abc import Sequence

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from sca.schemas import SymmetryResult


DECLARED_SYMBOL_FIELDS = (
    "_symmetry_space_group_name_H-M",
    "_space_group_name_H-M_alt",
)
DECLARED_NUMBER_FIELDS = ("_space_group_IT_number", "_symmetry_Int_Tables_number")


def evaluate_symmetry(
    structure: Structure,
    cif_text: str | None,
    target_space_group: str | None,
    symprec_values: Sequence[float] = (0.01, 0.1, 0.2),
) -> SymmetryResult:
    declared_symbol, declared_number = _extract_declared_space_group(cif_text)
    result = SymmetryResult(
        declared_space_group=declared_symbol,
        declared_space_group_number=declared_number,
        target_space_group=target_space_group,
    )

    last_error: Exception | None = None
    for symprec in symprec_values:
        try:
            analyzer = SpacegroupAnalyzer(structure, symprec=symprec, angle_tolerance=5)
            detected_symbol = analyzer.get_space_group_symbol()
            detected_number = analyzer.get_space_group_number()
            consistent = _space_group_consistent(
                detected_symbol,
                detected_number,
                target_space_group,
                declared_symbol,
                declared_number,
            )
            return result.model_copy(
                update={
                    "detected_space_group": detected_symbol,
                    "detected_space_group_number": detected_number,
                    "space_group_consistent": consistent,
                    "symprec_used": float(symprec),
                    "angle_tolerance_used": 5.0,
                }
            )
        except Exception as exc:
            last_error = exc

    return result.model_copy(
        update={
            "symmetry_error": None if last_error is None else f"{type(last_error).__name__}: {last_error}",
        }
    )


def _extract_declared_space_group(cif_text: str | None) -> tuple[str | None, int | None]:
    if not cif_text:
        return None, None

    symbol = None
    number = None
    for field in DECLARED_SYMBOL_FIELDS:
        match = re.search(rf"^{re.escape(field)}\s+(.+)$", cif_text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            symbol = _strip_cif_value(match.group(1))
            break
    for field in DECLARED_NUMBER_FIELDS:
        match = re.search(rf"^{re.escape(field)}\s+([0-9]+)", cif_text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            number = int(match.group(1))
            break
    return symbol, number


def _space_group_consistent(
    detected_symbol: str | None,
    detected_number: int | None,
    target: str | None,
    declared_symbol: str | None,
    declared_number: int | None,
) -> bool | None:
    if target:
        target_number = _parse_int(target)
        if target_number is not None and detected_number is not None:
            return target_number == detected_number
        return _normalize_space_group(target) == _normalize_space_group(detected_symbol)
    if declared_number is not None and detected_number is not None:
        return declared_number == detected_number
    if declared_symbol:
        return _normalize_space_group(declared_symbol) == _normalize_space_group(detected_symbol)
    return None


def _strip_cif_value(value: str) -> str:
    return value.strip().strip("'\"")


def _normalize_space_group(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.replace("−", "-").replace("_", "").replace(" ", "").replace("'", "").replace('"', "")
    return normalized.lower()


def _parse_int(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None
