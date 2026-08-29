"""Dynamic re-optimization using existing prediction and policy components."""

from dataclasses import replace

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.dynamic.errors import DynamicSessionError
from reserve_pay_optimizer.dynamic.models import (
    DynamicAuditEventType,
    DynamicAuditRecord,
    DynamicReoptimizationDecision,
    DynamicRideSession,
    DynamicUpdateApplication,
    ProcessedRideUpdate,
    RideContextUpdate,
)
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.models import (
    CustomerHistoryFeatures,
    PersonalizedFareDistributionPrediction,
)
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile


class DynamicRideService:
    """Apply immutable dynamic ride state transitions before final outcome exists."""

    def __init__(
        self,
        predictor: PersonalizedFarePredictor,
        optimizer: ReserveBlockOptimizer | None = None,
    ) -> None:
        self.predictor = predictor
        self.policy_optimizer = PolicyConstrainedOptimizer(
            optimizer or ReserveBlockOptimizer()
        )

    def _predict_with_snapshot(
        self,
        context: RideTransactionContext,
        history: CustomerHistoryFeatures,
        history_as_of,
    ) -> PersonalizedFareDistributionPrediction:
        return self.predictor.predict_with_history(
            context,
            history,
            history_as_of=history_as_of,
        )

    def start_dynamic_session(
        self,
        transaction: RideTransactionContext,
        risk_profile: RiskProfile | ReserveRiskPolicy = RiskProfile.BALANCED,
    ) -> DynamicRideSession:
        policy = (
            risk_profile
            if isinstance(risk_profile, ReserveRiskPolicy)
            else ReserveRiskPolicy.for_profile(risk_profile)
        )
        history = self.predictor.history_provider.features_for(transaction)
        prediction = self._predict_with_snapshot(
            transaction, history, transaction.timestamp
        )
        optimization = self.policy_optimizer.optimize(
            transaction, prediction, policy
        )
        initial_block = optimization.recommended_block
        audit = DynamicAuditRecord(
            event_type=DynamicAuditEventType.SESSION_STARTED,
            session_version=0,
            recorded_at=transaction.timestamp,
            authorized_block=initial_block,
        )
        return DynamicRideSession(
            transaction_id=transaction.transaction_id,
            initial_context=transaction,
            current_context=transaction,
            risk_policy=policy,
            initial_authorized_block=initial_block,
            current_authorized_block=initial_block,
            session_version=0,
            started_at=transaction.timestamp,
            last_update_at=transaction.timestamp,
            history_snapshot=history,
            initial_prediction=prediction,
            latest_prediction=prediction,
            initial_optimization=optimization,
            latest_optimization=optimization,
            audit_trail=(audit,),
        )

    def apply_context_update(
        self,
        session: DynamicRideSession,
        update: RideContextUpdate,
    ) -> DynamicUpdateApplication:
        for processed in session.processed_updates:
            if processed.update.event_id == update.event_id:
                if processed.update == update:
                    return DynamicUpdateApplication(
                        session=session,
                        decision=processed.decision,
                        replayed=True,
                    )
                raise DynamicSessionError(
                    "duplicate_event_conflict",
                    "event_id was already processed with a different payload",
                    "event_id",
                )
        if update.transaction_id != session.transaction_id:
            raise DynamicSessionError(
                "transaction_id_mismatch",
                "update transaction_id does not match the dynamic session",
                "transaction_id",
            )
        expected_sequence = len(session.processed_updates) + 1
        if update.sequence_number != expected_sequence:
            raise DynamicSessionError(
                "out_of_order_sequence",
                f"expected sequence_number {expected_sequence}, got {update.sequence_number}",
                "sequence_number",
            )
        if update.observed_at <= session.last_update_at:
            raise DynamicSessionError(
                "stale_timestamp",
                "observed_at must be strictly later than the previous session event",
                "observed_at",
            )

        current = session.current_context
        revised = RideTransactionContext(
            transaction_id=current.transaction_id,
            customer_id=current.customer_id,
            estimated_amount=update.revised_estimated_amount or current.estimated_amount,
            city=current.city,
            distance_km=(
                update.revised_distance_km
                if update.revised_distance_km is not None
                else current.distance_km
            ),
            estimated_duration_minutes=(
                update.revised_estimated_duration_minutes
                if update.revised_estimated_duration_minutes is not None
                else current.estimated_duration_minutes
            ),
            surge_multiplier=(
                update.revised_surge_multiplier
                if update.revised_surge_multiplier is not None
                else current.surge_multiplier
            ),
            timestamp=current.timestamp,
        )
        if revised == current:
            raise DynamicSessionError(
                "no_context_change",
                "the update must change at least one mutable decision-time field",
                "update",
            )
        prediction = self._predict_with_snapshot(
            revised, session.history_snapshot, session.started_at
        )
        optimization = self.policy_optimizer.optimize(
            revised, prediction, session.risk_policy
        )
        target = optimization.recommended_block
        additional_paise = max(
            target.amount_paise - session.current_authorized_block.amount_paise,
            0,
        )
        version = session.session_version + 1
        decision = DynamicReoptimizationDecision(
            transaction_id=session.transaction_id,
            event_id=update.event_id,
            sequence_number=update.sequence_number,
            session_version=version,
            update_reason=update.reason,
            previous_authorized_block=session.current_authorized_block,
            previous_target_block=session.latest_optimization.recommended_block,
            recommended_target_block=target,
            additional_block_required=Money.from_non_negative_paise(additional_paise),
            current_block_sufficient=additional_paise == 0,
            prediction_mode=prediction.prediction_mode,
            history_count=prediction.history_count,
            risk_policy=session.risk_policy,
            estimated_collection_probability=optimization.estimated_collection_probability,
            estimated_under_block_probability=optimization.estimated_under_block_probability,
            expected_excess_block=optimization.expected_excess_block,
            objective_score=optimization.objective_score,
            model_version=prediction.model_version,
            observed_at=update.observed_at,
            previous_estimated_amount=current.estimated_amount,
            revised_estimated_amount=revised.estimated_amount,
            previous_distance_km=current.distance_km,
            revised_distance_km=revised.distance_km,
            previous_estimated_duration_minutes=current.estimated_duration_minutes,
            revised_estimated_duration_minutes=revised.estimated_duration_minutes,
            previous_surge_multiplier=current.surge_multiplier,
            revised_surge_multiplier=revised.surge_multiplier,
            previous_q50=session.latest_prediction.amount_for_quantile("0.50"),
            revised_q50=prediction.amount_for_quantile("0.50"),
            previous_q90=session.latest_prediction.amount_for_quantile("0.90"),
            revised_q90=prediction.amount_for_quantile("0.90"),
            previous_q95=session.latest_prediction.amount_for_quantile("0.95"),
            revised_q95=prediction.amount_for_quantile("0.95"),
            previous_q97=session.latest_prediction.amount_for_quantile("0.97"),
            revised_q97=prediction.amount_for_quantile("0.97"),
            previous_q99=session.latest_prediction.amount_for_quantile("0.99"),
            revised_q99=prediction.amount_for_quantile("0.99"),
        )
        updated_session = replace(
            session,
            current_context=revised,
            session_version=version,
            last_update_at=update.observed_at,
            latest_prediction=prediction,
            latest_optimization=optimization,
            processed_updates=session.processed_updates
            + (ProcessedRideUpdate(update=update, decision=decision),),
            audit_trail=session.audit_trail
            + (
                DynamicAuditRecord(
                    DynamicAuditEventType.CONTEXT_UPDATED,
                    version,
                    update.observed_at,
                    event_id=update.event_id,
                ),
                DynamicAuditRecord(
                    DynamicAuditEventType.REOPTIMIZED,
                    version,
                    update.observed_at,
                    event_id=update.event_id,
                ),
            ),
        )
        return DynamicUpdateApplication(updated_session, decision)

    def confirm_block_authorized(
        self,
        session: DynamicRideSession,
        decision: DynamicReoptimizationDecision,
        authorized_total_block: Money,
    ) -> DynamicRideSession:
        if decision.transaction_id != session.transaction_id:
            raise DynamicSessionError(
                "transaction_id_mismatch",
                "confirmation decision does not belong to this session",
                "transaction_id",
            )
        for audit in session.audit_trail:
            if (
                audit.event_type is DynamicAuditEventType.BLOCK_CONFIRMED
                and audit.event_id == decision.event_id
            ):
                if audit.authorized_block == authorized_total_block:
                    return session
                raise DynamicSessionError(
                    "confirmation_conflict",
                    "this decision was already confirmed with a different amount",
                    "authorized_total_block",
                )
        if decision.session_version != session.session_version:
            raise DynamicSessionError(
                "stale_confirmation",
                "confirmation references an outdated session version",
                "session_version",
            )
        if not session.processed_updates or session.processed_updates[-1].decision != decision:
            raise DynamicSessionError(
                "unknown_decision",
                "confirmation must reference the latest decision for this session",
                "decision",
            )
        if not isinstance(authorized_total_block, Money):
            raise DynamicSessionError(
                "invalid_confirmation_amount",
                "authorized_total_block must be Money",
                "authorized_total_block",
            )
        expected_total = (
            decision.previous_authorized_block.amount_paise
            + decision.additional_block_required.amount_paise
        )
        if session.current_authorized_block != decision.previous_authorized_block:
            raise DynamicSessionError(
                "stale_confirmation",
                "authorized state changed after this decision was produced",
                "authorized_total_block",
            )
        if authorized_total_block.amount_paise != expected_total:
            raise DynamicSessionError(
                "invalid_confirmation_amount",
                f"confirmation must authorize exactly {expected_total} total paise",
                "authorized_total_block",
            )
        return replace(
            session,
            current_authorized_block=authorized_total_block,
            audit_trail=session.audit_trail
            + (
                DynamicAuditRecord(
                    DynamicAuditEventType.BLOCK_CONFIRMED,
                    session.session_version,
                    decision.observed_at,
                    event_id=decision.event_id,
                    authorized_block=authorized_total_block,
                ),
            ),
        )
