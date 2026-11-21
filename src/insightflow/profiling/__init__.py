"""InsightFlow profiling stage: a health check of the raw data before any change."""

from .patterns import classify
from .profiler import profile, summary_text, write_report

__all__ = ["classify", "profile", "summary_text", "write_report"]
