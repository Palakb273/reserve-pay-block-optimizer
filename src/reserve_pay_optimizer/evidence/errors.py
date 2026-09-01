"""Fail-closed errors for authoritative evidence generation."""


class EvidenceValidationError(ValueError):
    """Raised when authoritative evidence is incomplete or internally inconsistent."""

