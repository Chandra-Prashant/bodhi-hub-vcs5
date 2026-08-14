"""Phase 4 — validation and confidence scoring. Pure rules, no model."""

from app.validation.rules import RULES, Flag, Rule, Severity, rule  # noqa: F401
from app.validation.validator import (  # noqa: F401
    ReviewItem,
    ValidationResult,
    validate,
    validate_extraction,
)
