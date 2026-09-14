import json
import os
import shutil
from typing import Optional

from .utils import now_iso_utc


def snapshot_db(*, db_path: str, out_dir: str) -> str:
    timestamp = now_iso_utc().replace(":", "-")
    target_dir = os.path.join(out_dir, timestamp)
    os.makedirs(target_dir, exist_ok=True)

    db_name = os.path.basename(db_path)
    snapshot_path = os.path.join(target_dir, db_name)
    shutil.copy2(db_path, snapshot_path)

    manifest = {
        "created_at": now_iso_utc(),
        "db_path": db_path,
        "snapshot_path": snapshot_path,
    }
    with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return target_dir
