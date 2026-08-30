"""Razorpay boundary with no fabricated Reserve Pay HTTP mapping."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Mapping, Protocol

from reserve_pay_optimizer.reserve_pay.errors import (
    ProviderConfigurationError,
    UnsupportedProviderOperation,
)
from reserve_pay_optimizer.reserve_pay.models import (
    BlockStatusResult,
    CreateBlockRequest,
    CreateBlockResult,
    DebitBlockRequest,
    DebitBlockResult,
    GetBlockStatusRequest,
    IncreaseBlockRequest,
    IncreaseBlockResult,
    ProviderCapabilities,
    ReleaseBlockRequest,
    ReleaseBlockResult,
    ReserveProviderName,
)


class ReservePayTransport(Protocol):
    """Injectable transport reserved for a verified provider mapping."""

    def send(
        self,
        *,
        operation: str,
        payload: Mapping[str, object],
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class RazorpayProviderConfig:
    key_id: str = field(repr=False)
    key_secret: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, str) or not self.key_id.strip():
            raise ProviderConfigurationError("RAZORPAY_KEY_ID is required.")
        if not isinstance(self.key_secret, str) or not self.key_secret.strip():
            raise ProviderConfigurationError("RAZORPAY_KEY_SECRET is required.")

    @classmethod
    def from_environment(cls) -> "RazorpayProviderConfig":
        return cls(
            key_id=os.environ.get("RAZORPAY_KEY_ID", ""),
            key_secret=os.environ.get("RAZORPAY_KEY_SECRET", ""),
        )

    def to_safe_dict(self) -> dict[str, object]:
        return {"credentials_configured": True}


class RazorpayProvider:
    """Common provider contract pending approved Reserve Pay wire documentation.

    Public product documentation was verified on 2026-08-30, but a complete
    endpoint, request, response, status, increase, idempotency, and error schema
    was not available to this implementation. Every operation therefore fails
    explicitly instead of guessing a network contract.
    """

    name = ReserveProviderName.RAZORPAY
    capabilities = ProviderCapabilities(False, False, False, False, False)

    def __init__(
        self,
        config: RazorpayProviderConfig,
        transport: ReservePayTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    def _unsupported(self, operation: str) -> None:
        raise UnsupportedProviderOperation(
            "Razorpay Reserve Pay network mapping is intentionally disabled until "
            "the endpoint, authentication, schemas, status semantics, idempotency, "
            "and errors are verified from approved documentation.",
            safe_metadata={"provider": self.name.value, "operation": operation},
        )

    def create_block(self, request: CreateBlockRequest) -> CreateBlockResult:
        self._unsupported("create")

    def increase_block(self, request: IncreaseBlockRequest) -> IncreaseBlockResult:
        self._unsupported("increase")

    def debit_block(self, request: DebitBlockRequest) -> DebitBlockResult:
        self._unsupported("debit")

    def release_block(self, request: ReleaseBlockRequest) -> ReleaseBlockResult:
        self._unsupported("release")

    def get_block_status(self, request: GetBlockStatusRequest) -> BlockStatusResult:
        self._unsupported("status")
