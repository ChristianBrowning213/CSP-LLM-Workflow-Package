from __future__ import annotations

import json
import sys
from typing import Any, Callable


def serve(
    tools: list[str],
    on_call: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        rid = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        if method == "tools/list":
            response = {"id": rid, "result": {"tools": [{"name": tool} for tool in tools]}}
        elif method == "tools/call":
            name = params["name"]
            arguments = params.get("arguments", {})
            result = on_call(name, arguments)
            response = {"id": rid, "result": result}
        else:
            response = {"id": rid, "error": {"message": f"unknown method {method}"}}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
