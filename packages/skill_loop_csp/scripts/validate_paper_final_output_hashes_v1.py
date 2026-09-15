"""Recompute every final output SHA-256 recorded in the manifest."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "artifacts" / "paper_final_results_v1" / "09_reproducibility" / "FINAL_OUTPUT_HASH_MANIFEST.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def main() -> int:
    with MANIFEST.open(encoding="utf-8", newline="") as handle: rows = list(csv.DictReader(handle))
    failures=[]
    for row in rows:
        path=Path(row["absolute_path"])
        if not path.is_file(): failures.append({"path":str(path),"status":"MISSING"})
        elif sha256(path)!=row["sha256"]: failures.append({"path":str(path),"status":"HASH_MISMATCH"})
        elif path.stat().st_size!=int(row["bytes"]): failures.append({"path":str(path),"status":"SIZE_MISMATCH"})
    if failures: raise RuntimeError(json.dumps(failures[:10],indent=2))
    print(json.dumps({"manifest_entries":len(rows),"failures":0,"status":"PASS"},sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
