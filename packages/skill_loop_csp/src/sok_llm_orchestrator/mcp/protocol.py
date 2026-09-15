from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RPCRequest:
    id: int
    method: str
    params: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": self.id, "method": self.method, "params": self.params}, sort_keys=True)


def parse_json_line(line: str) -> dict[str, Any]:
    return json.loads(line)
