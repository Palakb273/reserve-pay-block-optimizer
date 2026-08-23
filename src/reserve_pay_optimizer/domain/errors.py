"""Structured domain validation errors."""

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    field: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "field": self.field,
            "code": self.code,
            "message": self.message,
        }

    def for_field(self, field: str) -> "ValidationIssue":
        return ValidationIssue(field=field, code=self.code, message=self.message)


class DomainValidationError(ValueError):
    """One or more understandable violations of a domain contract."""

    def __init__(self, issues: Iterable[ValidationIssue]):
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("DomainValidationError requires at least one issue")
        super().__init__("; ".join(issue.message for issue in self.issues))

    def to_dict(self) -> dict[str, object]:
        return {
            "validation_status": "invalid",
            "errors": [issue.to_dict() for issue in self.issues],
        }

