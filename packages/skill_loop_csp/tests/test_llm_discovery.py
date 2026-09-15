from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sok_llm_orchestrator.llm.discovery import discover_model_id, smoke_chat_api_v1


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/models":
            body = {
                "models": [
                    {"type": "llm", "key": "model-loaded", "loaded_instances": [{"id": "model-loaded"}]},
                    {"type": "embedding", "key": "emb-1", "loaded_instances": []},
                ]
            }
        elif self.path == "/v1/models":
            body = {"data": [{"id": "model-openai"}], "object": "list"}
        else:
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/v1/chat":
            self.send_response(404)
            self.end_headers()
            return
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        payload = json.dumps({"output": [{"type": "message", "content": "ok"}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return


def test_discover_model_and_smoke_chat() -> None:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        model = discover_model_id(base)
        assert model == "model-loaded"
        ok, detail = smoke_chat_api_v1(base, model="model-loaded")
        assert ok is True
        assert detail == "ok"
    finally:
        server.shutdown()
        server.server_close()
