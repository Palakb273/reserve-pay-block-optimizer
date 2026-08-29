"""Structured errors for dynamic ride state transitions."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DynamicSessionError(ValueError):
    code: str
    message: str
    field: str | None = None

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "status": "error",
            "error_type": "dynamic_session_error",
            "code": self.code,
            "message": self.message,
        }
        if self.field is not None:
            value["field"] = self.field
        return value
