from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from spp_maker.io_cif import load_cifs_from_dir
from spp_maker.pot_compat import check_pot_root


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _error(code: str, message: str, path: str | Path | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if path is not None:
        payload["path"] = str(path)
    return payload


def _canonical_pair(a: str, b: str) -> str:
    parts = sorted([a.strip().title(), b.strip().title()], key=lambda value: value.lower())
    return f"{parts[0]}-{parts[1]}"


@dataclass(frozen=True)
class CandidateRoot:
    run_path: str
    pot_root: str
    available_pairs: list[str]
    missing_pairs: list[str]
    compat_passed: bool | None
    selected: bool
    reason: str
    material_match: bool = False


@dataclass(frozen=True)
class RootSelectionResult:
    selected_pot_root: str | None
    selected_run_path: str | None
    qlip_solve_compatible: bool
    required_pairs: list[str]
    available_pairs_by_candidate_root: dict[str, list[str]]
    missing_pairs: list[str]
    candidate_roots_checked: list[CandidateRoot]
    errors: list[dict[str, Any]]


def parse_formula_elements(formula: str) -> list[str]:
    """Return unique element symbols in formula order."""
    if not isinstance(formula, str) or not formula.strip():
        return []
    elements = []
    for match in re.finditer(r"([A-Z][a-z]?)(?:[0-9]+(?:\.[0-9]+)?)?", formula):
        element = match.group(1)
        if element not in elements:
            elements.append(element)
    return elements


def _parse_formula_counts(formula: str | None) -> dict[str, float]:
    if not isinstance(formula, str) or not formula.strip():
        return {}
    counts: dict[str, float] = {}
    for match in re.finditer(r"([A-Z][a-z]?)([0-9]+(?:\.[0-9]+)?)?", formula):
        element = match.group(1)
        raw_count = match.group(2)
        count = float(raw_count) if raw_count else 1.0
        counts[element] = counts.get(element, 0.0) + count
    return counts


def _formula_is_abo3_family(formula: str | None) -> bool:
    counts = _parse_formula_counts(formula)
    if len(counts) != 3 or "O" not in counts:
        return False
    return abs(counts["O"] - 3.0) < 1e-9


def derive_required_pairs(elements: list[str]) -> list[str]:
    """Return unordered self/cross element pairs required by a set of elements."""
    cleaned = []
    for element in elements:
        if isinstance(element, str) and element.strip() and element.strip().title() not in cleaned:
            cleaned.append(element.strip().title())
    pairs = {
        _canonical_pair(cleaned[i], cleaned[j])
        for i in range(len(cleaned))
        for j in range(i, len(cleaned))
    }
    return sorted(pairs, key=str.lower)


def required_pairs_from_formula(formula: str | None) -> list[str]:
    """Return unordered self/cross element pairs required by a formula."""
    return derive_required_pairs(parse_formula_elements(formula or ""))


def _normalize_required_pairs(required_pairs: list[str] | tuple[str, ...] | None) -> list[str]:
    out = set()
    for item in required_pairs or []:
        if not isinstance(item, str) or "-" not in item:
            continue
        left, right = item.split("-", 1)
        left = left.strip()
        right = right.strip()
        if left and right:
            out.add(_canonical_pair(left, right))
    return sorted(out, key=str.lower)


def _pair_key(pair: str) -> str:
    if "-" not in pair:
        return pair.strip().lower()
    left, right = pair.split("-", 1)
    return "-".join(sorted([left.strip().lower(), right.strip().lower()]))


def _pair_from_path(path: Path) -> str | None:
    if "-" in path.stem:
        left, right = path.stem.split("-", 1)
        return _canonical_pair(left, right)
    if "-" in path.parent.name:
        left, right = path.parent.name.split("-", 1)
        return _canonical_pair(left, right)
    return None


def read_pot_root_pairs(pot_root: Path) -> set[str]:
    """Read canonical pair coverage from a published POT root."""
    pairs: set[str] = set()
    spp_root = Path(pot_root)
    if not spp_root.is_dir():
        return pairs
    for pot_file in spp_root.rglob("*.POT"):
        pair = _pair_from_path(pot_file)
        if pair:
            pairs.add(pair)
    return pairs


def _available_pairs_from_pot_root(spp_root: Path) -> set[str]:
    return {_pair_key(pair) for pair in read_pot_root_pairs(spp_root)}


def _pot_path_for_pair(pot_root: Path, pair: str) -> str | None:
    if "-" not in pair:
        return None
    left, right = pair.split("-", 1)
    candidates = [
        pot_root / pair / f"{pair}.POT",
        pot_root / f"{right}-{left}" / f"{right}-{left}.POT",
        pot_root / f"{pair}.POT",
        pot_root / f"{right}-{left}.POT",
        pot_root / f"{pair.upper()}.POT",
        pot_root / f"{right.upper()}-{left.upper()}" / f"{right.upper()}-{left.upper()}.POT",
        pot_root / f"{right.upper()}-{left.upper()}.POT",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _manifest_pairs(manifest_path: Path, spp_root: Path) -> set[str]:
    pairs: set[str] = set()
    if not manifest_path.is_file():
        return pairs
    manifest = _load_json(manifest_path)
    manifest_pairs = manifest.get("pairs")
    if not isinstance(manifest_pairs, list):
        return pairs
    for item in manifest_pairs:
        if not isinstance(item, dict):
            continue
        left = item.get("A")
        right = item.get("B")
        if isinstance(left, str) and isinstance(right, str):
            pairs.add(_canonical_pair(left, right))
            continue
        rel_path = item.get("path")
        if isinstance(rel_path, str):
            pair = _pair_from_path(spp_root / rel_path)
            if pair:
                pairs.add(pair)
    return pairs


def _geometric_pairs_from_corpus(cif_dir: Path, *, cutoff: float, supercell: int = 1) -> tuple[list[str], list[str]]:
    try:
        loaded = load_cifs_from_dir(cif_dir)
    except Exception:
        return [], []
    span = range(-int(supercell), int(supercell) + 1)
    detected: set[str] = set()
    formulas: list[str] = []
    for item in loaded:
        formulas.append(str(item.atoms.get_chemical_formula()))
        symbols = tuple(str(symbol) for symbol in item.atoms.get_chemical_symbols())
        positions = np.asarray(item.atoms.get_positions(), dtype=np.float64)
        cell = np.asarray(item.atoms.cell.array, dtype=np.float64)
        for i, symbol_i in enumerate(symbols):
            pos_i = positions[i]
            for j, symbol_j in enumerate(symbols):
                pos_j = positions[j]
                for tx in span:
                    for ty in span:
                        for tz in span:
                            if i == j and tx == 0 and ty == 0 and tz == 0:
                                continue
                            image_pos = pos_j + tx * cell[0] + ty * cell[1] + tz * cell[2]
                            distance = float(np.linalg.norm(image_pos - pos_i))
                            if distance <= cutoff + 1e-12:
                                detected.add(_canonical_pair(symbol_i, symbol_j))
    return sorted(detected, key=str.lower), formulas


def _coverage_error(
    *,
    run_path: Path,
    required_pairs: list[str],
    available_pairs: set[str],
    nearest_candidate_roots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    missing_pairs = [pair for pair in required_pairs if _pair_key(pair) not in available_pairs]
    message = "Published SPP POT root does not cover required pair coverage: " + ", ".join(missing_pairs)
    error = _error("pot_pair_coverage_missing", message, run_path / "spp_root")
    error["required_pairs"] = required_pairs
    error["missing_pairs"] = missing_pairs
    error["available_pair_count"] = len(available_pairs)
    if nearest_candidate_roots is not None:
        error["nearest_candidate_roots"] = nearest_candidate_roots
    return error


def _parse_compat_report(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")

    def _number(label: str) -> int | None:
        match = re.search(rf"^{re.escape(label)}:\s*(\d+)\s*$", text, flags=re.MULTILINE)
        return int(match.group(1)) if match else None

    checked = _number("POT files checked")
    passed = _number("Passed")
    failed = _number("Failed")
    parsed: dict[str, Any] = {}
    if checked is not None:
        parsed["checked"] = checked
    if passed is not None:
        parsed["passed"] = passed
    if failed is not None:
        parsed["failed"] = failed
    parsed["strict"] = True
    return parsed


def _compat_from_publish_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = _load_json(path)
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    compat = checks.get("compat") if isinstance(checks.get("compat"), dict) else {}
    out: dict[str, Any] = {}
    for key in ("checked", "passed", "failed"):
        value = compat.get(key)
        if isinstance(value, int):
            out[key] = value
    if isinstance(compat.get("strict"), bool):
        out["strict"] = compat["strict"]
    return out


def _compat_passed(run_path: Path) -> bool | None:
    compat = _compat_from_publish_meta(run_path / "publish_meta.json")
    compat_from_report = _parse_compat_report(run_path / "compat_report.txt")
    merged = {**compat_from_report, **compat}
    failed = merged.get("failed")
    if isinstance(failed, int):
        return failed == 0
    checked = merged.get("checked")
    passed = merged.get("passed")
    if isinstance(checked, int) or isinstance(passed, int):
        return failed in (None, 0)
    return None


def _manifest_paths_missing(manifest_path: Path, spp_root: Path) -> int:
    if not manifest_path.is_file():
        return 0
    manifest = _load_json(manifest_path)
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list):
        return 0
    missing = 0
    for item in pairs:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        if not (spp_root / item["path"]).is_file():
            missing += 1
    return missing


def _resolve_published_run(
    qlip_outputs_root: str | Path | None,
    published_spp_rel: str | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    if qlip_outputs_root is None:
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root was not provided.")]
    qlip_outputs = Path(qlip_outputs_root).resolve()
    if not qlip_outputs.is_dir():
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root does not exist.", qlip_outputs)]

    if published_spp_rel:
        run_path = qlip_outputs / published_spp_rel
        if run_path.is_dir():
            return run_path, []
        return None, [_error("pot_root_missing", "Published SPP run path does not exist.", run_path)]

    latest_path = qlip_outputs / "SPP" / "latest.txt"
    if not latest_path.is_file():
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs/SPP/latest.txt does not exist.", latest_path)]
    latest_rel = latest_path.read_text(encoding="utf-8").strip()
    if not latest_rel:
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs/SPP/latest.txt is empty.", latest_path)]
    run_path = qlip_outputs / latest_rel
    if not run_path.is_dir():
        return None, [_error("pot_root_missing", "Latest SPP run path does not exist.", run_path)]
    return run_path, []


def _candidate_run_paths(qlip_outputs_root: Path, published_spp_rel: str | None) -> list[Path]:
    paths: list[Path] = []
    if published_spp_rel:
        paths.append(qlip_outputs_root / published_spp_rel)
    latest_path = qlip_outputs_root / "SPP" / "latest.txt"
    if latest_path.is_file():
        latest_rel = latest_path.read_text(encoding="utf-8").strip()
        if latest_rel:
            paths.append(qlip_outputs_root / latest_rel)
    runs_root = qlip_outputs_root / "SPP" / "runs"
    if runs_root.is_dir():
        paths.extend(sorted((item for item in runs_root.iterdir() if item.is_dir()), reverse=True))

    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _material_metadata_matches(run_path: Path, material_system: str) -> bool:
    needle = material_system.strip().lower()
    if not needle:
        return False
    chunks = [run_path.name.lower()]
    for filename in ("manifest.json", "publish_meta.json"):
        path = run_path / filename
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="ignore").lower())
    return needle in "\n".join(chunks)


def _is_abo3_root(run_path: Path) -> bool:
    text = run_path.name.lower()
    for filename in ("manifest.json", "publish_meta.json"):
        path = run_path / filename
        if path.is_file():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore").lower()
    return "abo3" in text


def inspect_published_pot_roots(registry_root: Path, required_pairs: list[str]) -> list[CandidateRoot]:
    """Inspect all published SPP runs for pair coverage."""
    qlip_outputs = Path(registry_root).resolve()
    normalized_required = _normalize_required_pairs(required_pairs)
    candidates: list[CandidateRoot] = []
    for run_path in _candidate_run_paths(qlip_outputs, None):
        spp_root = run_path / "spp_root"
        available = read_pot_root_pairs(spp_root) | _manifest_pairs(run_path / "manifest.json", spp_root)
        available_pairs = sorted(available, key=str.lower)
        available_keys = {_pair_key(pair) for pair in available_pairs}
        missing_pairs = [pair for pair in normalized_required if _pair_key(pair) not in available_keys]
        compat = _compat_passed(run_path)
        if not run_path.is_dir():
            reason = "run_missing"
        elif not spp_root.is_dir():
            reason = "pot_root_missing"
        elif compat is False:
            reason = "compat_failed"
        elif missing_pairs:
            reason = "missing_required_pairs"
        else:
            reason = "compatible"
        candidates.append(
            CandidateRoot(
                run_path=str(run_path),
                pot_root=str(spp_root),
                available_pairs=available_pairs,
                missing_pairs=missing_pairs,
                compat_passed=compat,
                selected=False,
                reason=reason,
            )
        )
    return candidates


def select_compatible_pot_root(material_system: str, registry_root: Path) -> RootSelectionResult:
    """Select a published POT root by material-system pair coverage."""
    required_pairs = required_pairs_from_formula(material_system)
    qlip_outputs = Path(registry_root).resolve()
    candidates = inspect_published_pot_roots(qlip_outputs, required_pairs)
    checked: list[CandidateRoot] = []
    compatible: list[tuple[int, CandidateRoot]] = []
    for index, candidate in enumerate(candidates):
        run_path = Path(candidate.run_path)
        material_match = _material_metadata_matches(run_path, material_system)
        material_family_ok = not _is_abo3_root(run_path) or material_match or _formula_is_abo3_family(material_system)
        is_compatible = (
            bool(required_pairs)
            and candidate.reason == "compatible"
            and candidate.compat_passed is not False
            and material_family_ok
        )
        compatible_reason = "selected" if is_compatible else candidate.reason
        if candidate.reason == "compatible" and not material_family_ok:
            compatible_reason = "material_family_mismatch"
        enriched = CandidateRoot(
            run_path=candidate.run_path,
            pot_root=candidate.pot_root,
            available_pairs=candidate.available_pairs,
            missing_pairs=candidate.missing_pairs,
            compat_passed=candidate.compat_passed,
            selected=False,
            reason=compatible_reason,
            material_match=material_match,
        )
        checked.append(enriched)
        if is_compatible:
            compatible.append((index, enriched))

    selected_index: int | None = None
    selected: CandidateRoot | None = None
    if compatible:
        # Candidate order is explicit published run, latest pointer, then newest run names.
        # Prefer metadata that names the requested material, otherwise the newest compatible run.
        selected_index, selected = sorted(
            compatible,
            key=lambda item: (item[1].material_match, -item[0]),
            reverse=True,
        )[0]
        checked[selected_index] = CandidateRoot(
            run_path=selected.run_path,
            pot_root=selected.pot_root,
            available_pairs=selected.available_pairs,
            missing_pairs=[],
            compat_passed=selected.compat_passed,
            selected=True,
            reason="selected_material_match" if selected.material_match else "selected_pair_coverage",
            material_match=selected.material_match,
        )

    available_by_root = {item.pot_root: item.available_pairs for item in checked}
    missing_pairs = []
    if selected is None:
        missing_sets = [item.missing_pairs for item in checked if item.missing_pairs]
        missing_pairs = (
            sorted(set(required_pairs), key=str.lower)
            if not missing_sets
            else sorted(set(missing_sets[0]), key=str.lower)
        )
        if checked:
            missing_pairs = sorted(
                set(min((item.missing_pairs for item in checked), key=lambda pairs: len(pairs))),
                key=str.lower,
            )
        message_target = material_system.strip() or "requested material system"
        error = _error(
            "pot_pair_coverage_missing",
            f"No published SPP POT root covers required pairs for {message_target}.",
        )
        error["details"] = {
            "required_pairs": required_pairs,
            "missing_pairs": missing_pairs,
            "available_pairs_by_candidate_root": available_by_root,
        }
        errors = [error]
    else:
        errors = []

    return RootSelectionResult(
        selected_pot_root=checked[selected_index].pot_root if selected_index is not None else None,
        selected_run_path=checked[selected_index].run_path if selected_index is not None else None,
        qlip_solve_compatible=selected_index is not None,
        required_pairs=required_pairs,
        available_pairs_by_candidate_root=available_by_root,
        missing_pairs=[] if selected_index is not None else missing_pairs,
        candidate_roots_checked=checked,
        errors=errors,
    )


def _select_published_run_for_pairs(
    *,
    qlip_outputs_root: str | Path | None,
    published_spp_rel: str | None,
    required_pairs: list[str],
    material_system: str | None = None,
) -> tuple[Path | None, list[dict[str, Any]], list[dict[str, Any]]]:
    if not required_pairs:
        run_path, errors = _resolve_published_run(qlip_outputs_root, published_spp_rel)
        return run_path, errors, []

    if qlip_outputs_root is None:
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root was not provided.")], []
    qlip_outputs = Path(qlip_outputs_root).resolve()
    if not qlip_outputs.is_dir():
        return None, [_error("qlip_outputs_missing", "QLIP_Outputs root does not exist.", qlip_outputs)], []

    candidates: list[dict[str, Any]] = []
    compatible_indexes: list[int] = []
    for index, run_path in enumerate(_candidate_run_paths(qlip_outputs, published_spp_rel)):
        spp_root = run_path / "spp_root"
        available_pair_names = read_pot_root_pairs(spp_root) | _manifest_pairs(run_path / "manifest.json", spp_root)
        available_pairs = {_pair_key(pair) for pair in available_pair_names}
        missing_pairs = [pair for pair in required_pairs if _pair_key(pair) not in available_pairs]
        compat_passed = _compat_passed(run_path)
        reason = "compatible"
        if not run_path.is_dir():
            reason = "run_missing"
        elif not spp_root.is_dir():
            reason = "pot_root_missing"
        elif compat_passed is False:
            reason = "compat_failed"
        elif missing_pairs:
            reason = "missing_required_pairs"
        elif _is_abo3_root(run_path) and not _material_metadata_matches(run_path, material_system or "") and not _formula_is_abo3_family(material_system):
            reason = "material_family_mismatch"
        candidate = {
            "run_path": str(run_path),
            "pot_root": str(spp_root),
            "available_pairs": sorted(available_pair_names, key=str.lower),
            "available_pair_count": len(available_pair_names),
            "covered_pairs": [pair for pair in required_pairs if _pair_key(pair) in available_pairs],
            "missing_pairs": missing_pairs,
            "compat_passed": compat_passed,
            "selected": False,
            "material_match": _material_metadata_matches(run_path, material_system or ""),
            "reason": reason,
        }
        candidates.append(candidate)
        if run_path.is_dir() and not missing_pairs and compat_passed is not False and reason == "compatible":
            compatible_indexes.append(index)

    if compatible_indexes:
        selected_index = sorted(
            compatible_indexes,
            key=lambda item: (bool(candidates[item].get("material_match")), -item),
            reverse=True,
        )[0]
        candidates[selected_index]["selected"] = True
        candidates[selected_index]["reason"] = (
            "selected_material_match"
            if candidates[selected_index].get("material_match")
            else "selected_pair_coverage"
        )
        return Path(str(candidates[selected_index]["run_path"])), [], candidates

    if not candidates:
        return None, [_error("qlip_outputs_missing", "No published SPP runs were found.", qlip_outputs / "SPP" / "runs")], []
    viable_for_nearest = [item for item in candidates if item.get("compat_passed") is not False] or candidates
    best = sorted(viable_for_nearest, key=lambda item: (len(item["missing_pairs"]), -int(item["available_pair_count"])))[0]
    error = _error("pot_pair_coverage_missing", "No published SPP POT root covers all required pairs.", best["pot_root"])
    error["required_pairs"] = required_pairs
    error["missing_pairs"] = best["missing_pairs"]
    error["available_pair_count"] = best["available_pair_count"]
    error["available_pairs_by_candidate_root"] = {
        str(item["pot_root"]): item.get("available_pairs", []) for item in candidates
    }
    error["nearest_candidate_roots"] = candidates[:5]
    return Path(str(best["run_path"])), [error], candidates


def discover_published_spp_pot_root(
    *,
    qlip_outputs_root: str | Path | None,
    published_spp_rel: str | None = None,
    required_pairs: list[str] | tuple[str, ...] | None = None,
    material_system: str | None = None,
) -> dict[str, Any]:
    """Locate and validate a real published QLIP_Outputs SPP POT root."""
    normalized_required_pairs = _normalize_required_pairs(required_pairs)
    if not normalized_required_pairs:
        normalized_required_pairs = required_pairs_from_formula(material_system)
    run_path, selection_errors, candidate_roots = _select_published_run_for_pairs(
        qlip_outputs_root=qlip_outputs_root,
        published_spp_rel=published_spp_rel,
        required_pairs=normalized_required_pairs,
        material_system=material_system,
    )
    if run_path is None:
        return {
            "ok": False,
            "run_path": None,
            "pot_root": None,
            "pot_root_source": "fallback_precompiled",
            "extraction_mode": None,
            "selected_pot_root": None,
            "pot_count": 0,
            "compat": {},
            "artifact_refs": [],
            "required_pairs": normalized_required_pairs,
            "missing_pairs": normalized_required_pairs,
            "sparse_pairs": [],
            "sparse_pair_metadata_available": False,
            "available_pair_count": 0,
            "pair_coverage_complete": False,
            "qlip_solve_compatible": False,
            "available_pairs_by_candidate_root": {},
            "candidate_roots_checked": candidate_roots,
            "nearest_candidate_roots": candidate_roots,
            "errors": selection_errors,
        }

    pot_root = run_path / "spp_root"
    manifest_path = run_path / "manifest.json"
    compat_report_path = run_path / "compat_report.txt"
    publish_meta_path = run_path / "publish_meta.json"
    errors = list(selection_errors)
    if not pot_root.is_dir():
        errors.append(_error("pot_root_missing", "Published SPP run is missing spp_root.", pot_root))
    pot_count = len(list(pot_root.rglob("*.POT"))) if pot_root.is_dir() else 0
    if pot_root.is_dir() and pot_count == 0:
        errors.append(_error("pot_root_no_pot_files", "Published SPP root contains no .POT files.", pot_root))
    available_pair_names = read_pot_root_pairs(pot_root) | _manifest_pairs(manifest_path, pot_root)
    manifest_payload = _load_json(manifest_path) if manifest_path.is_file() else {}
    manifest_sparse_pairs = [
        str(pair)
        for pair in manifest_payload.get("sparse_pairs", [])
        if isinstance(pair, str)
    ] if isinstance(manifest_payload.get("sparse_pairs"), list) else []
    sparse_pair_metadata_available = isinstance(manifest_payload.get("sparse_pairs"), list)
    available_pairs = {_pair_key(pair) for pair in available_pair_names}
    missing_pairs = [
        pair for pair in normalized_required_pairs if _pair_key(pair) not in available_pairs
    ]
    if missing_pairs:
        errors.append(
            _coverage_error(
                run_path=run_path,
                required_pairs=normalized_required_pairs,
                available_pairs=available_pairs,
                nearest_candidate_roots=candidate_roots[:5],
            )
        )
    if not manifest_path.is_file():
        errors.append(_error("pot_root_missing", "Published SPP run is missing manifest.json.", manifest_path))

    compat = _compat_from_publish_meta(publish_meta_path)
    compat_from_report = _parse_compat_report(compat_report_path)
    compat = {**compat_from_report, **compat}
    failed = compat.get("failed")
    if isinstance(failed, int) and failed > 0:
        errors.append(_error("pot_compat_failed", f"Published SPP POT compatibility failed for {failed} files.", compat_report_path))

    missing_manifest_paths = _manifest_paths_missing(manifest_path, pot_root)
    if missing_manifest_paths:
        errors.append(_error("pot_root_missing", f"Manifest references {missing_manifest_paths} missing POT files.", manifest_path))

    artifact_refs = [
        {"ref_name": "pot_root", "value": str(pot_root), "kind": "directory"},
        {"ref_name": "spp_manifest_json", "value": str(manifest_path), "kind": "file"},
    ]
    if compat_report_path.is_file():
        artifact_refs.append({"ref_name": "spp_compat_report_txt", "value": str(compat_report_path), "kind": "file"})
    if publish_meta_path.is_file():
        artifact_refs.append({"ref_name": "spp_publish_meta_json", "value": str(publish_meta_path), "kind": "file"})

    return {
        "ok": not errors,
        "run_path": str(run_path),
        "pot_root_source": "fallback_precompiled",
        "extraction_mode": None,
        "pot_root": str(pot_root) if pot_root.is_dir() else None,
        "selected_pot_root": str(pot_root) if pot_root.is_dir() and not errors else None,
        "pot_count": pot_count,
        "compat": compat,
        "artifact_refs": artifact_refs,
        "required_pairs": normalized_required_pairs,
        "missing_pairs": missing_pairs,
        "sparse_pairs": manifest_sparse_pairs,
        "sparse_pair_metadata_available": sparse_pair_metadata_available,
        "available_pairs": sorted(available_pair_names, key=str.lower),
        "available_pair_count": len(available_pair_names),
        "pair_coverage_complete": not missing_pairs and not manifest_sparse_pairs,
        "qlip_solve_compatible": not errors,
        "available_pairs_by_candidate_root": {
            str(item.get("pot_root")): item.get("available_pairs", []) for item in candidate_roots
        },
        "candidate_roots_checked": candidate_roots,
        "nearest_candidate_roots": candidate_roots[:5],
        "errors": errors,
    }


def discover_fresh_spp_pot_root(
    *,
    run_root: str | Path,
    fresh_spp_root: str | Path | None = None,
    required_pairs: list[str] | tuple[str, ...] | None = None,
    material_system: str | None = None,
    formula: str | None = None,
    cif_count: int | None = None,
    fresh_generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Locate and validate the SPP root generated by this pipeline run."""
    root = Path(run_root)
    spp_root = Path(fresh_spp_root) if fresh_spp_root is not None else root / "calibrate" / "scaled_spp_root"
    manifest_path = spp_root / "manifest.json"
    compat_report_path = root / "calibrate" / "compat_report_scaled.txt"
    effective_formula = formula or material_system
    normalized_required_pairs = _normalize_required_pairs(required_pairs)
    if not normalized_required_pairs:
        normalized_required_pairs = required_pairs_from_formula(effective_formula)

    fresh_generation_out = dict(fresh_generation or {})
    fresh_generation_out.update({
        "corpus_ref": None,
        "cif_count": fresh_generation_out.get("cif_count", cif_count),
        "run_root": str(root),
        "spp_root": str(spp_root),
        "compat_checked": fresh_generation_out.get("compat_checked", 0),
        "compat_passed": fresh_generation_out.get("compat_passed", 0),
        "compat_failed": fresh_generation_out.get("compat_failed", 0),
    })
    errors: list[dict[str, Any]] = []
    seen_error_keys: set[tuple[str | None, str | None]] = set()

    def _append_error_once(error: dict[str, Any]) -> None:
        key = (
            str(error.get("code")) if error.get("code") is not None else None,
            str(error.get("message")) if error.get("message") is not None else None,
        )
        if key in seen_error_keys:
            return
        seen_error_keys.add(key)
        errors.append(error)

    for item in fresh_generation_out.get("errors", []):
        if isinstance(item, dict):
            _append_error_once(dict(item))

    if not spp_root.is_dir():
        _append_error_once(_error("fresh_spp_generation_failed", "Fresh run-local SPP root was not generated.", spp_root))
        return {
            "ok": False,
            "run_path": str(root),
            "pot_root_source": "fresh_corpus",
            "extraction_mode": fresh_generation_out.get("extraction_mode"),
            "pot_root": None,
            "selected_pot_root": None,
            "pot_count": 0,
            "compat": {},
            "artifact_refs": [],
            "required_pairs": normalized_required_pairs,
            "missing_pairs": normalized_required_pairs,
            "sparse_pairs": [],
            "sparse_pair_metadata_available": False,
            "available_pairs": [],
            "available_pair_count": 0,
            "pair_coverage_complete": False,
            "qlip_solve_compatible": False,
            "errors": errors,
            "fresh_generation": fresh_generation_out,
        }

    pot_files = sorted(spp_root.rglob("*.POT"), key=lambda item: str(item).lower())
    if not pot_files:
        _append_error_once(_error("fresh_spp_generation_failed", "Could not generate compatible SPP POT root from retrieved corpus.", spp_root))

    available_pair_names = read_pot_root_pairs(spp_root) | _manifest_pairs(manifest_path, spp_root)
    available_pairs = {_pair_key(pair) for pair in available_pair_names}
    missing_pairs = [pair for pair in normalized_required_pairs if _pair_key(pair) not in available_pairs]
    manifest = _load_json(manifest_path) if manifest_path.is_file() else {}
    manifest_missing_pairs = [
        str(pair) for pair in manifest.get("missing_pairs", []) if isinstance(pair, str)
    ] if isinstance(manifest.get("missing_pairs"), list) else []
    manifest_sparse_pairs = [
        str(pair) for pair in manifest.get("sparse_pairs", []) if isinstance(pair, str)
    ] if isinstance(manifest.get("sparse_pairs"), list) else []
    if manifest_missing_pairs:
        missing_pairs = manifest_missing_pairs
    formula_elements = set(parse_formula_elements(effective_formula or ""))
    relevant_available_pair_names = sorted(
        [
            pair
            for pair in available_pair_names
            if not formula_elements or set(pair.split("-", 1)).issubset(formula_elements)
        ],
        key=str.lower,
    )
    relevant_pot_pairs = sorted(
        [
            pair
            for pair in read_pot_root_pairs(spp_root)
            if not formula_elements or set(pair.split("-", 1)).issubset(formula_elements)
        ],
        key=str.lower,
    )
    cif_dir_raw = manifest.get("cif_dir")
    cutoff = manifest.get("r_cut")
    cutoff_value = float(cutoff) if isinstance(cutoff, (int, float)) else None
    corpus_cif_files: list[str] = []
    corpus_detected_formulas: list[str] = []
    geometric_pairs_detected: list[str] = []
    if isinstance(cif_dir_raw, str) and cif_dir_raw.strip():
        cif_dir = Path(cif_dir_raw)
        if cif_dir.is_dir():
            corpus_cif_files = [
                str(path)
                for path in sorted(cif_dir.iterdir(), key=lambda item: item.name.lower())
                if path.is_file() and path.suffix.lower() == ".cif"
            ]
            geometric_pairs_detected, corpus_detected_formulas = _geometric_pairs_from_corpus(
                cif_dir,
                cutoff=cutoff_value or 6.0,
            )
    pair_extraction_diagnostics = {
        "required_pairs": normalized_required_pairs,
        "geometric_pairs_detected": geometric_pairs_detected,
        "spp_selected_pairs": relevant_available_pair_names,
        "pot_pairs": relevant_pot_pairs,
        "missing_pairs": missing_pairs,
        "likely_reason": (
            "same-element periodic image pairs may be geometrically present, but the SPP extraction policy selected only a subset"
            if missing_pairs
            else "fresh SPP generation produced all QLIP-required pairs"
        ),
        "cutoff": cutoff_value,
        "pair_policy": manifest.get("fit_method") if isinstance(manifest.get("fit_method"), str) else None,
        "corpus_cif_files": corpus_cif_files,
        "corpus_detected_formulas": corpus_detected_formulas,
    }
    fresh_generation_out["pair_extraction_diagnostics"] = pair_extraction_diagnostics
    if manifest.get("extraction_mode") == "qlip_required_pairs":
        fresh_generation_out["extraction_mode"] = "qlip_required_pairs"
        fresh_generation_out["pair_stats"] = manifest.get("pair_stats", {})
        fresh_generation_out["corpus_cif_count"] = manifest.get("corpus_cif_count")
        fresh_generation_out["corpus_cif_files"] = manifest.get("corpus_cif_files", [])
        fresh_generation_out["corpus_quality"] = manifest.get("corpus_quality", fresh_generation_out.get("corpus_quality", {}))
    fresh_required_pair_coverage_complete = not missing_pairs and not manifest_sparse_pairs
    required_pair_pot_export_complete = all(
        (spp_root / pair / f"{pair}.POT").is_file()
        for pair in normalized_required_pairs
    )
    pot_quality = fresh_generation_out.get("spp_pot_quality")
    if not isinstance(pot_quality, dict):
        pot_quality = {}
    fresh_generation_out["required_pair_pot_export_complete"] = bool(required_pair_pot_export_complete)
    fresh_generation_out["fresh_required_pair_coverage_complete"] = bool(fresh_required_pair_coverage_complete)
    fresh_generation_out["pot_quality"] = pot_quality
    fresh_generation_out["diagnostic_only"] = bool(pot_quality.get("diagnostic_only")) if pot_quality else False
    if missing_pairs:
        error_code = "required_pair_distances_missing" if manifest.get("extraction_mode") == "qlip_required_pairs" else "fresh_spp_generation_failed"
        error = _error(
            error_code,
            "No periodic distances were found for one or more formula-required pairs."
            if error_code == "required_pair_distances_missing"
            else "Fresh SPP generation did not produce all QLIP-required pairs. Geometric distances may exist, but the SPP extraction policy selected only a subset.",
            spp_root,
        )
        error["required_pairs"] = normalized_required_pairs
        error["missing_pairs"] = missing_pairs
        error["sparse_pairs"] = manifest_sparse_pairs
        error["available_pair_count"] = len(available_pairs)
        error["fresh_generation"] = {"pair_extraction_diagnostics": pair_extraction_diagnostics}
        corpus_quality = fresh_generation_out.get("corpus_quality")
        if isinstance(corpus_quality, dict):
            error["corpus_quality"] = corpus_quality
        _append_error_once(error)

    compat: dict[str, Any] = {}
    try:
        report = check_pot_root(spp_root, strict=True)
        compat = {
            "checked": report.checked,
            "passed": report.passed,
            "failed": report.failed,
            "strict": True,
        }
        fresh_generation_out.update(
            {
                "compat_checked": report.checked,
                "compat_passed": report.passed,
                "compat_failed": report.failed,
            }
        )
        if not report.ok:
            _append_error_once(
                _error(
                    "fresh_spp_generation_failed",
                    f"Fresh SPP POT compatibility failed for {report.failed} files.",
                    compat_report_path if compat_report_path.is_file() else spp_root,
                )
            )
    except Exception as exc:
        _append_error_once(_error("fresh_spp_generation_failed", f"Fresh SPP POT compatibility check failed: {exc}", spp_root))

    if not manifest_path.is_file():
        _append_error_once(_error("fresh_spp_generation_failed", "Fresh SPP run is missing manifest.json.", manifest_path))

    artifact_refs = [{"ref_name": "pot_root", "value": str(spp_root), "kind": "directory"}]
    if manifest_path.is_file():
        artifact_refs.append({"ref_name": "spp_manifest_json", "value": str(manifest_path), "kind": "file"})
    if compat_report_path.is_file():
        artifact_refs.append({"ref_name": "spp_compat_report_txt", "value": str(compat_report_path), "kind": "file"})

    ok = not errors
    return {
        "ok": ok,
        "run_path": str(root),
        "pot_root_source": "fresh_corpus",
        "extraction_mode": fresh_generation_out.get("extraction_mode"),
        "pot_root": str(spp_root),
        "selected_pot_root": str(spp_root) if ok else None,
        "pot_count": len(pot_files),
        "compat": compat,
        "artifact_refs": artifact_refs,
        "required_pairs": normalized_required_pairs,
        "missing_pairs": [] if ok else missing_pairs,
        "sparse_pairs": manifest_sparse_pairs,
        "sparse_pair_metadata_available": isinstance(manifest.get("sparse_pairs"), list),
        "available_pairs": relevant_available_pair_names,
        "available_pair_count": len(relevant_available_pair_names),
        "required_pair_pot_export_complete": bool(required_pair_pot_export_complete),
        "fresh_required_pair_coverage_complete": bool(fresh_required_pair_coverage_complete),
        "pot_quality": pot_quality,
        "pair_coverage_complete": bool(fresh_required_pair_coverage_complete),
        "qlip_solve_compatible": ok,
        "errors": errors,
        "fresh_generation": fresh_generation_out,
    }


def create_spp_guidance_package(
    spp_run_root: str | Path,
    calibration_json: str | Path | None,
    out_dir: str | Path,
    name: str,
    qlip_outputs_root: str | Path | None = None,
    published_spp_rel: str | None = None,
    required_pairs: list[str] | tuple[str, ...] | None = None,
    material_system: str | None = None,
    formula: str | None = None,
    cif_count: int | None = None,
    fresh_spp_root: str | Path | None = None,
    fresh_generation: dict[str, Any] | None = None,
    allow_fallback_precompiled: bool = True,
) -> dict[str, Any]:
    """Create a QLIP guidance handoff package from real SPP run artifacts."""
    run_root = Path(spp_run_root)
    calibration_path = Path(calibration_json) if calibration_json is not None else run_root / "calibrate" / "calibration.json"
    output_root = Path(out_dir)

    if not run_root.exists():
        raise FileNotFoundError(f"SPP run root does not exist: {run_root}")
    if not calibration_path.exists():
        raise FileNotFoundError(f"Calibration file does not exist: {calibration_path}")

    package_json_path = run_root / "package" / "package.json"
    if not package_json_path.exists():
        package_json_path = run_root / "package.json"
    if not package_json_path.exists():
        raise FileNotFoundError(f"package.json not found in SPP run root: {run_root}")

    bundle_name = f"{name}_bundle" if name else "_bundle"
    bundle_root = output_root / bundle_name
    guidance_package_path = bundle_root / "guidance_package"
    guidance_package_path.mkdir(parents=True, exist_ok=True)

    fit_spp_root = run_root / "fit" / "spp_root"
    scaled_spp_root = run_root / "calibrate" / "scaled_spp_root"
    final_bundle = run_root.parents[1] / "Final_QLIP_output" / run_root.name if len(run_root.parents) > 1 else run_root / "final_bundle"
    log_path = run_root / "logs" / "timings.json"

    fresh_handoff = discover_fresh_spp_pot_root(
        run_root=run_root,
        fresh_spp_root=fresh_spp_root,
        required_pairs=required_pairs,
        material_system=formula or material_system,
        formula=formula,
        cif_count=cif_count,
        fresh_generation=fresh_generation,
    )
    fallback_handoff: dict[str, Any] | None = None
    if fresh_handoff.get("ok"):
        pot_handoff = fresh_handoff
        pot_root_source = "fresh_corpus"
        fallback_used = False
        fallback_reason = None
        selected_fallback_root = None
    elif allow_fallback_precompiled:
        fallback_handoff = discover_published_spp_pot_root(
            qlip_outputs_root=qlip_outputs_root,
            published_spp_rel=published_spp_rel,
            required_pairs=fresh_handoff.get("required_pairs")
            if isinstance(fresh_handoff.get("required_pairs"), list)
            else required_pairs,
            material_system=formula or material_system,
        )
        pot_handoff = fallback_handoff
        fallback_used = bool(fallback_handoff.get("ok") and fallback_handoff.get("selected_pot_root"))
        fallback_reason = "fresh_corpus_insufficient"
        selected_fallback_root = fallback_handoff.get("selected_pot_root") if fallback_used else None
        pot_root_source = "fallback_precompiled" if fallback_used else "none"
    else:
        fallback_handoff = {
            "ok": False,
            "selected_pot_root": None,
            "missing_pairs": fresh_handoff.get("missing_pairs", []),
            "sparse_pairs": fresh_handoff.get("sparse_pairs", []),
            "required_pairs": fresh_handoff.get("required_pairs", []),
            "available_pairs": fresh_handoff.get("available_pairs", []),
            "available_pair_count": 0,
            "candidate_roots_checked": [],
            "available_pairs_by_candidate_root": {},
            "errors": [
                _error(
                    "fallback_precompiled_disabled",
                    "Precompiled fallback POT root scan was disabled for this runtime profile.",
                )
            ],
        }
        pot_handoff = fallback_handoff
        fallback_used = False
        fallback_reason = "fallback_precompiled_disabled"
        selected_fallback_root = None
        pot_root_source = "none"

    missing_pairs = pot_handoff.get("missing_pairs") if isinstance(pot_handoff.get("missing_pairs"), list) else []
    sparse_pairs = pot_handoff.get("sparse_pairs") if isinstance(pot_handoff.get("sparse_pairs"), list) else []
    if not fresh_handoff.get("ok") and not fallback_used and not missing_pairs:
        fresh_missing_pairs = fresh_handoff.get("missing_pairs")
        if isinstance(fresh_missing_pairs, list) and fresh_missing_pairs:
            missing_pairs = fresh_missing_pairs

    fallback_errors: list[dict[str, Any]] = []
    if not fresh_handoff.get("ok") and not fallback_used:
        fallback_error = _error(
            "fallback_pot_pair_coverage_missing",
            "No precompiled fallback POT root covers required pairs.",
        )
        fallback_error["required_pairs"] = (
            fresh_handoff.get("required_pairs") if isinstance(fresh_handoff.get("required_pairs"), list) else []
        )
        fallback_error["missing_pairs"] = (
            pot_handoff.get("missing_pairs") if isinstance(pot_handoff.get("missing_pairs"), list) else fallback_error["required_pairs"]
        )
        fallback_errors.append(fallback_error)

    combined_errors = list(fresh_handoff.get("errors", []))
    if not fresh_handoff.get("ok"):
        combined_errors.extend(list(pot_handoff.get("errors", [])))
        combined_errors.extend(fallback_errors)
    compat_evidence = pot_handoff.get("compat") if isinstance(pot_handoff.get("compat"), dict) else {}
    selected_pot_root = (
        pot_handoff.get("selected_pot_root")
        if isinstance(pot_handoff.get("selected_pot_root"), str)
        else None
    )
    pot_root = selected_pot_root if pot_handoff.get("ok") else None
    qlip_solve_compatible = bool(pot_handoff.get("ok") and selected_pot_root)
    required_pairs_out = pot_handoff.get("required_pairs") if isinstance(pot_handoff.get("required_pairs"), list) else []
    if not required_pairs_out and isinstance(fresh_handoff.get("required_pairs"), list):
        required_pairs_out = fresh_handoff.get("required_pairs")
    selected_metadata_handoff = pot_handoff if qlip_solve_compatible or fallback_used else fresh_handoff
    selected_available_pairs = (
        selected_metadata_handoff.get("available_pairs")
        if isinstance(selected_metadata_handoff.get("available_pairs"), list)
        else []
    )
    supported_pairs = [
        pair for pair in selected_available_pairs if _pair_key(pair) in {_pair_key(required) for required in required_pairs_out}
    ] if required_pairs_out else list(selected_available_pairs)
    selected_available_pair_count = len(selected_available_pairs)
    partial_pot_root = fresh_handoff.get("pot_root") if isinstance(fresh_handoff.get("pot_root"), str) and not qlip_solve_compatible else None
    diagnostic_only = bool(
        (fresh_handoff.get("pot_quality") if isinstance(fresh_handoff.get("pot_quality"), dict) else {}).get("diagnostic_only")
    ) or (bool(selected_available_pairs) and not qlip_solve_compatible)
    fallback_required_to_solve = not bool(fresh_handoff.get("ok")) and bool(required_pairs_out)
    partial_guidance_pot_root = partial_pot_root or (pot_root if supported_pairs else None)
    if partial_guidance_pot_root and required_pairs_out and not qlip_solve_compatible:
        supported_pair_pot_paths = {
            pair: _pot_path_for_pair(Path(partial_guidance_pot_root), pair)
            for pair in required_pairs_out
        }
    else:
        supported_pair_pot_paths = {
            pair: _pot_path_for_pair(Path(partial_guidance_pot_root), pair)
            for pair in supported_pairs
        } if partial_guidance_pot_root else {}
    supported_pair_pot_paths = {pair: path for pair, path in supported_pair_pot_paths.items() if path}
    if partial_guidance_pot_root and required_pairs_out and not qlip_solve_compatible:
        supported_pairs = [pair for pair in required_pairs_out if pair in supported_pair_pot_paths]
        selected_available_pairs = list(supported_pairs)
        selected_available_pair_count = len(selected_available_pairs)
        missing_pairs = [
            pair for pair in required_pairs_out
            if _pair_key(pair) not in {_pair_key(supported) for supported in supported_pairs}
        ]
    can_use_as_partial_guidance = bool(supported_pairs and partial_guidance_pot_root and supported_pair_pot_paths)
    candidate_roots_checked = (
        pot_handoff.get("candidate_roots_checked")
        if isinstance(pot_handoff.get("candidate_roots_checked"), list)
        else []
    )
    fresh_package = {
        "pot_root": fresh_handoff.get("pot_root"),
        "required_pairs": fresh_handoff.get("required_pairs") if isinstance(fresh_handoff.get("required_pairs"), list) else [],
        "available_pairs": fresh_handoff.get("available_pairs") if isinstance(fresh_handoff.get("available_pairs"), list) else [],
        "missing_pairs": fresh_handoff.get("missing_pairs") if isinstance(fresh_handoff.get("missing_pairs"), list) else [],
        "required_pair_pot_export_complete": bool(fresh_handoff.get("required_pair_pot_export_complete")),
        "fresh_required_pair_coverage_complete": bool(fresh_handoff.get("fresh_required_pair_coverage_complete")),
        "can_use_as_partial_guidance": can_use_as_partial_guidance,
        "qlip_partial_guidance_compatible": can_use_as_partial_guidance,
        "partial_guidance_pot_root": partial_guidance_pot_root,
        "supported_pair_pot_paths": supported_pair_pot_paths,
        "missing_pair_policy_recommendation": "neutral",
        "strict_pair_coverage": False if can_use_as_partial_guidance else not bool(fresh_handoff.get("missing_pairs")),
        "pot_quality": fresh_handoff.get("pot_quality") if isinstance(fresh_handoff.get("pot_quality"), dict) else {},
    }
    fallback_package = {
        "pot_root": fallback_handoff.get("selected_pot_root") if isinstance(fallback_handoff, dict) else None,
        "available_pairs": fallback_handoff.get("available_pairs") if isinstance(fallback_handoff, dict) and isinstance(fallback_handoff.get("available_pairs"), list) else [],
        "missing_pairs": fallback_handoff.get("missing_pairs") if isinstance(fallback_handoff, dict) and isinstance(fallback_handoff.get("missing_pairs"), list) else [],
        "pair_coverage_complete": bool(fallback_handoff.get("ok")) if isinstance(fallback_handoff, dict) else False,
        "metadata_available": isinstance(fallback_handoff, dict),
    }
    if qlip_solve_compatible:
        missing = []
    elif missing_pairs:
        missing = ["pot_pair_coverage"]
    else:
        missing = ["context.pot_root"]
    if qlip_solve_compatible and pot_root_source == "fresh_corpus":
        reason = "Fresh SPP root generated from retrieved corpus and validated."
    elif qlip_solve_compatible:
        reason = "Fallback precompiled POT root used after fresh corpus generation was insufficient."
    elif missing_pairs:
        reason = "No compatible SPP POT root could be generated/found: " + ", ".join(missing_pairs)
    else:
        reason = "No compatible SPP POT root could be generated/found."
    compatibility = {
        "qlip_version": "1.0",
        "spp_maker_version": "runtime",
        "qlip_solve_compatible": qlip_solve_compatible,
        "reason": reason,
        "missing": missing,
        "required_pairs": required_pairs_out,
        "missing_pairs": missing_pairs,
        "sparse_pairs": sparse_pairs,
        "available_pair_count": selected_available_pair_count,
        "fresh_package": fresh_package,
        "fallback_package": fallback_package,
        "selected_package": {
            "pot_root_source": pot_root_source,
            "pot_root": pot_root,
            "available_pairs": selected_available_pairs,
            "supported_pairs": supported_pairs,
            "required_pairs": required_pairs_out,
            "missing_pairs": missing_pairs,
            "diagnostic_only": diagnostic_only,
            "required_pair_pot_export_complete": bool(qlip_solve_compatible),
            "qlip_solve_compatible": qlip_solve_compatible,
            "fallback_required_to_solve": fallback_required_to_solve,
            "fallback_selected_reason": fallback_reason,
        },
        "pot_compat": compat_evidence,
        "pot_root_source": pot_root_source,
        "extraction_mode": fresh_handoff.get("fresh_generation", {}).get("extraction_mode")
        if isinstance(fresh_handoff.get("fresh_generation"), dict)
        else None,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "selected_fallback_root": selected_fallback_root,
        "fresh_generation": fresh_handoff.get("fresh_generation", {}),
        "recommended_next": "Add QLIP native SPP guidance mode or implement real POT export.",
        "accepted_parameters": ["spp_package_path"],
        "removed_parameters": [
            "pairs_policy",
            "oob_policy",
            "missing_pair_policy",
            "lambda_override",
            "convention_override",
            "r_cut",
            "top_k_breakdown",
            "weighting_profile",
            "structure_perturbation_profile",
            "base_weight_scale",
            "guidance_weight_scale",
            "template_seed_profile",
            "lattice_candidate_profile",
            "symmetry_relaxation_profile",
            "ordering_perturbation_profile",
        ],
    }
    files = {
        "package_manifest.json": {
            "spp_run_root": str(run_root),
            "calibration_json": str(calibration_path),
            "fit_spp_root": str(fit_spp_root),
            "scaled_spp_root": str(scaled_spp_root),
            "final_bundle": str(final_bundle),
            "package_json": str(package_json_path),
            "log_path": str(log_path),
        },
        "calibration_refs.json": {
            "calibration_json": str(calibration_path),
            "calibration_data": _load_json(calibration_path),
        },
        "statistical_refs.json": {
            "fit_spp_root": str(fit_spp_root),
            "scaled_spp_root": str(scaled_spp_root),
            "final_bundle": str(final_bundle),
            "package_json": str(package_json_path),
            "log_path": str(log_path),
        },
        "compatibility.json": compatibility,
        "pot_handoff.json": {
            "context": {"pot_root": pot_root} if pot_root else {},
            "summary": (
                "Fresh SPP root generated from retrieved corpus."
                if qlip_solve_compatible and pot_root_source == "fresh_corpus"
                else (
                    "Fallback precompiled POT root used."
                    if qlip_solve_compatible
                    else "No compatible SPP POT root could be generated/found."
                )
            ),
            "published_spp_run_path": pot_handoff.get("run_path"),
            "pot_count": pot_handoff.get("pot_count", 0),
            "pot_root_source": pot_root_source,
            "extraction_mode": fresh_handoff.get("fresh_generation", {}).get("extraction_mode")
            if isinstance(fresh_handoff.get("fresh_generation"), dict)
            else None,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "selected_fallback_root": selected_fallback_root,
            "fresh_generation": fresh_handoff.get("fresh_generation", {}),
        "required_pairs": required_pairs_out,
        "selected_pot_root": selected_pot_root,
        "supported_pairs": supported_pairs,
        "partial_pot_root": partial_pot_root,
        "can_use_as_partial_guidance": can_use_as_partial_guidance,
        "qlip_partial_guidance_compatible": can_use_as_partial_guidance,
        "partial_guidance_pot_root": partial_guidance_pot_root,
        "supported_pair_pot_paths": supported_pair_pot_paths,
        "missing_pair_policy_recommendation": "neutral",
        "strict_pair_coverage": False if can_use_as_partial_guidance else bool(qlip_solve_compatible),
        "diagnostic_only": diagnostic_only,
        "required_pair_pot_export_complete": bool(qlip_solve_compatible),
        "qlip_solve_compatible": qlip_solve_compatible,
        "fallback_required_to_solve": fallback_required_to_solve,
        "fallback_selected_reason": fallback_reason,
        "missing_pairs": missing_pairs,
            "sparse_pairs": sparse_pairs,
            "candidate_roots_checked": candidate_roots_checked,
            "available_pairs_by_candidate_root": pot_handoff.get("available_pairs_by_candidate_root", {}),
            "available_pair_count": selected_available_pair_count,
            "fallback_available_pair_count": pot_handoff.get("available_pair_count", 0) if pot_root_source in {"fallback_precompiled", "none"} else 0,
            "fresh_package": fresh_package,
            "fallback_package": fallback_package,
            "nearest_candidate_roots": pot_handoff.get("nearest_candidate_roots", []),
            "compat": compat_evidence,
            "artifact_refs": pot_handoff.get("artifact_refs", []),
            "errors": combined_errors,
        },
        "provenance.json": {
            "tool": "SPP-Maker-QLIP",
            "source": str(run_root),
            "calibration_source": str(calibration_path),
        },
    }
    for filename, payload in files.items():
        (guidance_package_path / filename).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    created_files = sorted(files)
    output_bytes = sum((guidance_package_path / filename).stat().st_size for filename in created_files)
    return {
        "guidance_package_path": str(guidance_package_path),
        "contents": created_files,
        "compatibility": compatibility,
        "context": {"pot_root": pot_root} if pot_root else {},
        "selected_pot_root": selected_pot_root,
        "pot_root_source": pot_root_source,
        "extraction_mode": fresh_handoff.get("fresh_generation", {}).get("extraction_mode")
        if isinstance(fresh_handoff.get("fresh_generation"), dict)
        else None,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "selected_fallback_root": selected_fallback_root,
        "fresh_generation": fresh_handoff.get("fresh_generation", {}),
        "request_ref": str(package_json_path) if qlip_solve_compatible else None,
        "material_system": material_system or formula,
        "formula": formula or material_system,
        "artifact_refs": pot_handoff.get("artifact_refs", []),
        "summary": (
            "Fresh SPP root generated from retrieved corpus."
            if qlip_solve_compatible and pot_root_source == "fresh_corpus"
            else (
                "Fallback precompiled POT root used."
                if qlip_solve_compatible
                else (
                    "No compatible SPP POT root could be generated/found: "
                    + ", ".join(missing_pairs)
                    if missing_pairs
                    else "No compatible SPP POT root could be generated/found."
                )
            )
        ),
        "errors": combined_errors,
        "required_pairs": required_pairs_out,
        "missing_pairs": missing_pairs,
        "supported_pairs": supported_pairs,
        "partial_pot_root": partial_pot_root,
        "can_use_as_partial_guidance": can_use_as_partial_guidance,
        "qlip_partial_guidance_compatible": can_use_as_partial_guidance,
        "partial_guidance_pot_root": partial_guidance_pot_root,
        "supported_pair_pot_paths": supported_pair_pot_paths,
        "missing_pair_policy_recommendation": "neutral",
        "strict_pair_coverage": False if can_use_as_partial_guidance else bool(qlip_solve_compatible),
        "diagnostic_only": diagnostic_only,
        "required_pair_pot_export_complete": bool(qlip_solve_compatible),
        "qlip_solve_compatible": qlip_solve_compatible,
        "fallback_required_to_solve": fallback_required_to_solve,
        "fallback_selected_reason": fallback_reason,
        "sparse_pairs": sparse_pairs,
        "available_pairs": selected_available_pairs,
        "candidate_roots_checked": candidate_roots_checked,
        "available_pairs_by_candidate_root": pot_handoff.get("available_pairs_by_candidate_root", {}),
        "available_pair_count": selected_available_pair_count,
        "fresh_package": fresh_package,
        "fallback_package": fallback_package,
        "selected_package": compatibility["selected_package"],
        "provenance": {
            "git_sha": None,
            "tool": "SPP-Maker-QLIP",
            "tool_version": "runtime",
            "params_hash": None,
            "content_hash": "runtime-hash",
        },
        "output_bytes": output_bytes,
    }
