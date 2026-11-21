"""InsightFlow pipeline: runs all Phase 1 stages in order and returns a structured result."""

from .phase1 import describe, run_phase1

__all__ = ["describe", "run_phase1"]
