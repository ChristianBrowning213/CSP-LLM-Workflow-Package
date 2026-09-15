"""Best-effort adapter for LLM-CSP, QLIP, and evidence-pack run archives."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

from sca.traceability.schema import (
    ConstraintTrace,
    DiagnosticsTrace,
    FinalDecisionTrace,
    GeneratedCandidateTrace,
    RelaxationTrace,
    RetrievalTrace,
    SolverTrace,
    SPPTrace,
    StructuredIntent,
    TraceableRunBundle,
    ValidationTrace,
)


PROMPT_NAMES = ("prompt.txt", "input.txt", "input_prompt.txt", "prompt.md")
INTENT_PATTERNS = ("structured_intent*.json", "*intent*.json", "robocrys_intent_rescore.json")
RETRIEVAL_PATTERNS = ("retrieval_trace*.json", "*retrieval*.json", "*evidence*.json", "qlip*.json")
CONSTRAINT_PATTERNS = ("constraint_trace*.json", "*constraints*.json")
SPP_PATTERNS = ("spp_trace*.json", "spp*.json")
SOLVER_PATTERNS = ("solver_trace*.json", "*solver*.json", "qlip_solve*.json", "*solve*.json", "*solver*.log", "*solve*.log")
VALIDATION_PATTERNS = ("validation_trace*.json", "*validation*.json", "*benchmark_results*.json", "*benchmark*.csv")
RELAXATION_PATTERNS = ("relaxation_trace*.json", "*relax*.json", "*relaxed*.cif")
DIAGNOSTICS_PATTERNS = ("diagnostics_trace*.json", "*diagnostic*.json", "*diagnostic*.csv", "*diagnostic*.md")
DECISION_PATTERNS = ("final_decision*.json", "*decision*.json", "*summary*.json", "*report*.md")
CONFIG_PATTERNS = {
    "environment": ("environment.json", "env.json", "requirements*.txt"),
    "generator_config": ("generator_config.json", "*generator*.json", "config.json"),
    "retrieval_config": ("retrieval_config.json", "*retrieval_config*.json"),
    "solver_config": ("solver_config.json", "solver_config.json", "*solver_config*.json"),
}


def detect_llm_csp_archive(path: str | Path) -> bool:
    """Return true when a directory looks like a generated-crystal run archive."""

    root = Path(path)
    if not root.exists() or not root.is_dir():
        return False
    markers = 0
    if _first_existing(root, PROMPT_NAMES):
        markers += 1
    if _find_first(root, RETRIEVAL_PATTERNS):
        markers += 1
    if _find_first(root, SOLVER_PATTERNS):
        markers += 1
    if list(root.rglob("*.cif")):
        markers += 1
    if _find_first(root, VALIDATION_PATTERNS) or _find_first(root, DIAGNOSTICS_PATTERNS):
        markers += 1
    return markers > 0


def load_llm_csp_archive(path: str | Path, run_id: str | None = None) -> TraceableRunBundle:
    """Convert an archive directory into a TraceableRunBundle in memory."""

    root = Path(path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Archive directory does not exist: {root}")
    errors: list[str] = []
    prompt_path = _first_existing(root, PROMPT_NAMES)
    prompt_text = _read_text(prompt_path, errors) if prompt_path else ""
    intent_path = _find_first(root, INTENT_PATTERNS)
    retrieval_path = _find_first(root, RETRIEVAL_PATTERNS)
    constraint_path = _find_first(root, CONSTRAINT_PATTERNS)
    spp_path = _find_first(root, SPP_PATTERNS)
    solver_path = _find_first(root, SOLVER_PATTERNS)
    validation_path = _find_first(root, VALIDATION_PATTERNS)
    relaxation_path = _find_first(root, RELAXATION_PATTERNS)
    diagnostics_path = _find_first(root, DIAGNOSTICS_PATTERNS)
    decision_path = _find_first(root, DECISION_PATTERNS)
    cifs = sorted(root.rglob("*.cif"))
    generated_cifs = [path for path in cifs if "_chgnet_relaxed" not in path.name.lower()]
    missing = []

    structured_intent = _structured_intent(intent_path, errors)
    retrieval_trace = _retrieval_trace(retrieval_path, errors)
    constraint_trace = _constraint_trace(constraint_path, structured_intent, errors)
    spp_trace = _spp_trace(spp_path, errors)
    solver_trace = _solver_trace(solver_path, errors)
    generated_candidates = _generated_candidates(generated_cifs)
    validation_trace = _validation_trace(validation_path, errors)
    relaxation_trace = _relaxation_trace(relaxation_path, errors)
    diagnostics_trace = _diagnostics_trace(diagnostics_path, errors)
    final_decision = _final_decision(decision_path, errors)

    for name, value in (
        ("prompt", prompt_path),
        ("structured_intent", structured_intent),
        ("retrieval_trace", retrieval_trace),
        ("constraint_trace", constraint_trace),
        ("solver_trace", solver_trace),
        ("generated_candidates", generated_candidates if generated_cifs else None),
        ("validation_trace", validation_trace),
        ("diagnostics_trace", diagnostics_trace),
        ("final_decision", final_decision),
    ):
        if value is None:
            missing.append(name)

    files = _file_map(
        {
            "prompt": prompt_path,
            "structured_intent": intent_path,
            "retrieval_trace": retrieval_path,
            "constraint_trace": constraint_path,
            "spp_trace": spp_path,
            "solver_trace": solver_path,
            "validation_trace": validation_path,
            "relaxation_trace": relaxation_path,
            "diagnostics_trace": diagnostics_path,
            "final_decision": decision_path,
        }
    )
    bundle = TraceableRunBundle(
        run_id=run_id or root.name,
        prompt_id=root.name,
        input_text=prompt_text,
        run_dir=str(root),
        files=files,
        status="converted_with_missing_artifacts" if missing else "converted",
        errors=[*errors, *[f"missing_source_artifact:{name}" for name in missing]],
        notes="Converted by sca.traceability.adapters.llm_csp_archive.",
        structured_intent=structured_intent,
        retrieval_trace=retrieval_trace,
        constraint_trace=constraint_trace,
        spp_trace=spp_trace,
        solver_trace=solver_trace,
        generated_candidates=generated_candidates if generated_cifs else None,
        validation_trace=validation_trace,
        relaxation_trace=relaxation_trace,
        diagnostics_trace=diagnostics_trace,
        final_decision=final_decision,
    )
    return bundle


def write_traceable_bundle(bundle: TraceableRunBundle, out_dir: str | Path) -> dict[str, Any]:
    """Write standard traceability artifacts plus bundle.json and a manifest."""

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bundle.json").write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    written: dict[str, Path] = {}

    if bundle.input_text:
        written["prompt"] = _write_text(out / "prompt.txt", bundle.input_text)
    _write_model(out, "structured_intent", "structured_intent.json", bundle.structured_intent, written)
    _write_model(out, "retrieval_trace", "retrieval_trace.json", bundle.retrieval_trace, written)
    _write_model(out, "constraint_trace", "constraint_trace.json", bundle.constraint_trace, written)
    _write_model(out, "spp_trace", "spp_trace.json", bundle.spp_trace, written)
    _write_model(out, "solver_trace", "solver_trace.json", bundle.solver_trace, written)
    _write_model(out, "validation_trace", "validation_trace.json", bundle.validation_trace, written)
    _write_model(out, "relaxation_trace", "relaxation_trace.json", bundle.relaxation_trace, written)
    _write_model(out, "diagnostics_trace", "diagnostics_trace.json", bundle.diagnostics_trace, written)
    _write_model(out, "final_decision", "final_decision.json", bundle.final_decision, written)

    if bundle.generated_candidates and bundle.generated_candidates.candidates:
        cifs_dir = out / "cifs"
        cifs_dir.mkdir(exist_ok=True)
        copied = []
        for candidate in bundle.generated_candidates.candidates:
            source = Path(str(candidate.get("source_path") or candidate.get("cif_path") or ""))
            target = cifs_dir / source.name if source.name else cifs_dir / f"{candidate.get('candidate_id')}.cif"
            if source.exists():
                shutil.copy2(source, target)
            candidate["cif_path"] = str(target.relative_to(out))
            copied.append(candidate)
        bundle.generated_candidates.candidates = copied
        _write_model(out, "generated_candidates", "generated_candidates.json", bundle.generated_candidates, written)

    for artifact_name, patterns in CONFIG_PATTERNS.items():
        source = _find_first(Path(bundle.run_dir or "."), patterns)
        if source:
            suffix = ".json" if source.suffix.lower() == ".json" else source.suffix
            target = out / f"{artifact_name}{suffix}"
            shutil.copy2(source, target)
            written[artifact_name] = target

    manifest_row = {
        "run_id": bundle.run_id,
        "prompt_id": bundle.prompt_id,
        "bundle_dir": str(out),
        "bundle_json": str(out / "bundle.json"),
        "status": bundle.status,
        "missing_source_artifacts": ";".join(
            error.split(":", 1)[1] for error in bundle.errors if error.startswith("missing_source_artifact:")
        ),
        "conversion_errors": ";".join(
            error for error in bundle.errors if not error.startswith("missing_source_artifact:")
        ),
    }
    _write_manifest(out / "bundle_manifest.csv", [manifest_row])
    return {"out_dir": str(out), "manifest_row": manifest_row, "written": {k: str(v) for k, v in written.items()}}


def _structured_intent(path: Path | None, errors: list[str]) -> StructuredIntent | None:
    data = _read_json(path, errors) if path else {}
    if not data:
        return None
    intent = data.get("structured_intent") if isinstance(data.get("structured_intent"), dict) else data
    return StructuredIntent(
        formula=_first(intent, "formula", "target_formula", "composition"),
        chemical_system=_first(intent, "chemical_system", "chemicalSystem"),
        space_group=_first(intent, "space_group", "target_space_group", "spacegroup"),
        crystal_system=_first(intent, "crystal_system"),
        prototype_family=_first(intent, "prototype_family", "target_structure_family", "family"),
        constraints=_as_list(intent.get("constraints") or intent.get("expected_constraints")),
        status="loaded",
    )


def _retrieval_trace(path: Path | None, errors: list[str]) -> RetrievalTrace | None:
    data = _read_json(path, errors) if path and path.suffix.lower() == ".json" else {}
    if path and not data and path.suffix.lower() != ".json":
        return RetrievalTrace(query=None, mode=None, retrieved=[], status="linked", notes=str(path))
    if not data:
        return None
    root = data.get("retrieval_trace") if isinstance(data.get("retrieval_trace"), dict) else data
    items = root.get("retrieved") or root.get("evidence") or root.get("results") or root.get("items") or []
    retrieved = []
    for index, item in enumerate(_as_list(items)):
        if not isinstance(item, dict):
            continue
        retrieved.append(
            {
                "evidence_id": str(_first(item, "evidence_id", "id", "material_id") or f"evidence_{index:03d}"),
                "formula": _first(item, "formula", "pretty_formula"),
                "chemical_system": _first(item, "chemical_system"),
                "family": _first(item, "family", "prototype_family", "structure_family"),
                "space_group": _first(item, "space_group", "spacegroup", "sg"),
                "cif_path": _first(item, "cif_path", "path"),
                "score": _as_float(_first(item, "score", "retrieval_score")),
                "citation": _first(item, "citation", "source"),
                "parseable": _as_bool(_first(item, "parseable", "parse_ok")),
            }
        )
    return RetrievalTrace(query=_first(root, "query", "retrieval_query"), mode=_first(root, "mode", "retrieval_mode"), retrieved=retrieved, status="loaded")


def _constraint_trace(path: Path | None, intent: StructuredIntent | None, errors: list[str]) -> ConstraintTrace | None:
    data = _read_json(path, errors) if path else {}
    if data:
        root = data.get("constraint_trace") if isinstance(data.get("constraint_trace"), dict) else data
        constraints = _as_list(root.get("constraints"))
        return ConstraintTrace(constraints=constraints, status="loaded")
    if intent and intent.constraints:
        return ConstraintTrace(constraints=intent.constraints, status="inferred_from_structured_intent")
    return None


def _spp_trace(path: Path | None, errors: list[str]) -> SPPTrace | None:
    data = _read_json(path, errors) if path else {}
    if not data:
        return None
    pairs = data.get("pairs") or data.get("pair_scores") or data.get("pair_statistics") or []
    return SPPTrace(pairs=_as_list(pairs), status="loaded")


def _solver_trace(path: Path | None, errors: list[str]) -> SolverTrace | None:
    if path is None:
        return None
    if path.suffix.lower() == ".json":
        data = _read_json(path, errors)
        root = data.get("solver_trace") if isinstance(data.get("solver_trace"), dict) else data
        return SolverTrace(
            backend=_first(root, "backend", "solver_backend", "solver"),
            solver_status=_first(root, "solver_status", "status"),
            objective_value=_as_float(_first(root, "objective_value", "objective")),
            num_variables=_as_int(_first(root, "num_variables", "variable_count")),
            num_constraints=_as_int(_first(root, "num_constraints", "constraint_count")),
            solve_time_seconds=_as_float(_first(root, "solve_time_seconds", "runtime_seconds", "solve_time")),
            infeasibility_explanation=_first(root, "infeasibility_explanation", "explanation"),
            status="loaded",
        )
    text = _read_text(path, errors) or ""
    status = _status_from_text(text)
    return SolverTrace(backend="log", solver_status=status, status="loaded_from_log", notes=str(path))


def _generated_candidates(cifs: list[Path]) -> GeneratedCandidateTrace:
    return GeneratedCandidateTrace(
        candidates=[
            {"candidate_id": f"candidate_{index:03d}", "cif_path": str(path), "source_path": str(path), "rank": index}
            for index, path in enumerate(cifs, start=1)
        ],
        status="loaded",
    )


def _validation_trace(path: Path | None, errors: list[str]) -> ValidationTrace | None:
    if not path:
        return None
    data = _read_json(path, errors) if path.suffix.lower() == ".json" else {}
    return ValidationTrace(report_path=str(path), pre_dft_valid=_as_bool(_first(data, "pre_dft_valid", "valid")), status="linked")


def _relaxation_trace(path: Path | None, errors: list[str]) -> RelaxationTrace | None:
    if not path:
        return None
    data = _read_json(path, errors) if path.suffix.lower() == ".json" else {}
    return RelaxationTrace(report_path=str(path), relax_ok=_as_bool(_first(data, "relax_ok", "success")), status="linked")


def _diagnostics_trace(path: Path | None, errors: list[str]) -> DiagnosticsTrace | None:
    if not path:
        return None
    data = _read_json(path, errors) if path.suffix.lower() == ".json" else {}
    return DiagnosticsTrace(report_path=str(path), failure_type=_first(data, "failure_type", "primary_category"), status="linked")


def _final_decision(path: Path | None, errors: list[str]) -> FinalDecisionTrace | None:
    if not path:
        return None
    if path.suffix.lower() == ".json":
        data = _read_json(path, errors)
        return FinalDecisionTrace(
            decision=_first(data, "decision", "final_decision", "status"),
            explanation=_first(data, "explanation", "summary", "notes"),
            citations=_as_list(data.get("citations")),
            status="loaded",
        )
    text = _read_text(path, errors) or ""
    return FinalDecisionTrace(decision=None, explanation=text[:2000], citations=[], status="loaded_from_text")


def _find_first(root: Path, patterns: tuple[str, ...]) -> Path | None:
    matches = []
    for pattern in patterns:
        matches.extend(path for path in root.rglob(pattern) if path.is_file())
    return sorted(set(matches), key=lambda path: (len(path.parts), str(path)))[0] if matches else None


def _first_existing(root: Path, names: tuple[str, ...]) -> Path | None:
    for name in names:
        candidate = root / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _read_json(path: Path | None, errors: list[str]) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return {}
    return value if isinstance(value, dict) else {}


def _read_text(path: Path | None, errors: list[str]) -> str | None:
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
        return None


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def _write_model(out: Path, key: str, filename: str, value: Any, written: dict[str, Path]) -> None:
    if value is None:
        return
    target = out / filename
    target.write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")
    written[key] = target


def _write_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _file_map(paths: dict[str, Path | None]) -> dict[str, str]:
    return {key: str(path) for key, path in paths.items() if path is not None}


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if isinstance(data, dict) and key in data and data[key] not in ("", None):
            return data[key]
    return None


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(";") if part.strip()]
    return [value]


def _as_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "ok", "success"}:
        return True
    if normalized in {"false", "0", "no", "n", "failed", "fail"}:
        return False
    return None


def _status_from_text(text: str) -> str | None:
    lowered = text.lower()
    for status in ("optimal", "infeasible", "feasible", "timeout", "failed"):
        if status in lowered:
            return status
    return None
