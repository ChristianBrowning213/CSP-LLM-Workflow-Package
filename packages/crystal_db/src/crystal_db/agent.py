import re
from typing import Any, Dict, List, Optional, Tuple

from .audit_log import AuditLogger
from .db import connect, init_db
from .fingerprint import fingerprint_structure
from .query import get_structure, query_structures
from .similarity import similar_structures
from .utils import now_iso_utc

ELEMENTS = {
    "H", "C", "N", "O", "F", "Li", "Na", "K", "Mg", "Ca",
    "Al", "Si", "P", "S", "Cl", "Fe", "Co", "Ni", "Cu", "Zn",
}


def _extract_structure_id(text: str) -> Optional[str]:
    match = re.search(r"[A-Za-z]+-\d{4}", text)
    if match:
        return match.group(0)
    return None


def _extract_elements(text: str) -> List[str]:
    tokens = re.findall(r"[A-Z][a-z]?", text)
    elements = [tok for tok in tokens if tok in ELEMENTS]
    seen = []
    for el in elements:
        if el not in seen:
            seen.append(el)
    return seen


def _run_tool(logger: AuditLogger, tool_name: str, fn, **kwargs) -> Any:
    started_at = now_iso_utc()
    status = "ok"
    error_text = None
    try:
        output = fn(**kwargs)
    except Exception as exc:
        status = "error"
        error_text = str(exc)
        output = {"error": "exception", "message": error_text}
    ended_at = now_iso_utc()
    logger.log_tool_call(tool_name, kwargs, output, started_at, ended_at, status, error_text)
    return output


def _ensure_fingerprints(logger: AuditLogger, db_path: Optional[str]) -> None:
    conn = connect(db_path)
    init_db(conn)
    missing_rows = conn.execute(
        "SELECT s.structure_id FROM structures s "
        "LEFT JOIN structure_fingerprints f "
        "ON s.structure_id = f.structure_id AND f.fingerprint_method = ? AND f.fingerprint_version = ? "
        "WHERE f.structure_id IS NULL",
        ("fp.simple.v1", "v1"),
    ).fetchall()
    conn.close()

    if not missing_rows:
        return

    for row in missing_rows:
        _run_tool(
            logger,
            "fingerprint_structure",
            fingerprint_structure,
            structure_id=row["structure_id"],
            db_path=db_path,
            store=True,
        )


def _build_answer_from_query(result: Dict[str, Any], logger: AuditLogger) -> Tuple[str, Dict[str, Any]]:
    results = result.get("results", [])
    lines = []
    evidence_items = []
    for item in results:
        structure_id = item.get("structure_id")
        logger.add_explored(structure_id, "retrieved")
        provenance = {
            "source": item.get("source"),
            "source_id": item.get("source_id"),
            "retrieved_at": item.get("retrieved_at"),
            "license_notes": item.get("license_notes"),
            "allow_export": item.get("allow_export"),
        }
        metadata = {
            "formula": item.get("formula"),
            "elements": item.get("elements"),
            "space_group": item.get("space_group"),
            "band_gap_eV": item.get("band_gap_eV"),
            "nsites": item.get("nsites"),
            "volume": item.get("volume"),
        }
        lines.append(
            f"- {structure_id}: formula={metadata['formula']}, space_group={metadata['space_group']}, "
            f"band_gap_eV={metadata['band_gap_eV']}, nsites={metadata['nsites']}, volume={metadata['volume']}; "
            f"source={provenance['source']}, source_id={provenance['source_id']}, retrieved_at={provenance['retrieved_at']}"
        )
        evidence_items.append({"structure_id": structure_id, "provenance": provenance, "metadata": metadata})

    if not lines:
        lines.append("- No matching structures found.")

    answer = "\n".join(lines)
    evidence = {"structures": evidence_items}
    return answer, evidence


