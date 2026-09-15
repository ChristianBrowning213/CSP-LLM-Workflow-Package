"""Slurm configuration, rendering, submission, and normalized status."""

from sca.dft.slurm.render import query_status, render_slurm_script, submit_calculation
from sca.dft.slurm.schema import SlurmConfig

__all__ = ["SlurmConfig", "query_status", "render_slurm_script", "submit_calculation"]

