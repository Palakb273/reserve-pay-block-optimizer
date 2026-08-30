"""Complete deterministic offline Reserve Pay provider for tests and demos."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.reserve_pay.errors import (
    InvalidReserveStateError,
    InsufficientReservedFundsError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from reserve_pay_optimizer.reserve_pay.idempotency import IdempotencyRegistry
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
    ReserveBlock,
    ReserveProviderName,
)
from reserve_pay_optimizer.reserve_pay.state import (
    ReserveBlockStatus,
    ensure_transition_allowed,
)

_OPERATIONS = frozenset({"create", "increase", "debit", "release"})


@dataclass(slots=True)
class MockFailureConfig:
    """Opt-in deterministic failures. Normal operation never fails randomly."""

    fail_next_create: bool = False
    fail_next_increase: bool = False
    fail_next_debit: bool = False
    fail_next_release: bool = False
    timeout_next_operation: str | None = None
    transient_failures: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout_next_operation is not None and self.timeout_next_operation not in _OPERATIONS:
            raise ValueError("timeout_next_operation is not a supported operation")
        if any(
            operation not in _OPERATIONS
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for operation, count in self.transient_failures.items()
        ):
            raise ValueError("transient_failures must map supported operations to non-negative counts")


class MockReserveProvider:
    """In-memory provider implementing create/increase/debit/release/status."""

    name = ReserveProviderName.MOCK
    capabilities = ProviderCapabilities(True, True, True, True, True)

    def __init__(self, failure_config: MockFailureConfig | None = None) -> None:
        self.failure_config = failure_config or MockFailureConfig()
        self._blocks: dict[str, ReserveBlock] = {}
        self._idempotency = IdempotencyRegistry()
        self._block_counter = 0
        self._clock_tick = 0
        self.operation_attempts: list[tuple[str, str]] = []

    def _next_time(self) -> datetime:
        value = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=self._clock_tick)
        self._clock_tick += 1
        return value

    def _inject_failure(self, operation: str, idempotency_key: str) -> None:
        self.operation_attempts.append((operation, idempotency_key))
        if self.failure_config.timeout_next_operation == operation:
            self.failure_config.timeout_next_operation = None
            raise ProviderTimeoutError(
                "The mock provider timed out before confirming execution.",
                safe_metadata={"provider": self.name.value, "operation": operation},
            )
        transient = self.failure_config.transient_failures.get(operation, 0)
        if transient > 0:
            self.failure_config.transient_failures[operation] = transient - 1
            raise ProviderUnavailableError(
                "The mock provider is temporarily unavailable.",
                safe_metadata={"provider": self.name.value, "operation": operation},
            )
        flag = f"fail_next_{operation}"
        if getattr(self.failure_config, flag):
            setattr(self.failure_config, flag, False)
            raise ProviderRejectedError(
                "The mock provider deterministically rejected the operation.",
                safe_metadata={"provider": self.name.value, "operation": operation},
            )

    def _block_for(self, block_id: str, transaction_id: str | None = None) -> ReserveBlock:
        block = self._blocks.get(block_id)
        if block is None:
            raise InvalidReserveStateError(
                "Reserve block was not found.", safe_metadata={"block_id": block_id}
            )
        if transaction_id is not None and block.transaction_id != transaction_id:
            raise InvalidReserveStateError(
                "Reserve block does not belong to the supplied transaction.",
                safe_metadata={"block_id": block_id},
            )
        return block

    def create_block(self, request: CreateBlockRequest) -> CreateBlockResult:
        def action() -> CreateBlockResult:
            self._inject_failure("create", request.idempotency_key)
            self._block_counter += 1
            block_id = f"mock_blk_{self._block_counter:06d}"
            created_at = self._next_time()
            zero = Money.from_non_negative_paise(0)
            block = ReserveBlock(
                block_id=block_id,
                provider=self.name,
                transaction_id=request.transaction_id,
                customer_reference=request.customer_reference,
                authorized_amount=request.requested_amount,
                remaining_amount=request.requested_amount,
                debited_amount=zero,
                released_amount=zero,
                status=ReserveBlockStatus.AUTHORIZED,
                created_at=created_at,
                updated_at=created_at,
                provider_reference=block_id,
            )
            self._blocks[block_id] = block
            return CreateBlockResult(block, request.requested_amount, request.idempotency_key)

        return self._idempotency.execute(
            "create", request.idempotency_key, request.idempotency_payload(), action
        )

    def increase_block(self, request: IncreaseBlockRequest) -> IncreaseBlockResult:
        def action() -> IncreaseBlockResult:
            self._inject_failure("increase", request.idempotency_key)
            block = self._block_for(request.block_id, request.transaction_id)
            if block.status not in {
                ReserveBlockStatus.AUTHORIZED,
                ReserveBlockStatus.PARTIALLY_DEBITED,
            }:
                raise InvalidReserveStateError(
                    "Only an active authorized block can be increased.",
                    safe_metadata={"status": block.status.value},
                )
            new_status = block.status
            ensure_transition_allowed(block.status, new_status)
            updated = replace(
                block,
                authorized_amount=Money(
                    block.authorized_amount.amount_paise
                    + request.additional_amount.amount_paise
                ),
                remaining_amount=Money(
                    block.remaining_amount.amount_paise
                    + request.additional_amount.amount_paise
                ),
                updated_at=self._next_time(),
            )
            self._blocks[block.block_id] = updated
            return IncreaseBlockResult(
                updated,
                block.authorized_amount,
                request.additional_amount,
                request.idempotency_key,
            )

        return self._idempotency.execute(
            "increase", request.idempotency_key, request.idempotency_payload(), action
        )

    def debit_block(self, request: DebitBlockRequest) -> DebitBlockResult:
        def action() -> DebitBlockResult:
            self._inject_failure("debit", request.idempotency_key)
            block = self._block_for(request.block_id, request.transaction_id)
            if block.status not in {
                ReserveBlockStatus.AUTHORIZED,
                ReserveBlockStatus.PARTIALLY_DEBITED,
            }:
                raise InvalidReserveStateError(
                    "This reserve block cannot be debited in its current state.",
                    safe_metadata={"status": block.status.value},
                )
            if request.amount.amount_paise > block.remaining_amount.amount_paise:
                raise InsufficientReservedFundsError(
                    requested_paise=request.amount.amount_paise,
                    available_paise=block.remaining_amount.amount_paise,
                )
            remaining = block.remaining_amount.amount_paise - request.amount.amount_paise
            target = (
                ReserveBlockStatus.DEBITED
                if remaining == 0
                else ReserveBlockStatus.PARTIALLY_DEBITED
            )
            ensure_transition_allowed(block.status, target)
            updated = replace(
                block,
                remaining_amount=Money.from_non_negative_paise(remaining),
                debited_amount=Money.from_non_negative_paise(
                    block.debited_amount.amount_paise + request.amount.amount_paise
                ),
                status=target,
                updated_at=self._next_time(),
            )
            self._blocks[block.block_id] = updated
            return DebitBlockResult(updated, request.amount, request.idempotency_key)

        return self._idempotency.execute(
            "debit", request.idempotency_key, request.idempotency_payload(), action
        )

    def release_block(self, request: ReleaseBlockRequest) -> ReleaseBlockResult:
        def action() -> ReleaseBlockResult:
            self._inject_failure("release", request.idempotency_key)
            block = self._block_for(request.block_id, request.transaction_id)
            if block.status not in {
                ReserveBlockStatus.AUTHORIZED,
                ReserveBlockStatus.PARTIALLY_DEBITED,
            }:
                raise InvalidReserveStateError(
                    "This reserve block has no releasable authorization.",
                    safe_metadata={"status": block.status.value},
                )
            if request.amount.amount_paise != block.remaining_amount.amount_paise:
                raise InvalidReserveStateError(
                    "Phase 10 releases the full remaining authorization only.",
                    safe_metadata={
                        "requested_amount_paise": request.amount.amount_paise,
                        "remaining_amount_paise": block.remaining_amount.amount_paise,
                    },
                )
            ensure_transition_allowed(block.status, ReserveBlockStatus.RELEASED)
            updated = replace(
                block,
                remaining_amount=Money.from_non_negative_paise(0),
                released_amount=Money.from_non_negative_paise(
                    block.released_amount.amount_paise + request.amount.amount_paise
                ),
                status=ReserveBlockStatus.RELEASED,
                updated_at=self._next_time(),
            )
            self._blocks[block.block_id] = updated
            return ReleaseBlockResult(updated, request.amount, request.idempotency_key)

        return self._idempotency.execute(
            "release", request.idempotency_key, request.idempotency_payload(), action
        )

    def get_block_status(self, request: GetBlockStatusRequest) -> BlockStatusResult:
        return BlockStatusResult(self._block_for(request.block_id, request.transaction_id))
