"""Explainability consistency and rendering errors."""


class ExplanationConsistencyError(ValueError):
    """Structured evidence does not match its authoritative decision sources."""


class InvalidGeneratedExplanation(ValueError):
    """Optional generated text failed its bounded response contract."""
