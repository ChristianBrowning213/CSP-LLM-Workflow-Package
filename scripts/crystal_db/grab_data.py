#!/usr/bin/env python3
"""Build local Crystal-DB datasets from tracked Materials Project requests."""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PARSER_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
CRYSTAL_DB_SCIENTIFIC_REVISION = "e33d5cc55be01f800a7cf055cc1793d982deb5bc"
EMBEDDING_MODEL = "text-embedding-bge-m3"


@dataclass(frozen=True)
class Request:
    name: str
    description: str
    source_reason: str
    fields: tuple[str, ...]
    stable_only: bool
    chemsys: str | None
    elements: tuple[str, ...]
    limit: int
    chunk_size: int
    rps: float


def parse_requests(path: Path) -> list[Request]:
    parser = configparser.ConfigParser(interpolation=None)
    with path.open("r", encoding="utf-8") as handle:
        parser.read_file(handle)
    requests: list[Request] = []
    for name in parser.sections():
        section = parser[name]
        fields = tuple(item.strip() for item in section.get("fields", "").split(",") if item.strip())
        if fields != ("material_id",):
            raise ValueError(f"{name}: source downloader supports fields=material_id only")
        limit = section.getint("limit")
        if limit < 1:
            raise ValueError(f"{name}: limit must be positive")
        requests.append(
            Request(
                name=name,
                description=section.get("description", "").strip(),
                source_reason=section.get("source_reason", "").strip(),
                fields=fields,
                stable_only=section.getboolean("stable_only"),
                chemsys=section.get("chemsys", "").strip() or None,
                elements=tuple(item for item in section.get("elements", "").split() if item),
                limit=limit,
                chunk_size=section.getint("chunk_size", fallback=200),
                rps=section.getfloat("rps", fallback=8.0),
            )
        )
    if not requests:
        raise ValueError("request file contains no sections")
    return requests


def acquisition_command(request: Request, cif_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(REPO_ROOT / "packages" / "crystal_db" / "grab_mp_bulk.py"),
        "--out", str(cif_dir), "--max", str(request.limit),
        "--chunk-size", str(request.chunk_size), "--rps", str(request.rps), "--resume",
    ]
    if request.stable_only:
        command.append("--stable-only")
    if request.chemsys:
        command.extend(["--chemsys", request.chemsys])
    if request.elements:
        command.extend(["--elements", *request.elements])
    return command


def build_command(request: Request, cif_dir: Path, runtime_root: Path) -> list[str]:
    dataset_root = runtime_root / request.name
    return [
        sys.executable,
        str(REPO_ROOT / "packages" / "crystal_db" / "scripts" / "build_crystaldb_corpus.py"),
        "--dataset-id", request.name,
        "--out-db", str(dataset_root / f"{request.name}.db"),
        "--out-root", str(runtime_root),
        "--source", "local_cif", "--cif-dir", str(cif_dir),
        "--source-query-name", request.name,
        "--purpose", request.description,
        "--max-structures", str(request.limit),
        "--make-crystalcards", "--make-fingerprints", "--make-text-embeddings",
        "--make-sequences", "--retrieval-smoke",
    ]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--requests", type=Path, required=True)
    ap.add_argument("--runtime-root", type=Path, default=REPO_ROOT / "data" / "crystal_db" / "runtime")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    request_path = args.requests.resolve()
    request_hash = hashlib.sha256(request_path.read_bytes()).hexdigest()
    parsed = parse_requests(request_path)

    preview = {
        "parser_version": PARSER_VERSION,
        "request_file": str(request_path),
        "request_sha256": request_hash,
        "api_key_present": bool(os.environ.get("MP_API_KEY")),
        "api_version": "SOURCE_EVIDENCE_MISSING",
        "requests": [request.__dict__ for request in parsed],
    }
    print(json.dumps(preview, indent=2, sort_keys=True))
    if args.dry_run:
        return 0
    if not os.environ.get("MP_API_KEY"):
        print("ERROR: set MP_API_KEY for a live Materials Project build", file=sys.stderr)
        return 2

    for request in parsed:
        dataset_root = args.runtime_root.resolve() / request.name
        cif_dir = dataset_root / "cifs"
        cif_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(acquisition_command(request, cif_dir), cwd=REPO_ROOT, check=True)
        subprocess.run(build_command(request, cif_dir, args.runtime_root.resolve()), cwd=REPO_ROOT, check=True)
        acquisition_rows = _read_jsonl(cif_dir / "manifest.jsonl")
        ok_rows = [row for row in acquisition_rows if row.get("status") == "OK"]
        db_path = dataset_root / f"{request.name}.db"
        dataset_card_path = dataset_root / "dataset_card.json"
        dataset_card = json.loads(dataset_card_path.read_text(encoding="utf-8"))
        build_manifest = {
            **preview,
            "request_name": request.name,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "crystal_db_scientific_revision": CRYSTAL_DB_SCIENTIFIC_REVISION,
            "material_ids": [str(row["material_id"]) for row in ok_rows],
            "retrieval_timestamps": [str(row["retrieved_at"]) for row in ok_rows],
            "raw_cif_sha256": {str(row["material_id"]): str(row["cif_sha256"]) for row in ok_rows},
            "database_path": str(db_path),
            "database_sha256": _sha256(db_path),
            "record_count": int(dataset_card.get("structure_count", len(ok_rows))),
            "embedding_model": dataset_card.get("embedding_model") or EMBEDDING_MODEL,
            "embedding_count": int(dataset_card.get("embedding_count", 0)),
            "embedding_dimensions": "recorded in Crystal-DB text_embeddings.dim when embeddings are built",
            "acquisition_manifest": str(cif_dir / "manifest.jsonl"),
            "dataset_card": str(dataset_card_path),
        }
        (dataset_root / "bootstrap_manifest.json").write_text(
            json.dumps(build_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
