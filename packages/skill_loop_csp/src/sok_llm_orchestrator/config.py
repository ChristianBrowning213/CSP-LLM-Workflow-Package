from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _split_paths(raw: str | None) -> list[Path]:
    if not raw:
        return []
    items = [item.strip() for item in raw.split(os.pathsep) if item.strip()]
    return [Path(item).resolve() for item in items]


@dataclass(slots=True)
class Settings:
    llm_base_url: str = "http://localhost:1234/v1"
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_timeout_s: int = 60
    workspace_root: Path = field(default_factory=lambda: Path(".sokllm_workspace").resolve())

    crystaldb_mcp_cmd: str = "python -m crystal_db.mcp.server"
    spp_mcp_cmd: str = "python -m spp_maker_mcp.server"
    qlip_mcp_cmd: str = "python -m qlip.mcp.server"
    crystaldb_mcp_cwd: str | None = None
    spp_mcp_cwd: str | None = None
    qlip_mcp_cwd: str | None = None
    qlip_allow_repo_shim: bool = False

    allowed_read_roots: list[Path] = field(default_factory=list)
    allowed_write_roots: list[Path] = field(default_factory=list)
    qlip_allowed_path_roots: list[Path] = field(default_factory=list)

    max_cif_count: int = 500
    max_runtime_seconds: int = 120
    max_output_bytes: int = 100_000_000

    crystaldb_policy_mode: str = "safe"

    optimization_max_iterations: int = 6
    optimization_max_solver_calls: int = 20
    optimization_max_retrieval_calls: int = 20
    optimization_max_failed_iterations: int = 3
    optimization_stagnation_window: int = 3
    optimization_exploration_rate: float = 0.25
    optimization_allow_midloop_clarification: bool = True
    optimization_selection_metric_view: str = "objective_total"
    optimization_max_wall_clock_s: int | None = None
    optimization_action_family_limits: dict[str, int] = field(default_factory=dict)
    optimization_action_allowlist: list[str] = field(default_factory=list)

    @classmethod
    def from_sources(cls, yaml_path: Path | None = None) -> "Settings":
        yaml_data: dict[str, Any] = {}
        if yaml_path and yaml_path.exists():
            yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

        def pick(name: str, default: Any) -> Any:
            env_name = name.upper()
            if env_name in os.environ:
                return os.environ[env_name]
            return yaml_data.get(name, default)

        workspace_root = Path(pick("workspace_root", ".sokllm_workspace")).resolve()
        read_roots = _split_paths(os.environ.get("ALLOWED_READ_ROOTS"))
        write_roots = _split_paths(os.environ.get("ALLOWED_WRITE_ROOTS"))
        if not read_roots:
            data = yaml_data.get("allowed_read_roots", [])
            read_roots = [Path(item).resolve() for item in data] if data else [workspace_root]
        if not write_roots:
            data = yaml_data.get("allowed_write_roots", [])
            write_roots = [Path(item).resolve() for item in data] if data else [workspace_root]
        qlip_roots = _split_paths(os.environ.get("QLIP_ALLOWED_PATH_ROOTS"))
        if not qlip_roots:
            data = yaml_data.get("qlip_allowed_path_roots", [])
            qlip_roots = [Path(item).resolve() for item in data] if data else []
        max_wall_clock_raw = pick("optimization_max_wall_clock_s", None)
        max_wall_clock: int | None
        if max_wall_clock_raw in (None, "", "null"):
            max_wall_clock = None
        else:
            max_wall_clock = int(max_wall_clock_raw)

        return cls(
            llm_base_url=pick("llm_base_url", "http://localhost:1234/v1"),
            llm_api_key=pick("llm_api_key", None),
            llm_model=pick("llm_model", None),
            llm_timeout_s=int(pick("llm_timeout_s", 60)),
            workspace_root=workspace_root,
            crystaldb_mcp_cmd=pick("crystaldb_mcp_cmd", "python -m crystal_db.mcp.server"),
            spp_mcp_cmd=pick("spp_mcp_cmd", "python -m spp_maker_mcp.server"),
            qlip_mcp_cmd=pick("qlip_mcp_cmd", "python -m qlip.mcp.server"),
            crystaldb_mcp_cwd=pick("crystaldb_mcp_cwd", None),
            spp_mcp_cwd=pick("spp_mcp_cwd", None),
            qlip_mcp_cwd=pick("qlip_mcp_cwd", None),
            qlip_allow_repo_shim=str(pick("qlip_allow_repo_shim", "false")).strip().lower()
            in {"1", "true", "yes", "y", "on"},
            allowed_read_roots=read_roots,
            allowed_write_roots=write_roots,
            qlip_allowed_path_roots=qlip_roots,
            max_cif_count=int(pick("max_cif_count", 500)),
            max_runtime_seconds=int(pick("max_runtime_seconds", 120)),
            max_output_bytes=int(pick("max_output_bytes", 100_000_000)),
            crystaldb_policy_mode=str(pick("crystaldb_policy_mode", "safe")),
            optimization_max_iterations=int(pick("optimization_max_iterations", 6)),
            optimization_max_solver_calls=int(pick("optimization_max_solver_calls", 20)),
            optimization_max_retrieval_calls=int(pick("optimization_max_retrieval_calls", 20)),
            optimization_max_failed_iterations=int(pick("optimization_max_failed_iterations", 3)),
            optimization_stagnation_window=int(pick("optimization_stagnation_window", 3)),
            optimization_exploration_rate=float(pick("optimization_exploration_rate", 0.25)),
            optimization_allow_midloop_clarification=str(
                pick("optimization_allow_midloop_clarification", "true")
            ).strip().lower()
            in {"1", "true", "yes", "y", "on"},
            optimization_selection_metric_view=str(
                pick("optimization_selection_metric_view", "objective_total")
            ).strip().lower(),
            optimization_max_wall_clock_s=max_wall_clock,
            optimization_action_family_limits={
                str(k): int(v) for k, v in (yaml_data.get("optimization_action_family_limits", {}) or {}).items()
            },
            optimization_action_allowlist=[
                str(item).strip()
                for item in (yaml_data.get("optimization_action_allowlist", []) or [])
                if str(item).strip()
            ],
        )

    def validate_llm(self) -> None:
        if not self.llm_api_key:
            raise ValueError("LLM_API_KEY is required.")
        if not self.llm_model:
            raise ValueError("LLM_MODEL is required.")
