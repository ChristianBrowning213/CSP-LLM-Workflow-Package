"""Compatibility checks for QLIP-style POT files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class PotCompatFailure:
    """One failing POT file with reason."""

    path: Path
    reason: str


@dataclass(frozen=True)
class PotCompatReport:
    """Compatibility check aggregate result."""

    checked: int
    passed: int
    failures: tuple[PotCompatFailure, ...]

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.checked > 0


def parse_pot_like_qlip(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Parse POT numeric rows the same tolerant way as QLIP-like readers."""
    r_vals: list[float] = []
    u_vals: list[float] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                r_val = float(parts[0])
                u_val = float(parts[1])
            except ValueError:
                continue
            r_vals.append(r_val)
            u_vals.append(u_val)
    return np.asarray(r_vals, dtype=np.float64), np.asarray(u_vals, dtype=np.float64)


def check_single_pot(path: Path, *, strict: bool) -> str | None:
    """Return failure reason for one POT file, or None if valid."""
    r_vals, u_vals = parse_pot_like_qlip(path)
    if r_vals.size < 2:
        return "fewer than 2 numeric rows"
    if not np.all(np.isfinite(r_vals)):
        return "non-finite r value"
    if not np.all(np.isfinite(u_vals)):
        return "non-finite U value"

    # Current compatibility target requires strictly increasing r.
    if not np.all(np.diff(r_vals) > 0):
        return "r values are not strictly increasing"

    if strict:
        if float(np.min(r_vals)) <= 0:
            return "strict mode requires r min > 0"
        if np.unique(r_vals).size != r_vals.size:
            return "strict mode requires unique r values"

    return None


def check_pot_root(spp_root: Path, *, strict: bool) -> PotCompatReport:
    """Check all POT files recursively under an SPP root."""
    if not spp_root.is_dir():
        raise ValueError(f"spp_root is not a directory: {spp_root}")

    pot_files = sorted(
        spp_root.rglob("*.POT"),
        key=lambda p: str(p.relative_to(spp_root)).lower(),
    )
    failures: list[PotCompatFailure] = []
    if not pot_files:
        failures.append(PotCompatFailure(path=Path("<none>"), reason="no .POT files found"))
        return PotCompatReport(checked=0, passed=0, failures=tuple(failures))

    for pot_file in pot_files:
        reason = check_single_pot(pot_file, strict=strict)
        if reason is not None:
            failures.append(PotCompatFailure(path=pot_file, reason=reason))

    checked = len(pot_files)
    passed = checked - len(failures)
    return PotCompatReport(checked=checked, passed=passed, failures=tuple(failures))


def render_compat_report(report: PotCompatReport) -> str:
    """Render a concise human-readable compatibility report."""
    lines = [
        f"POT files checked: {report.checked}",
        f"Passed: {report.passed}",
        f"Failed: {report.failed}",
    ]
    if report.failures:
        lines.append("Failures:")
        for failure in report.failures:
            lines.append(f"- {failure.path}: {failure.reason}")
    else:
        lines.append("All POT files passed compatibility checks.")
    return "\n".join(lines)
