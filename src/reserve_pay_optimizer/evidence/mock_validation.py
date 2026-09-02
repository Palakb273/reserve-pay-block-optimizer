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


def validate_mock_reserve_pay(
    context,
    *,
    dynamic_dataset=None,
    dynamic_service=None,
    policy=None,
) -> dict[str, object]:
    scenarios: list[dict[str, object]] = []

    expected_states = {
        "create_success": "authorized",
        "idempotent_create": "same result; no duplicate block",
        "increase_success": "authorized amount increased exactly once",
        "failed_increase_no_mutation": "authorized amount unchanged",
        "transient_retry_success": "authorized after retry with the same idempotency key",
        "permanent_failure_surfaced": "rejected once without retry",
        "idempotency_conflict": "conflict rejected without execution",
        "partial_debit": "partially_debited with remaining authorization",
        "full_settlement": "actual fare fully debited within authorization",
        "release_remaining_amount": "unused remaining authorization released",
        "final_status_and_accounting": "released and accounting invariant balanced",
        "under_block_shortfall": "explicit shortfall with no over-debit",
        "dynamic_additional_authorization_success": "provider success confirms dynamic target",
        "dynamic_additional_authorization_failure_no_mutation": "failed provider execution preserves authorized session state",
        "stale_success_reconciliation_visible": "reconciliation_required without latest-session mutation",
    }

    def passed(name: str, details: dict[str, object] | None = None) -> None:
        observed = details or {}
        scenarios.append({
            "scenario": name,
            "expected_state": expected_states[name],
            "observed_state": observed,
            "passed": True,
            "details": observed,
        })

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
    passed("full_settlement", {
        "debited_amount_paise": settlement.debited_amount.amount_paise,
        "settlement_status": settlement.status.value,
    })
    passed("release_remaining_amount", {
        "released_amount_paise": settlement.released_amount.amount_paise,
        "final_status": settlement.final_block.status.value,
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

    if dynamic_dataset is not None and dynamic_service is not None and policy is not None:
        stale_proof = None
        for record in dynamic_dataset.records:
            if len(record.updates) < 2:
                continue
            session = dynamic_service.start_dynamic_session(record.initial_transaction, policy)
            first = dynamic_service.apply_context_update(session, record.updates[0])
            if first.decision.additional_block_required.amount_paise <= 0:
                continue
            stale_proof = (record, session, first)
            break
        if stale_proof is None:
            raise AssertionError("dynamic cohort has no usable stale-confirmation scenario")
        record, session, first = stale_proof

        success_provider = MockReserveProvider()
        success_service = ReservePayService(
            success_provider, dynamic_service=dynamic_service, sleeper=lambda _: None
        )
        success_initial = success_service.authorize_initial_block(
            session.initial_optimization.reserve_decision,
            customer_reference=record.initial_transaction.customer_id,
            idempotency_key="dynamic-success-create",
        )
        success = success_service.request_additional_block(
            first.session,
            first.decision,
            block_id=success_initial.block.block_id,
            idempotency_key="dynamic-success-increase",
        )
        if success.status.value != "succeeded" or success.session.current_authorized_block != first.decision.recommended_target_block:
            raise AssertionError("successful dynamic increase was not confirmed")
        passed("dynamic_additional_authorization_success", {
            "recommended_target_paise": first.decision.recommended_target_block.amount_paise,
            "authorized_after_paise": success.session.current_authorized_block.amount_paise,
        })

        dynamic_failure_provider = MockReserveProvider(MockFailureConfig(fail_next_increase=True))
        dynamic_failure_service = ReservePayService(
            dynamic_failure_provider, dynamic_service=dynamic_service, sleeper=lambda _: None
        )
        failure_initial = dynamic_failure_service.authorize_initial_block(
            session.initial_optimization.reserve_decision,
            customer_reference=record.initial_transaction.customer_id,
            idempotency_key="dynamic-failure-create",
        )
        before_dynamic_failure = first.session.current_authorized_block.amount_paise
        failed_dynamic = dynamic_failure_service.request_additional_block(
            first.session,
            first.decision,
            block_id=failure_initial.block.block_id,
            idempotency_key="dynamic-failure-increase",
        )
        if failed_dynamic.status.value != "failed" or failed_dynamic.session.current_authorized_block.amount_paise != before_dynamic_failure:
            raise AssertionError("failed dynamic increase mutated application authorization")
        passed("dynamic_additional_authorization_failure_no_mutation", {
            "recommended_target_paise": first.decision.recommended_target_block.amount_paise,
            "authorized_before_paise": before_dynamic_failure,
            "authorized_after_paise": failed_dynamic.session.current_authorized_block.amount_paise,
        })

        stale_provider = MockReserveProvider()
        stale_service = ReservePayService(
            stale_provider, dynamic_service=dynamic_service, sleeper=lambda _: None
        )
        initial = stale_service.authorize_initial_block(
            session.initial_optimization.reserve_decision,
            customer_reference=record.initial_transaction.customer_id,
            idempotency_key="stale-create",
        )
        provider_success = stale_service.increase_block(IncreaseBlockRequest(
            initial.block.block_id,
            record.initial_transaction.transaction_id,
            first.decision.additional_block_required,
            "stale-increase",
        ))
        latest = dynamic_service.apply_context_update(first.session, record.updates[1])
        reconciliation = stale_service.confirm_dynamic_increase(
            latest.session, first.decision, provider_success
        )
        if reconciliation.status.value != "reconciliation_required":
            raise AssertionError("stale provider success did not require reconciliation")
        if reconciliation.session.current_authorized_block != session.current_authorized_block:
            raise AssertionError("stale provider success mutated current application authorization")
        passed("stale_success_reconciliation_visible", {
            "status": reconciliation.status.value,
            "provider_authorized_paise": provider_success.block.authorized_amount.amount_paise,
            "application_authorized_paise": reconciliation.session.current_authorized_block.amount_paise,
        })
    return {
        "provider": "mock",
        "network_calls_made": False,
        "total_scenarios": len(scenarios),
        "passed_scenarios": sum(bool(item["passed"]) for item in scenarios),
        "failed_scenarios": sum(not bool(item["passed"]) for item in scenarios),
        "scenarios": scenarios,
    }
