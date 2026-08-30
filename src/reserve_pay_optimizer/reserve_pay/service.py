"""High-level Reserve Pay execution, retry, dynamic confirmation, and settlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import time
from typing import Callable, TypeVar

from reserve_pay_optimizer.domain.mobility import RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.dynamic.errors import DynamicSessionError
from reserve_pay_optimizer.dynamic.models import (
    DynamicReoptimizationDecision,
    DynamicRideSession,
)
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.reserve_pay.audit import (
    ReservePayAuditEvent,
    ReservePayAuditEventType,
)
from reserve_pay_optimizer.reserve_pay.errors import (
    ProviderResponseError,
    ReservePayError,
)
from reserve_pay_optimizer.reserve_pay.idempotency import IdempotencyRegistry
from reserve_pay_optimizer.reserve_pay.models import (
    BlockStatusResult,
    CreateBlockRequest,
    CreateBlockResult,
    DebitBlockRequest,
    DebitBlockResult,
    DynamicBlockExecution,
    DynamicExecutionStatus,
    GetBlockStatusRequest,
    IncreaseBlockRequest,
    IncreaseBlockResult,
    ReleaseBlockRequest,
    ReleaseBlockResult,
    SettlementResult,
    SettlementStatus,
)
from reserve_pay_optimizer.reserve_pay.provider import ReservePayProvider

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryConfig:
    max_attempts: int = 3
    delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or self.max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        if (
            isinstance(self.delay_seconds, bool)
            or not isinstance(self.delay_seconds, (int, float))
            or self.delay_seconds < 0
        ):
            raise ValueError("delay_seconds must be non-negative")


def _key_fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:12]


class ReservePayService:
    """Execute already-computed amounts; never predicts or optimizes them."""

    def __init__(
        self,
        provider: ReservePayProvider,
        *,
        dynamic_service: DynamicRideService | None = None,
        retry_config: RetryConfig | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.dynamic_service = dynamic_service
        self.retry_config = retry_config or RetryConfig()
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(UTC))
        self.audit_events: list[ReservePayAuditEvent] = []
        self._settlement_idempotency = IdempotencyRegistry()

    def _audit(
        self,
        event_type: ReservePayAuditEventType,
        *,
        transaction_id: str,
        block_id: str | None = None,
        idempotency_key: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.audit_events.append(
            ReservePayAuditEvent(
                event_type=event_type,
                recorded_at=self.clock(),
                transaction_id=transaction_id,
                block_id=block_id,
                provider=self.provider.name.value,
                operation_key_fingerprint=(
                    _key_fingerprint(idempotency_key) if idempotency_key else None
                ),
                error_code=error_code,
            )
        )

    def _invoke(self, action: Callable[[], T]) -> T:
        last_error: ReservePayError | None = None
        for attempt in range(1, self.retry_config.max_attempts + 1):
            try:
                return action()
            except ReservePayError as exc:
                last_error = exc
                if not exc.retryable or attempt == self.retry_config.max_attempts:
                    raise
                self.sleeper(self.retry_config.delay_seconds)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _validate_result_identity(
        request_transaction_id: str,
        result_transaction_id: str,
    ) -> None:
        if result_transaction_id != request_transaction_id:
            raise ProviderResponseError(
                "Provider result changed the transaction identity.",
                safe_metadata={"expected_transaction_id": request_transaction_id},
            )

    def create_block(self, request: CreateBlockRequest) -> CreateBlockResult:
        self._audit(
            ReservePayAuditEventType.BLOCK_CREATE_REQUESTED,
            transaction_id=request.transaction_id,
            idempotency_key=request.idempotency_key,
        )
        try:
            result = self._invoke(lambda: self.provider.create_block(request))
            self._validate_result_identity(request.transaction_id, result.block.transaction_id)
        except ReservePayError as exc:
            self._audit(
                ReservePayAuditEventType.BLOCK_AUTHORIZATION_FAILED,
                transaction_id=request.transaction_id,
                idempotency_key=request.idempotency_key,
                error_code=exc.code,
            )
            raise
        self._audit(
            ReservePayAuditEventType.BLOCK_AUTHORIZED,
            transaction_id=request.transaction_id,
            block_id=result.block.block_id,
            idempotency_key=request.idempotency_key,
        )
        return result

    def authorize_initial_block(
        self,
        decision: ReserveDecision,
        *,
        customer_reference: str,
        idempotency_key: str,
        metadata: tuple[tuple[str, str], ...] = (),
    ) -> CreateBlockResult:
        return self.create_block(
            CreateBlockRequest(
                transaction_id=decision.transaction_id,
                customer_reference=customer_reference,
                requested_amount=decision.block_amount,
                idempotency_key=idempotency_key,
                metadata=metadata,
            )
        )

    def increase_block(self, request: IncreaseBlockRequest) -> IncreaseBlockResult:
        self._audit(
            ReservePayAuditEventType.BLOCK_INCREASE_REQUESTED,
            transaction_id=request.transaction_id,
            block_id=request.block_id,
            idempotency_key=request.idempotency_key,
        )
        try:
            result = self._invoke(lambda: self.provider.increase_block(request))
            self._validate_result_identity(request.transaction_id, result.block.transaction_id)
        except ReservePayError as exc:
            self._audit(
                ReservePayAuditEventType.BLOCK_INCREASE_FAILED,
                transaction_id=request.transaction_id,
                block_id=request.block_id,
                idempotency_key=request.idempotency_key,
                error_code=exc.code,
            )
            raise
        self._audit(
            ReservePayAuditEventType.BLOCK_INCREASE_AUTHORIZED,
            transaction_id=request.transaction_id,
            block_id=request.block_id,
            idempotency_key=request.idempotency_key,
        )
        return result

    def debit_block(self, request: DebitBlockRequest) -> DebitBlockResult:
        self._audit(
            ReservePayAuditEventType.BLOCK_DEBIT_REQUESTED,
            transaction_id=request.transaction_id,
            block_id=request.block_id,
            idempotency_key=request.idempotency_key,
        )
        try:
            result = self._invoke(lambda: self.provider.debit_block(request))
            self._validate_result_identity(request.transaction_id, result.block.transaction_id)
        except ReservePayError as exc:
            self._audit(
                ReservePayAuditEventType.BLOCK_DEBIT_FAILED,
                transaction_id=request.transaction_id,
                block_id=request.block_id,
                idempotency_key=request.idempotency_key,
                error_code=exc.code,
            )
            raise
        self._audit(
            ReservePayAuditEventType.BLOCK_DEBITED,
            transaction_id=request.transaction_id,
            block_id=request.block_id,
            idempotency_key=request.idempotency_key,
        )
        return result

    def release_block(self, request: ReleaseBlockRequest) -> ReleaseBlockResult:
        self._audit(
            ReservePayAuditEventType.BLOCK_RELEASE_REQUESTED,
            transaction_id=request.transaction_id,
            block_id=request.block_id,
            idempotency_key=request.idempotency_key,
        )
        try:
            result = self._invoke(lambda: self.provider.release_block(request))
            self._validate_result_identity(request.transaction_id, result.block.transaction_id)
        except ReservePayError as exc:
            self._audit(
                ReservePayAuditEventType.BLOCK_RELEASE_FAILED,
                transaction_id=request.transaction_id,
                block_id=request.block_id,
                idempotency_key=request.idempotency_key,
                error_code=exc.code,
            )
            raise
        self._audit(
            ReservePayAuditEventType.BLOCK_RELEASED,
            transaction_id=request.transaction_id,
            block_id=request.block_id,
            idempotency_key=request.idempotency_key,
        )
        return result

    def get_block_status(self, request: GetBlockStatusRequest) -> BlockStatusResult:
        result = self._invoke(lambda: self.provider.get_block_status(request))
        if request.transaction_id is not None:
            self._validate_result_identity(request.transaction_id, result.block.transaction_id)
        self._audit(
            ReservePayAuditEventType.BLOCK_STATUS_REFRESHED,
            transaction_id=result.block.transaction_id,
            block_id=result.block.block_id,
        )
        return result

    def request_additional_block(
        self,
        session: DynamicRideSession,
        decision: DynamicReoptimizationDecision,
        *,
        block_id: str,
        idempotency_key: str,
    ) -> DynamicBlockExecution:
        if decision.additional_block_required.amount_paise == 0:
            return DynamicBlockExecution(
                DynamicExecutionStatus.NOT_REQUIRED, session, decision
            )
        request = IncreaseBlockRequest(
            block_id=block_id,
            transaction_id=decision.transaction_id,
            additional_amount=decision.additional_block_required,
            idempotency_key=idempotency_key,
        )
        try:
            result = self.increase_block(request)
        except ReservePayError as exc:
            return DynamicBlockExecution(
                DynamicExecutionStatus.FAILED,
                session,
                decision,
                error=exc.to_dict(),
            )
        return self.confirm_dynamic_increase(session, decision, result)

    def confirm_dynamic_increase(
        self,
        session: DynamicRideSession,
        decision: DynamicReoptimizationDecision,
        result: IncreaseBlockResult,
    ) -> DynamicBlockExecution:
        """Apply a normalized success through Phase-8 stale/version checks."""

        expected_total = decision.recommended_target_block.amount_paise
        mismatch = (
            result.block.transaction_id != decision.transaction_id
            or result.block.authorized_amount.amount_paise != expected_total
        )
        if mismatch:
            error = ProviderResponseError(
                "Provider success does not match the dynamic decision target.",
                safe_metadata={
                    "expected_transaction_id": decision.transaction_id,
                    "expected_target_paise": expected_total,
                    "provider_authorized_paise": result.block.authorized_amount.amount_paise,
                },
            )
            return self._reconciliation(session, decision, result, error.to_dict())
        if self.dynamic_service is None:
            error = ProviderResponseError(
                "DynamicRideService is required to confirm a dynamic increase."
            )
            return self._reconciliation(session, decision, result, error.to_dict())
        try:
            confirmed = self.dynamic_service.confirm_block_authorized(
                session,
                decision,
                result.block.authorized_amount,
            )
        except DynamicSessionError as exc:
            return self._reconciliation(
                session,
                decision,
                result,
                {"code": exc.code, "message": exc.message, "field": exc.field},
            )
        return DynamicBlockExecution(
            DynamicExecutionStatus.SUCCEEDED,
            confirmed,
            decision,
            provider_result=result,
        )

    def _reconciliation(
        self,
        session: DynamicRideSession,
        decision: DynamicReoptimizationDecision,
        result: IncreaseBlockResult,
        error: dict[str, object],
    ) -> DynamicBlockExecution:
        self._audit(
            ReservePayAuditEventType.RECONCILIATION_REQUIRED,
            transaction_id=decision.transaction_id,
            block_id=result.block.block_id,
            idempotency_key=result.idempotency_key,
            error_code=str(error.get("code", "reconciliation_required")),
        )
        return DynamicBlockExecution(
            DynamicExecutionStatus.RECONCILIATION_REQUIRED,
            session,
            decision,
            provider_result=result,
            error=error,
        )

    def settle_completed_transaction(
        self,
        outcome: RideTransactionOutcome,
        *,
        block_id: str,
        idempotency_key: str,
    ) -> SettlementResult:
        """Debit the known final fare, then release the full unused remainder."""

        def action() -> SettlementResult:
            status = self.get_block_status(
                GetBlockStatusRequest(block_id, outcome.transaction_id)
            ).block
            available = status.remaining_amount.amount_paise
            actual = outcome.actual_amount.amount_paise
            if actual > available:
                return SettlementResult(
                    transaction_id=outcome.transaction_id,
                    block_id=block_id,
                    authorized_amount=status.authorized_amount,
                    final_amount=outcome.actual_amount,
                    debited_amount=status.debited_amount,
                    released_amount=status.released_amount,
                    shortfall=Money.from_non_negative_paise(actual - available),
                    status=SettlementStatus.INSUFFICIENT_RESERVED_FUNDS,
                    provider=status.provider,
                    final_block=status,
                )
            debit = self.debit_block(
                DebitBlockRequest(
                    block_id=block_id,
                    transaction_id=outcome.transaction_id,
                    amount=outcome.actual_amount,
                    idempotency_key=f"{idempotency_key}:debit",
                )
            ).block
            final_block = debit
            if debit.remaining_amount.amount_paise > 0:
                final_block = self.release_block(
                    ReleaseBlockRequest(
                        block_id=block_id,
                        transaction_id=outcome.transaction_id,
                        amount=debit.remaining_amount,
                        idempotency_key=f"{idempotency_key}:release",
                    )
                ).block
            return SettlementResult(
                transaction_id=outcome.transaction_id,
                block_id=block_id,
                authorized_amount=final_block.authorized_amount,
                final_amount=outcome.actual_amount,
                debited_amount=final_block.debited_amount,
                released_amount=final_block.released_amount,
                shortfall=Money.from_non_negative_paise(0),
                status=SettlementStatus.SETTLED,
                provider=final_block.provider,
                final_block=final_block,
            )

        return self._settlement_idempotency.execute(
            "settlement",
            idempotency_key,
            {
                "block_id": block_id,
                "transaction_id": outcome.transaction_id,
                "actual_amount_paise": outcome.actual_amount.amount_paise,
                "completed_at": outcome.completed_at.isoformat(),
            },
            action,
        )
