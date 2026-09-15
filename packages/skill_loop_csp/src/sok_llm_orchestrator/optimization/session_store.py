from __future__ import annotations

import json
from pathlib import Path

from sok_llm_orchestrator.optimization.session_schema import OptimizationSession
from sok_llm_orchestrator.orchestrator.logging import canonical_json


class OptimizationSessionStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = self.workspace / "optimization" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def session_dir(self, session_id: str) -> Path:
        return self.root / session_id

    def session_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def save(self, session: OptimizationSession) -> Path:
        sdir = self.session_dir(session.session_id)
        sdir.mkdir(parents=True, exist_ok=True)
        path = self.session_path(session.session_id)
        payload = session.to_dict()
        path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        it_dir = sdir / "iterations"
        it_dir.mkdir(parents=True, exist_ok=True)
        for idx, item in enumerate(session.iteration_history):
            item_path = it_dir / f"{idx:03d}.json"
            item_path.write_text(canonical_json(item) + "\n", encoding="utf-8")
        return path

    def load(self, session_id: str) -> OptimizationSession:
        path = self.session_path(session_id)
        payload = path.read_text(encoding="utf-8")
        return OptimizationSession.from_dict(json.loads(payload))