def _build_answer_from_get(result: Dict[str, Any], logger: AuditLogger) -> Tuple[str, Dict[str, Any]]:
    if "error" in result:
        return "- Structure not found.", {"structures": []}

    structure_id = result.get("structure_id")
    logger.add_explored(structure_id, "retrieved")
    provenance = {
        "source": result.get("source"),
        "source_id": result.get("source_id"),
        "retrieved_at": result.get("retrieved_at"),
        "license_notes": result.get("license_notes"),
        "allow_export": result.get("allow_export"),
    }
    summary = result.get("canonical_summary", {})
    restricted = result.get("restricted")

    if restricted:
        cif_note = "CIF is restricted and not returned."
    else:
        cif_note = "CIF returned in tool output."

    answer = (
        f"- {structure_id}: reduced_formula={summary.get('reduced_formula')}, nsites={summary.get('nsites')}, "
        f"volume={summary.get('volume')}; source={provenance['source']}, source_id={provenance['source_id']}, "
        f"retrieved_at={provenance['retrieved_at']}. {cif_note}"
    )

    evidence = {
        "structures": [
            {
                "structure_id": structure_id,
                "provenance": provenance,
                "summary": summary,
                "restricted": restricted,
            }
        ]
    }
    return answer, evidence


def _build_answer_from_similar(result: Dict[str, Any], logger: AuditLogger) -> Tuple[str, Dict[str, Any]]:
    neighbors = result.get("neighbors", [])
    lines = []
    evidence_items = []
    for item in neighbors:
        structure_id = item.get("structure_id")
        logger.add_explored(structure_id, "neighbor")
        provenance = item.get("provenance", {})
        metadata = item.get("metadata", {})
        lines.append(
            f"- {structure_id}: distance={item.get('distance')}; formula={metadata.get('formula')}, "
            f"space_group={metadata.get('space_group')}, band_gap_eV={metadata.get('band_gap_eV')}; "
            f"source={provenance.get('source')}, source_id={provenance.get('source_id')}, retrieved_at={provenance.get('retrieved_at')}"
        )
        evidence_items.append({"structure_id": structure_id, "provenance": provenance, "metadata": metadata})

    if not lines:
        lines.append("- No neighbors found.")

    answer = "\n".join(lines)
    evidence = {"structures": evidence_items}
    return answer, evidence


def run_agent(
    *,
    question: str,
    db_path: Optional[str] = None,
    llm: str = "off",
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    config = {"llm": llm, "question": question}
    logger = AuditLogger(db_path, run_name, config)

    q_lower = question.lower()
    structure_id = _extract_structure_id(question)
    elements = _extract_elements(question)

    answer = ""
    evidence: Dict[str, Any] = {"structures": []}

    if "similar" in q_lower or "nearest" in q_lower:
        if not structure_id:
            tool_result = _run_tool(
                logger,
                "query_structures",
                query_structures,
                filter_spec={"limit": 5},
                db_path=db_path,
            )
            answer, evidence = _build_answer_from_query(tool_result, logger)
        else:
            _ensure_fingerprints(logger, db_path)
            tool_result = _run_tool(
                logger,
                "similar_structures",
                similar_structures,
                structure_id=structure_id,
                cif_text=None,
                mode="fingerprint",
                k=5,
                db_path=db_path,
            )
            answer, evidence = _build_answer_from_similar(tool_result, logger)
    elif "cif" in q_lower or "show" in q_lower or "structure" in q_lower:
        if structure_id:
            tool_result = _run_tool(
                logger,
                "get_structure",
                get_structure,
                structure_id=structure_id,
                db_path=db_path,
            )
            answer, evidence = _build_answer_from_get(tool_result, logger)
        else:
            tool_result = _run_tool(
                logger,
                "query_structures",
                query_structures,
                filter_spec={"limit": 5},
                db_path=db_path,
            )
            answer, evidence = _build_answer_from_query(tool_result, logger)
    else:
        filter_spec = {"limit": 5}
        if elements:
            filter_spec["elements_include"] = elements
        tool_result = _run_tool(
            logger,
            "query_structures",
            query_structures,
            filter_spec=filter_spec,
            db_path=db_path,
        )
        answer, evidence = _build_answer_from_query(tool_result, logger)

    logger.save_evidence(evidence)

    return {
        "run_id": logger.run_id,
        "answer": answer,
        "evidence": evidence,
    }
