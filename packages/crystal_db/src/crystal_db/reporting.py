from typing import Any, Dict, Optional

from .runlog import fetch_run_report


def report_run(*, run_id: str, db_path: Optional[str]) -> Dict[str, Any]:
    return fetch_run_report(run_id, db_path)
