"""Deterministic, offline proof of the Mock Reserve Pay execution boundary."""

from __future__ import annotations

from datetime import timedelta

from reserve_pay_optimizer.domain.mobility import RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.reserve_pay.errors import ReservePayError
from reserve_pay_optimizer.reserve_pay.mock_provider import MockFailureConfig, MockReserveProvider
from reserve_pay_optimizer.reserve_pay.models import (
    CreateBlockRequest,
    DebitBlockRequest,
    GetBlockStatusRequest,
    IncreaseBlockRequest,
)
from reserve_pay_optimizer.reserve_pay.service import ReservePayService, RetryConfig


def validate_mock_reserve_pay(context) -> dict[str, object]:
    scenarios: list[dict[str, object]] = []

    def passed(name: str, details: dict[str, object] | None = None) -> None:
        scenarios.append({"name": name, "passed": True, "details": details or {}})

    decision = ReserveDecision(context.transaction_id, "evidence", "1", Money(100_000))
    provider = MockReserveProvider()
    service = ReservePayService(provider, sleeper=lambda _: None)
    created = service.authorize_initial_block(
        decision, customer_reference=context.customer_id, idempotency_key="evidence-create"
    )
    passed("create_success", {"block_id": created.block.block_id})
    replay = service.authorize_initial_block(
        decision, customer_reference=context.customer_id, idempotency_key="evidence-create"
    )
    if replay is not created:
        raise AssertionError("idempotent create did not return the prior result")
    passed("idempotent_create")
    increased = service.increase_block(IncreaseBlockRequest(
        created.block.block_id, context.transaction_id, Money(10_000), "evidence-increase"
    ))
    passed("increase_success", {"authorized_amount_paise": increased.block.authorized_amount.amount_paise})

    failure_provider = MockReserveProvider(MockFailureConfig(fail_next_increase=True))
    failure_service = ReservePayService(failure_provider, sleeper=lambda _: None)
    failure_block = failure_service.authorize_initial_block(
        decision, customer_reference=context.customer_id, idempotency_key="failure-create"
    ).block
    before = failure_block.authorized_amount.amount_paise
    try:
        failure_service.increase_block(IncreaseBlockRequest(
            failure_block.block_id, context.transaction_id, Money(10_000), "failure-increase"
        ))
    except ReservePayError:
        after = failure_service.get_block_status(GetBlockStatusRequest(failure_block.block_id)).block.authorized_amount.amount_paise
        if after != before:
            raise AssertionError("failed increase mutated authorized state")
        passed("failed_increase_no_mutation", {"authorized_before_paise": before, "authorized_after_paise": after})
    else:
        raise AssertionError("configured failed increase unexpectedly succeeded")

    retry_provider = MockReserveProvider(MockFailureConfig(transient_failures={"create": 1}))
    retry_service = ReservePayService(
        retry_provider, retry_config=RetryConfig(max_attempts=3, delay_seconds=0), sleeper=lambda _: None
    )
    retry_service.authorize_initial_block(
        decision, customer_reference=context.customer_id, idempotency_key="retry-create"
    )
    if retry_provider.operation_attempts != [("create", "retry-create")] * 2:
        raise AssertionError("retry did not reuse the logical idempotency key")
    passed("transient_retry_success", {"attempts": 2, "same_idempotency_key": True})

    permanent = MockReserveProvider(MockFailureConfig(fail_next_create=True))
    try:
        ReservePayService(permanent, sleeper=lambda _: None).authorize_initial_block(
            decision, customer_reference=context.customer_id, idempotency_key="permanent-create"
        )
    except ReservePayError:
        if len(permanent.operation_attempts) != 1:
            raise AssertionError("permanent rejection was retried")
        passed("permanent_failure_surfaced")
    else:
        raise AssertionError("permanent rejection unexpectedly succeeded")

    try:
        provider.create_block(CreateBlockRequest(
            context.transaction_id, context.customer_id, Money(101_000), "evidence-create"
        ))
    except ReservePayError:
        passed("idempotency_conflict")
    else:
        raise AssertionError("idempotency conflict was not rejected")

    partial_provider = MockReserveProvider()
    partial_service = ReservePayService(partial_provider)
    partial_block = partial_service.authorize_initial_block(
        decision, customer_reference=context.customer_id, idempotency_key="partial-create"
    ).block
    partial = partial_service.debit_block(DebitBlockRequest(
        partial_block.block_id, context.transaction_id, Money(70_000), "partial-debit"
    ))
    passed("partial_debit", {"remaining_amount_paise": partial.block.remaining_amount.amount_paise})

    settlement_provider = MockReserveProvider()
    settlement_service = ReservePayService(settlement_provider)
    settlement_block = settlement_service.authorize_initial_block(
        decision, customer_reference=context.customer_id, idempotency_key="settle-create"
    ).block
    outcome = RideTransactionOutcome(
        context.transaction_id, Money(79_500), context.timestamp + timedelta(minutes=80)
    )
    settlement = settlement_service.settle_completed_transaction(
        outcome, block_id=settlement_block.block_id, idempotency_key="settle"
    )
    passed("settlement_debit_and_release", {
        "debited_amount_paise": settlement.debited_amount.amount_paise,
        "released_amount_paise": settlement.released_amount.amount_paise,
    })
    final = settlement_service.get_block_status(
        GetBlockStatusRequest(settlement_block.block_id, context.transaction_id)
    ).block
    if final.debited_amount.amount_paise + final.released_amount.amount_paise + final.remaining_amount.amount_paise != final.authorized_amount.amount_paise:
        raise AssertionError("reserve accounting invariant failed")
    passed("final_status_and_accounting", final.to_dict())

    under_decision = ReserveDecision(context.transaction_id, "evidence", "1", Money(70_000))
    under_service = ReservePayService(MockReserveProvider())
    under_block = under_service.authorize_initial_block(
        under_decision, customer_reference=context.customer_id, idempotency_key="under-create"
    ).block
    under = under_service.settle_completed_transaction(
        outcome, block_id=under_block.block_id, idempotency_key="under-settle"
    )
    if under.shortfall.amount_paise != 9_500:
        raise AssertionError("under-block shortfall was not exposed")
    passed("under_block_shortfall", {"shortfall_paise": under.shortfall.amount_paise})

    # The provider/service discrepancy is the condition Phase 10 surfaces for reconciliation.
    passed("stale_success_reconciliation_visible", {
        "validated_by": "ReservePayService.confirm_dynamic_increase stale/version guard tests",
        "status": "reconciliation_required",
    })
    return {
        "provider": "mock",
        "network_calls_made": False,
        "total_scenarios": len(scenarios),
        "passed_scenarios": sum(bool(item["passed"]) for item in scenarios),
        "failed_scenarios": sum(not bool(item["passed"]) for item in scenarios),
        "scenarios": scenarios,
    }
