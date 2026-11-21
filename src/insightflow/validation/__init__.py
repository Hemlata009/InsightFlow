"""InsightFlow validation stage: schema + business rules, generated from the rule book."""

from .validator import ValidationResult, build_schema, validate

__all__ = ["ValidationResult", "build_schema", "validate"]
