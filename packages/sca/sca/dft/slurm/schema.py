"""Typed Slurm configuration with no user-specific defaults."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SlurmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    partition: str
    walltime: str
    nodes: int = 1
    ntasks: int
    cpus_per_task: int = 1
    memory: str
    account: str | None = None
    modules: list[str] = Field(default_factory=list)
    executable: str
    extra_scheduler_options: dict[str, str | bool] = Field(default_factory=dict)

