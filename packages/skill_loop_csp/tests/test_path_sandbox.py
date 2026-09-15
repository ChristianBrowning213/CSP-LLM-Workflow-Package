from __future__ import annotations

from pathlib import Path

import pytest

from sok_llm_orchestrator.safety.path_sandbox import PathSandboxError, validate_paths_in_args


def test_path_escape_rejected(workdir: Path) -> None:
    workspace = workdir / "workspace"
    workspace.mkdir()
    bad_path = workspace / ".." / "escape"
    with pytest.raises(PathSandboxError, match="path_not_allowed"):
        validate_paths_in_args(
            args={"cif_dir": str(bad_path)},
            read_keys=["cif_dir"],
            write_keys=[],
            allowed_read_roots=[workspace],
            allowed_write_roots=[workspace],
        )
