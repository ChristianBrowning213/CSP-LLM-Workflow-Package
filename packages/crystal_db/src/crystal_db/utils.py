import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple


def now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_hash(payload: Dict) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def elements_from_csv(elements_csv: Optional[str]) -> List[str]:
    if not elements_csv:
        return []
    trimmed = elements_csv.strip(",")
    if not trimmed:
        return []
    return trimmed.split(",")


def parse_formula(formula: Optional[str]) -> Dict[str, int]:
    if not formula:
        return {}
    counts: Dict[str, int] = {}
    i = 0
    length = len(formula)
    while i < length:
        ch = formula[i]
        if not ch.isalpha() or not ch.isupper():
            i += 1
            continue
        element = ch
        i += 1
        if i < length and formula[i].islower():
            element += formula[i]
            i += 1
        num_start = i
        while i < length and formula[i].isdigit():
            i += 1
        num_str = formula[num_start:i]
        count = int(num_str) if num_str else 1
        counts[element] = counts.get(element, 0) + count
    return counts


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and ((value[0] == value[-1]) and value[0] in ("'", '"')):
        return value[1:-1]
    return value


def parse_cif_text(cif_text: str) -> Dict[str, Optional[float]]:
    formula = None
    space_group = None
    cell_a = None
    cell_b = None
    cell_c = None
    alpha = None
    beta = None
    gamma = None
    volume = None

    for raw_line in cif_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("_chemical_formula_sum"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                formula = _strip_quotes(parts[1].strip())
        elif line.startswith("_symmetry_space_group_name_H-M"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                space_group = _strip_quotes(parts[1].strip())
        elif line.startswith("_cell_length_a"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                cell_a = float(parts[1])
        elif line.startswith("_cell_length_b"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                cell_b = float(parts[1])
        elif line.startswith("_cell_length_c"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                cell_c = float(parts[1])
        elif line.startswith("_cell_angle_alpha"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                alpha = float(parts[1])
        elif line.startswith("_cell_angle_beta"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                beta = float(parts[1])
        elif line.startswith("_cell_angle_gamma"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                gamma = float(parts[1])
        elif line.startswith("_cell_volume"):
            parts = line.split(None, 1)
            if len(parts) > 1:
                volume = float(parts[1])

    if volume is None and cell_a and cell_b and cell_c and alpha and beta and gamma:
        ra = math.radians(alpha)
        rb = math.radians(beta)
        rg = math.radians(gamma)
        volume = (
            cell_a
            * cell_b
            * cell_c
            * math.sqrt(
                1
                + 2 * math.cos(ra) * math.cos(rb) * math.cos(rg)
                - math.cos(ra) ** 2
                - math.cos(rb) ** 2
                - math.cos(rg) ** 2
            )
        )

    return {
        "formula": formula,
        "space_group": space_group,
        "volume": volume,
    }
