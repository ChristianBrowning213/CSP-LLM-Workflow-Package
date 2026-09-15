from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from sok_llm_orchestrator.llm.client import LLMClient


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        _ = self.rfile.read(length)
        body = {
            "id": "cmpl-1",
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        }
        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return


def test_llm_client_chat_stub() -> None:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = LLMClient(
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="k",
            model="m",
        )
        response = client.chat([{"role": "user", "content": "hi"}])
        assert response["choices"][0]["message"]["content"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
