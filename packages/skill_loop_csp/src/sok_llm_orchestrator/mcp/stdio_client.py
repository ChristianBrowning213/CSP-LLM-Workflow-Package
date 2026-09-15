from __future__ import annotations

import os
import queue
import shlex
import subprocess
import threading
import time
import json
from dataclasses import dataclass, field
from typing import Any

from sok_llm_orchestrator.mcp.protocol import RPCRequest, parse_json_line


class MCPClientError(RuntimeError):
    pass


def _to_args(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return command
    return shlex.split(command, posix=os.name != "nt")


def _request_id_matches(response_id: Any, expected_id: int) -> bool:
    if response_id == expected_id:
        return True
    if isinstance(response_id, str) and response_id.strip() == str(expected_id):
        return True
    return False


@dataclass(slots=True)
class StdioMCPClient:
    command: str | list[str]
    timeout_s: int = 30
    cwd: str | None = None
    env: dict[str, str] | None = None
    _proc: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _request_id: int = field(default=0, init=False)
    _stdout_queue: queue.Queue[str | None] | None = field(default=None, init=False, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _mcp_init_attempted: bool = field(default=False, init=False)
    _mcp_init_ok: bool = field(default=False, init=False)

    def __enter__(self) -> "StdioMCPClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._proc is not None:
            return
        args = _to_args(self.command)
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.cwd,
            env=merged_env,
        )
        self._stdout_queue = queue.Queue()
        self._reader_thread = threading.Thread(target=self._drain_stdout, daemon=True)
        self._reader_thread.start()

    def _drain_stdout(self) -> None:
        proc = self._proc
        out_q = self._stdout_queue
        if proc is None or proc.stdout is None or out_q is None:
            return
        try:
            while True:
                line = proc.stdout.readline()
                if line == "":
                    out_q.put(None)
                    return
                out_q.put(line)
        except Exception:  # noqa: BLE001
            out_q.put(None)

    def close(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=0.5)
        self._proc = None
        self._stdout_queue = None
        self._reader_thread = None
        self._mcp_init_attempted = False
        self._mcp_init_ok = False

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        self._proc.stdin.write(json.dumps(payload, sort_keys=True) + "\n")
        self._proc.stdin.flush()

    def _ensure_mcp_initialized(self) -> None:
        if self._mcp_init_attempted:
            return
        self._mcp_init_attempted = True
        try:
            _ = self._send(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "sok-llm-orchestrator", "version": "0.1.0"},
                },
            )
            self._mcp_init_ok = True
            self._send_notification("notifications/initialized", {})
        except MCPClientError:
            # Legacy shim servers may not implement MCP initialize. Continue in compatibility mode.
            self._mcp_init_ok = False

    def _send(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise MCPClientError("MCP process not started.")
        if method != "initialize":
            self._ensure_mcp_initialized()
        self._request_id += 1
        request = RPCRequest(id=self._request_id, method=method, params=params).to_json()
        self._proc.stdin.write(request + "\n")
        self._proc.stdin.flush()
        skipped: list[str] = []
        out_q = self._stdout_queue
        if out_q is None:
            raise MCPClientError("MCP stdout queue not initialized.")
        deadline = time.monotonic() + float(max(1, self.timeout_s))
        for _ in range(128):
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                skipped_text = "; ".join(skipped[:12])
                raise MCPClientError(
                    f"Timed out waiting for MCP response id {self._request_id}. skipped={skipped_text}"
                )
            try:
                line = out_q.get(timeout=remaining)
            except queue.Empty:
                skipped_text = "; ".join(skipped[:12])
                raise MCPClientError(
                    f"Timed out waiting for MCP response id {self._request_id}. skipped={skipped_text}"
                )
            if line is None:
                stderr = ""
                if self._proc.stderr:
                    stderr = self._proc.stderr.read()
                skipped_text = "; ".join(skipped[:8])
                raise MCPClientError(
                    f"No response from MCP server. skipped={skipped_text} stderr={stderr}"
                )
            line = line.strip()
            if not line:
                continue
            try:
                payload = parse_json_line(line)
            except Exception:  # noqa: BLE001
                skipped.append("non_json_line")
                continue
            response_id = payload.get("id")
            if not _request_id_matches(response_id, self._request_id):
                skipped.append(f"id={response_id}")
                continue
            if "error" in payload and payload["error"]:
                raise MCPClientError(str(payload["error"]))
            return payload["result"]
        skipped_text = "; ".join(skipped[:12])
        raise MCPClientError(
            f"Exceeded response scan limit waiting for id {self._request_id}. skipped={skipped_text}"
        )

    def list_tools(self) -> list[str]:
        result = self._send("tools/list", {})
        return [item["name"] for item in result.get("tools", [])]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._send("tools/call", {"name": name, "arguments": arguments})
