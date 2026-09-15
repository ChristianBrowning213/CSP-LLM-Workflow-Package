from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if "key" in key.lower() or "token" in key.lower():
                out[key] = "***REDACTED***"
            else:
                out[key] = _redact(value)
        return out
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


@dataclass(slots=True)
class RunLogger:
    run_dir: Path
    calls_dir: Path = field(init=False)
    log_path: Path = field(init=False)
    _call_index: int = field(default=0, init=False)
    artifacts: dict[str, str] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.calls_dir = self.run_dir / "calls"
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.run_dir / "tool_call_log.jsonl"

    def write_artifact(self, name: str, payload: Any) -> Path:
        path = self.run_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = canonical_json(payload)
        path.write_text(text + "\n", encoding="utf-8")
        digest = sha256_text(text)
        self.artifacts[str(path.relative_to(self.run_dir))] = digest
        (Path(str(path) + ".sha256")).write_text(digest + "\n", encoding="utf-8")
        return path

    def log_tool_call(self, tool_name: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        idx = self._call_index
        self._call_index += 1
        safe_name = tool_name.replace(".", "_")
        req_path = self.calls_dir / f"{idx:03d}_{safe_name}_request.json"
        resp_path = self.calls_dir / f"{idx:03d}_{safe_name}_response.json"
        req_path.write_text(canonical_json(request) + "\n", encoding="utf-8")
        resp_path.write_text(canonical_json(response) + "\n", encoding="utf-8")
        req_hash = sha256_text(canonical_json(request))
        resp_hash = sha256_text(canonical_json(response))
        (Path(str(req_path) + ".sha256")).write_text(req_hash + "\n", encoding="utf-8")
        (Path(str(resp_path) + ".sha256")).write_text(resp_hash + "\n", encoding="utf-8")
        entry = {
            "index": idx,
            "tool_name": tool_name,
            "request_hash": req_hash,
            "response_hash": resp_hash,
            "request": _redact(request),
            "response": _redact(response),
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(canonical_json(entry) + "\n")

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        manifest_payload = dict(manifest)
        manifest_payload["artifacts"] = {k: self.artifacts[k] for k in sorted(self.artifacts)}
        return self.write_artifact("manifest.json", manifest_payload)
