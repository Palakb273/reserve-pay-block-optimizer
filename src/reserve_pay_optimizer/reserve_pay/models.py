"""Provider-independent Reserve Pay requests, results, and lifecycle models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from reserve_pay_optimizer.config import SUPPORTED_CURRENCY
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import Currency
from reserve_pay_optimizer.dynamic.models import (
    DynamicReoptimizationDecision,
    DynamicRideSession,
)
from reserve_pay_optimizer.reserve_pay.state import ReserveBlockStatus


def _required(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} cannot be empty")


def _money(value: object, field: str, *, allow_zero: bool = False) -> None:
    if not isinstance(value, Money):
        raise ValueError(f"{field} must be Money")
    if not allow_zero and value.amount_paise <= 0:
        raise ValueError(f"{field} must be positive")


class ReserveProviderName(StrEnum):
    MOCK = "mock"
    RAZORPAY = "razorpay"


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    supports_create: bool
    supports_increase: bool
    supports_partial_debit: bool
    supports_release: bool
    supports_status: bool


@dataclass(frozen=True, slots=True)
class ReserveBlock:
    block_id: str
    provider: ReserveProviderName
    transaction_id: str
    customer_reference: str
    authorized_amount: Money
    remaining_amount: Money
    debited_amount: Money
    released_amount: Money
    status: ReserveBlockStatus
    created_at: datetime
    updated_at: datetime
    provider_reference: str | None = None

    def __post_init__(self) -> None:
        for value, field in (
            (self.block_id, "block_id"),
            (self.transaction_id, "transaction_id"),
            (self.customer_reference, "customer_reference"),
        ):
            _required(value, field)
        _money(self.authorized_amount, "authorized_amount")
        for value, field in (
            (self.remaining_amount, "remaining_amount"),
            (self.debited_amount, "debited_amount"),
            (self.released_amount, "released_amount"),
        ):
            _money(value, field, allow_zero=True)
        if any(
            money.currency is not self.authorized_amount.currency
            for money in (self.remaining_amount, self.debited_amount, self.released_amount)
        ):
            raise ValueError("all ReserveBlock money values must use one currency")
        accounted = (
            self.debited_amount.amount_paise
            + self.released_amount.amount_paise
            + self.remaining_amount.amount_paise
        )
        if accounted != self.authorized_amount.amount_paise:
            raise ValueError(
                "debited + released + remaining must equal authorized amount"
            )
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.status is ReserveBlockStatus.AUTHORIZED and not (
            self.remaining_amount == self.authorized_amount
            and self.debited_amount.amount_paise == 0
            and self.released_amount.amount_paise == 0
        ):
            raise ValueError("AUTHORIZED accounting state is inconsistent")
        if self.status is ReserveBlockStatus.PARTIALLY_DEBITED and not (
            self.debited_amount.amount_paise > 0
            and self.remaining_amount.amount_paise > 0
            and self.released_amount.amount_paise == 0
        ):
            raise ValueError("PARTIALLY_DEBITED accounting state is inconsistent")
        if self.status is ReserveBlockStatus.DEBITED and not (
            self.debited_amount == self.authorized_amount
            and self.remaining_amount.amount_paise == 0
            and self.released_amount.amount_paise == 0
        ):
            raise ValueError("DEBITED accounting state is inconsistent")
        if self.status is ReserveBlockStatus.RELEASED and not (
            self.remaining_amount.amount_paise == 0
            and self.released_amount.amount_paise > 0
        ):
            raise ValueError("RELEASED accounting state is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "provider": self.provider.value,
            "transaction_id": self.transaction_id,
            "customer_reference": self.customer_reference,
            "status": self.status.value,
            "authorized_amount_paise": self.authorized_amount.amount_paise,
            "debited_amount_paise": self.debited_amount.amount_paise,
            "released_amount_paise": self.released_amount.amount_paise,
            "remaining_amount_paise": self.remaining_amount.amount_paise,
            "currency": self.authorized_amount.currency.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "provider_reference": self.provider_reference,
        }


@dataclass(frozen=True, slots=True)
class CreateBlockRequest:
    transaction_id: str
    customer_reference: str
    requested_amount: Money
    idempotency_key: str
    metadata: tuple[tuple[str, str], ...] = ()
    currency: ClassVar[Currency] = SUPPORTED_CURRENCY

    def __post_init__(self) -> None:
        for value, field in (
            (self.transaction_id, "transaction_id"),
            (self.customer_reference, "customer_reference"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _required(value, field)
        _money(self.requested_amount, "requested_amount")
        if not isinstance(self.metadata, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not all(isinstance(value, str) for value in item)
            for item in self.metadata
        ):
            raise ValueError("metadata must be string key/value pairs")

    def idempotency_payload(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "customer_reference": self.customer_reference,
            "requested_amount_paise": self.requested_amount.amount_paise,
            "currency": self.currency.value,
            "metadata": list(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class IncreaseBlockRequest:
    block_id: str
    transaction_id: str
    additional_amount: Money
    idempotency_key: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.block_id, "block_id"),
            (self.transaction_id, "transaction_id"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _required(value, field)
        _money(self.additional_amount, "additional_amount")

    def idempotency_payload(self) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "transaction_id": self.transaction_id,
            "additional_amount_paise": self.additional_amount.amount_paise,
        }


@dataclass(frozen=True, slots=True)
class DebitBlockRequest:
    block_id: str
    transaction_id: str
    amount: Money
    idempotency_key: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.block_id, "block_id"),
            (self.transaction_id, "transaction_id"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _required(value, field)
        _money(self.amount, "amount")

    def idempotency_payload(self) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "transaction_id": self.transaction_id,
            "amount_paise": self.amount.amount_paise,
        }


@dataclass(frozen=True, slots=True)
class ReleaseBlockRequest:
    block_id: str
    transaction_id: str
    amount: Money
    idempotency_key: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.block_id, "block_id"),
            (self.transaction_id, "transaction_id"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _required(value, field)
        _money(self.amount, "amount")

    def idempotency_payload(self) -> dict[str, object]:
        return {
            "block_id": self.block_id,
            "transaction_id": self.transaction_id,
            "amount_paise": self.amount.amount_paise,
        }


@dataclass(frozen=True, slots=True)
class GetBlockStatusRequest:
    block_id: str
    transaction_id: str | None = None

    def __post_init__(self) -> None:
        _required(self.block_id, "block_id")
        if self.transaction_id is not None:
            _required(self.transaction_id, "transaction_id")


@dataclass(frozen=True, slots=True)
class CreateBlockResult:
    block: ReserveBlock
    requested_amount: Money
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return {
            **self.block.to_dict(),
            "requested_amount_paise": self.requested_amount.amount_paise,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class IncreaseBlockResult:
    block: ReserveBlock
    previous_authorized_amount: Money
    additional_authorized_amount: Money
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return {
            **self.block.to_dict(),
            "previous_authorized_amount_paise": self.previous_authorized_amount.amount_paise,
            "additional_authorized_amount_paise": self.additional_authorized_amount.amount_paise,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class DebitBlockResult:
    block: ReserveBlock
    debited_now: Money
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return {
            **self.block.to_dict(),
            "debited_now_paise": self.debited_now.amount_paise,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class ReleaseBlockResult:
    block: ReserveBlock
    released_now: Money
    idempotency_key: str

    def to_dict(self) -> dict[str, object]:
        return {
            **self.block.to_dict(),
            "released_now_paise": self.released_now.amount_paise,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True, slots=True)
class BlockStatusResult:
    block: ReserveBlock

    def to_dict(self) -> dict[str, object]:
        return self.block.to_dict()


class DynamicExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"
    RECONCILIATION_REQUIRED = "reconciliation_required"


@dataclass(frozen=True, slots=True)
class DynamicBlockExecution:
    status: DynamicExecutionStatus
    session: DynamicRideSession
    decision: DynamicReoptimizationDecision
    provider_result: IncreaseBlockResult | None = None
    error: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_status": self.status.value,
            "transaction_id": self.decision.transaction_id,
            "event_id": self.decision.event_id,
            "recommended_target_block_paise": self.decision.recommended_target_block.amount_paise,
            "additional_requested_paise": self.decision.additional_block_required.amount_paise,
            "authorized_block_after_execution_paise": self.session.current_authorized_block.amount_paise,
            "provider_result": (
                self.provider_result.to_dict() if self.provider_result else None
            ),
            "error": self.error,
        }


class SettlementStatus(StrEnum):
    SETTLED = "settled"
    INSUFFICIENT_RESERVED_FUNDS = "insufficient_reserved_funds"


@dataclass(frozen=True, slots=True)
class SettlementResult:
    transaction_id: str
    block_id: str
    authorized_amount: Money
    final_amount: Money
    debited_amount: Money
    released_amount: Money
    shortfall: Money
    status: SettlementStatus
    provider: ReserveProviderName
    final_block: ReserveBlock

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_id": self.transaction_id,
            "block_id": self.block_id,
            "authorized_amount_paise": self.authorized_amount.amount_paise,
            "final_amount_paise": self.final_amount.amount_paise,
            "debited_amount_paise": self.debited_amount.amount_paise,
            "released_amount_paise": self.released_amount.amount_paise,
            "shortfall_paise": self.shortfall.amount_paise,
            "status": self.status.value,
            "provider": self.provider.value,
            "final_block": self.final_block.to_dict(),
        }
