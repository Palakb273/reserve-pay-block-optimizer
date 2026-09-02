"""Retrospective static-versus-dynamic evaluation on identical rides."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from statistics import median

from reserve_pay_optimizer.config import METRIC_RATIO_QUANTUM
from reserve_pay_optimizer.domain.evaluation import StrategyMetrics, format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.dynamic.simulation import DynamicSimulationDataset
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy
from reserve_pay_optimizer.services.evaluation import aggregate_evaluations, evaluate_transaction

DYNAMIC_EVALUATION_ASSUMPTION = (
    "Dynamic evaluation assumes recommended additional block requests succeed. "
    "No real Razorpay authorization is performed."
)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal(0)
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        METRIC_RATIO_QUANTUM, rounding=ROUND_HALF_UP
    )


def _average(values: list[int]) -> Money:
    value = int(
        (Decimal(sum(values)) / Decimal(len(values))).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )
    return Money.from_non_negative_paise(value)


@dataclass(frozen=True, slots=True)
class DynamicEvaluationDiagnostics:
    average_initial_block: Money
    average_final_authorized_block: Money
    average_total_additional_block: Money
    average_additional_when_triggered: Money
    rides_requiring_additional_block_rate: Decimal
    average_reoptimization_count: Decimal
    average_block_increase_count: Decimal
    current_block_remained_sufficient_rate: Decimal
    update_triggered_increase_rate: Decimal
    maximum_additional_amount: Money
    median_additional_amount: Money

    def to_dict(self) -> dict[str, object]:
        return {
            "average_initial_block_paise": self.average_initial_block.amount_paise,
            "average_final_authorized_block_paise": self.average_final_authorized_block.amount_paise,
            "average_total_additional_block_paise": self.average_total_additional_block.amount_paise,
            "average_additional_when_triggered_paise": self.average_additional_when_triggered.amount_paise,
            "rides_requiring_additional_block_rate": format_ratio(
                self.rides_requiring_additional_block_rate
            ),
            "average_reoptimization_count": format_ratio(self.average_reoptimization_count),
            "average_block_increase_count": format_ratio(self.average_block_increase_count),
            "current_block_remained_sufficient_rate": format_ratio(
                self.current_block_remained_sufficient_rate
            ),
            "update_triggered_increase_rate": format_ratio(
                self.update_triggered_increase_rate
            ),
            "maximum_additional_amount_paise": self.maximum_additional_amount.amount_paise,
            "median_additional_amount_paise": self.median_additional_amount.amount_paise,
        }


@dataclass(frozen=True, slots=True)
class DynamicReoptimizationEvaluation:
    static_metrics: StrategyMetrics
    dynamic_metrics: StrategyMetrics
    diagnostics: DynamicEvaluationDiagnostics
    policy: ReserveRiskPolicy
    record_count: int
    benefit_breakdown: dict[str, object]
    assumption: str = DYNAMIC_EVALUATION_ASSUMPTION

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluation_status": "complete",
            "evaluation_scope": "same_rides_static_vs_dynamic",
            "record_count": self.record_count,
            "risk_profile": self.policy.profile.value,
            "target_collection_probability": format_ratio(
                self.policy.target_collection_probability
            ),
            "authorization_assumption": self.assumption,
            "static": self.static_metrics.to_dict(),
            "dynamic": self.dynamic_metrics.to_dict(),
            "dynamic_diagnostics": self.diagnostics.to_dict(),
            "benefit_breakdown": self.benefit_breakdown,
        }


def evaluate_dynamic_reoptimization(
    dataset: DynamicSimulationDataset,
    service: DynamicRideService,
    policy: ReserveRiskPolicy,
) -> DynamicReoptimizationEvaluation:
    static_evaluations = []
    dynamic_evaluations = []
    initial_blocks: list[int] = []
    final_blocks: list[int] = []
    ride_additions: list[int] = []
    event_additions: list[int] = []
    total_updates = 0
    increase_count = 0
    sufficient_count = 0
    benefit_counts = {
        "static_failed_dynamic_succeeded": 0,
        "both_succeeded": 0,
        "both_failed": 0,
        "static_succeeded_dynamic_failed": 0,
        "dynamic_no_increase_required": 0,
    }
    for record in dataset.records:
        session = service.start_dynamic_session(record.initial_transaction, policy)
        initial = session.initial_authorized_block
        static_decision = ReserveDecision(
            transaction_id=record.initial_transaction.transaction_id,
            strategy="static_personalized_dynamic_comparison",
            strategy_version="1",
            block_amount=initial,
        )
        static_evaluation = evaluate_transaction(
            record.initial_transaction, static_decision, record.outcome
        )
        static_evaluations.append(static_evaluation)
        for update in record.updates:
            application = service.apply_context_update(session, update)
            session = application.session
            decision = application.decision
            total_updates += 1
            additional = decision.additional_block_required.amount_paise
            if additional > 0:
                increase_count += 1
                event_additions.append(additional)
                target_total = Money(
                    session.current_authorized_block.amount_paise + additional
                )
                session = service.confirm_block_authorized(
                    session, decision, target_total
                )
            else:
                sufficient_count += 1
        final = session.current_authorized_block
        initial_blocks.append(initial.amount_paise)
        final_blocks.append(final.amount_paise)
        ride_additions.append(final.amount_paise - initial.amount_paise)
        if final.amount_paise == initial.amount_paise:
            benefit_counts["dynamic_no_increase_required"] += 1
        dynamic_decision = ReserveDecision(
            transaction_id=record.initial_transaction.transaction_id,
            strategy="dynamic_personalized_reoptimization",
            strategy_version="1",
            block_amount=final,
        )
        dynamic_evaluation = evaluate_transaction(
            record.initial_transaction, dynamic_decision, record.outcome
        )
        dynamic_evaluations.append(dynamic_evaluation)
        if static_evaluation.collection_success and dynamic_evaluation.collection_success:
            benefit_counts["both_succeeded"] += 1
        elif not static_evaluation.collection_success and dynamic_evaluation.collection_success:
            benefit_counts["static_failed_dynamic_succeeded"] += 1
        elif static_evaluation.collection_success and not dynamic_evaluation.collection_success:
            benefit_counts["static_succeeded_dynamic_failed"] += 1
        else:
            benefit_counts["both_failed"] += 1

    count = len(dataset.records)
    triggered = [value for value in ride_additions if value > 0]
    event_median = int(Decimal(str(median(event_additions))).to_integral_value(rounding=ROUND_HALF_UP)) if event_additions else 0
    diagnostics = DynamicEvaluationDiagnostics(
        average_initial_block=_average(initial_blocks),
        average_final_authorized_block=_average(final_blocks),
        average_total_additional_block=_average(ride_additions),
        average_additional_when_triggered=(
            _average(triggered) if triggered else Money.from_non_negative_paise(0)
        ),
        rides_requiring_additional_block_rate=_ratio(len(triggered), count),
        average_reoptimization_count=(Decimal(total_updates) / Decimal(count)),
        average_block_increase_count=(Decimal(increase_count) / Decimal(count)),
        current_block_remained_sufficient_rate=_ratio(sufficient_count, total_updates),
        update_triggered_increase_rate=_ratio(increase_count, total_updates),
        maximum_additional_amount=Money.from_non_negative_paise(
            max(event_additions, default=0)
        ),
        median_additional_amount=Money.from_non_negative_paise(event_median),
    )
    return DynamicReoptimizationEvaluation(
        static_metrics=aggregate_evaluations(static_evaluations),
        dynamic_metrics=aggregate_evaluations(dynamic_evaluations),
        diagnostics=diagnostics,
        policy=policy,
        record_count=count,
        benefit_breakdown={
            **benefit_counts,
            **{
                f"{name}_rate": format_ratio(Decimal(value) / Decimal(count))
                for name, value in benefit_counts.items()
            },
        },
    )
