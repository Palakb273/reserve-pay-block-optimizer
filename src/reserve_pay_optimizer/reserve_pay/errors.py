"""Structured, credential-safe Reserve Pay execution errors."""

from __future__ import annotations

from typing import Mapping


class ReservePayError(Exception):
    """Base exception exposed by the provider-neutral execution boundary."""

    code = "reserve_pay_error"
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        safe_metadata: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.safe_metadata = dict(safe_metadata or {})

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"code": self.code, "message": self.message}
        if self.safe_metadata:
            value["metadata"] = dict(self.safe_metadata)
        return value


class ProviderUnavailableError(ReservePayError):
    code = "provider_unavailable"
    retryable = True


class ProviderTimeoutError(ReservePayError):
    code = "provider_timeout"
    retryable = True


class ProviderRejectedError(ReservePayError):
    code = "provider_rejected"


class ProviderValidationError(ReservePayError):
    code = "provider_validation_error"


class InvalidReserveStateError(ReservePayError):
    code = "invalid_reserve_state"


class InsufficientReservedFundsError(ReservePayError):
    code = "insufficient_reserved_funds"

    def __init__(self, *, requested_paise: int, available_paise: int) -> None:
        super().__init__(
            "Requested debit exceeds the remaining authorized reserve.",
            safe_metadata={
                "requested_amount_paise": requested_paise,
                "available_amount_paise": available_paise,
                "shortfall_paise": max(requested_paise - available_paise, 0),
            },
        )


class IdempotencyConflictError(ReservePayError):
    code = "idempotency_conflict"


class ProviderConfigurationError(ReservePayError):
    code = "provider_configuration_error"


class UnsupportedProviderOperation(ReservePayError):
    code = "unsupported_provider_operation"


class ProviderResponseError(ReservePayError):
    code = "invalid_provider_response"
