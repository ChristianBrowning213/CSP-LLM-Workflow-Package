import json
import os
import csv
from typing import Any, Dict, List, Optional

from .audit_log import AuditLogger
from .db import connect, init_db
from .utils import now_iso_utc, stable_hash


def _normalize_cif(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines) + "\n"


def _read_cif(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_manifest_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict) and "candidates" in payload:
        payload = payload["candidates"]
    if not isinstance(payload, list):
        raise ValueError("manifest JSON must be a list or contain a 'candidates' list")
    return payload


def _load_manifest_csv(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _coerce_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(";") if item.strip()]
    return [str(value)]


def _clean_meta(raw: Dict[str, Any]) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for key, value in raw.items():
        if key in ("file", "path", "cif", "cif_text"):
            continue
        if key == "tags":
            meta["tags"] = _coerce_tags(value)
        elif value is None or value == "":
            continue
        else:
            meta[key] = value
    return meta


def _candidate_id_from_path(path: str) -> str:
    base = os.path.basename(path)
    if base.lower().endswith(".cif"):
        base = base[:-4]
    return base or "candidate"


def _load_candidates_from_folder(folder_path: str) -> List[Dict[str, Any]]:
    manifest_path_json = os.path.join(folder_path, "manifest.json")
    manifest_path_csv = os.path.join(folder_path, "manifest.csv")

    manifest_entries: List[Dict[str, Any]] = []
    if os.path.exists(manifest_path_json):
        manifest_entries = _load_manifest_json(manifest_path_json)
    elif os.path.exists(manifest_path_csv):
        manifest_entries = _load_manifest_csv(manifest_path_csv)

    manifest_map: Dict[str, Dict[str, Any]] = {}
    for entry in manifest_entries:
        file_key = entry.get("file") or entry.get("path")
        if not file_key:
            continue
        normalized = str(file_key).replace("\\", "/")
        manifest_map[normalized] = entry

    cif_files: List[str] = []
    for root, _, files in os.walk(folder_path):
        for name in files:
            if name.lower().endswith(".cif"):
                cif_files.append(os.path.join(root, name))

    cif_files.sort()

    candidates: List[Dict[str, Any]] = []
    for path in cif_files:
        rel = os.path.relpath(path, folder_path).replace("\\", "/")
        manifest = manifest_map.get(rel, {})
        candidate_id = manifest.get("candidate_id") or _candidate_id_from_path(path)
        candidates.append(
            {
                "candidate_id": str(candidate_id),
                "input_path": path,
                "cif_text": None,
                "meta": _clean_meta(manifest),
            }
        )
    return candidates


def _load_candidates_from_manifest(path: str) -> List[Dict[str, Any]]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        rows = _load_manifest_csv(path)
    else:
        rows = _load_manifest_json(path)

    base_dir = os.path.dirname(path)
    candidates: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        candidate_id = row.get("candidate_id") or f"candidate-{idx+1}"
        cif_text = row.get("cif_text") or row.get("cif")
        input_path = row.get("file") or row.get("path")
        if input_path:
            input_path = os.path.join(base_dir, str(input_path))
        candidates.append(
            {
                "candidate_id": str(candidate_id),
                "input_path": input_path,
                "cif_text": cif_text,
                "meta": _clean_meta(row),
            }
        )
    return candidates


def _load_candidates_from_json(path: str) -> List[Dict[str, Any]]:
    rows = _load_manifest_json(path)
    candidates: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        candidate_id = row.get("candidate_id") or f"candidate-{idx+1}"
        cif_text = row.get("cif_text") or row.get("cif")
        input_path = row.get("file") or row.get("path")
        if input_path:
            input_path = os.path.join(os.path.dirname(path), str(input_path))
        candidates.append(
            {
                "candidate_id": str(candidate_id),
                "input_path": input_path,
                "cif_text": cif_text,
                "meta": _clean_meta(row),
            }
        )
    return candidates


def load_candidates(candidates_path: str) -> List[Dict[str, Any]]:
    if os.path.isdir(candidates_path):
        return _load_candidates_from_folder(candidates_path)

    ext = os.path.splitext(candidates_path)[1].lower()
    if ext in (".json", ".csv"):
        if ext == ".json":
            return _load_candidates_from_json(candidates_path)
        return _load_candidates_from_manifest(candidates_path)

    if candidates_path.lower().endswith(".cif"):
        return [
            {
                "candidate_id": _candidate_id_from_path(candidates_path),
                "input_path": candidates_path,
                "cif_text": None,
                "meta": {},
            }
        ]

    raise ValueError("Unsupported candidates path")


def _ensure_unique_id(candidate_id: str, seen: Dict[str, int]) -> str:
    if candidate_id not in seen:
        seen[candidate_id] = 1
        return candidate_id
    seen[candidate_id] += 1
    return f"{candidate_id}-{seen[candidate_id]}"


def propose_candidates(
    *,
    db_path: Optional[str],
    run_name: Optional[str],
    candidates_path: str,
    source: str = "csp",
) -> Dict[str, Any]:
    candidates = load_candidates(candidates_path)
    if not candidates:
        return {"error": "no_candidates"}

    config = {"mode": "propose", "source": source, "candidates_path": candidates_path}
    logger = AuditLogger(db_path, run_name, config, defer_init=False)
    run_id = logger.run_id

    cache_dir = os.path.join("data", "candidates", run_id)
    os.makedirs(cache_dir, exist_ok=True)

    conn = connect(db_path)
    init_db(conn)

    seen: Dict[str, int] = {}
    registered: List[Dict[str, Any]] = []
    log_entries: List[Dict[str, Any]] = []

    for item in candidates:
        input_path = item.get("input_path")
        cif_text = item.get("cif_text")
        if cif_text is None and input_path:
            cif_text = _read_cif(str(input_path))
        if cif_text is None:
            continue

        normalized = _normalize_cif(cif_text)
        input_hash = stable_hash({"cif_text": normalized})

        candidate_id = item.get("candidate_id") or f"candidate-{input_hash[:8]}"
        candidate_id = _ensure_unique_id(str(candidate_id), seen)

        if item.get("cif_text") is not None:
            cache_path = os.path.join(cache_dir, f"{input_hash}.cif")
            if not os.path.exists(cache_path):
                with open(cache_path, "w", encoding="utf-8") as f:
                    f.write(normalized)
            input_path = cache_path

        meta = dict(item.get("meta") or {})
        meta.setdefault("candidate_id", candidate_id)

        conn.execute(
            "INSERT OR REPLACE INTO candidates "
            "(run_id, candidate_id, input_path, input_hash, source, created_at, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                candidate_id,
                str(input_path) if input_path else None,
                input_hash,
                source,
                now_iso_utc(),
                json.dumps(meta, sort_keys=True, separators=(",", ":")),
            ),
        )

        log_entries.append({
            "candidate_id": candidate_id,
            "input_path": str(input_path) if input_path else None,
            "input_hash": input_hash,
            "source": source,
            "meta": meta,
        })

        registered.append(
            {
                "candidate_id": candidate_id,
                "input_path": str(input_path) if input_path else None,
                "input_hash": input_hash,
            }
        )

    conn.commit()
    conn.close()

    for entry in log_entries:
        logger.log_tool_call(
            "register_candidate",
            entry,
            {"status": "registered"},
            now_iso_utc(),
            now_iso_utc(),
            "ok",
            None,
        )

    return {"run_id": run_id, "candidates": registered}
