from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING

from reserve_pay_optimizer.domain.mobility import RideTransactionContext, RideTransactionOutcome
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from tests.fixtures import make_context


BASE_TIME = datetime.fromisoformat("2026-06-01T10:00:00+05:30")


def context_at(
    transaction_id: str,
    customer_id: str,
    start: datetime,
    amount_paise: int = 10000,
) -> RideTransactionContext:
    return replace(
        make_context(transaction_id, amount_paise),
        customer_id=customer_id,
        timestamp=start,
    )


def outcome_at(
    transaction_id: str,
    completed: datetime,
    amount_paise: int,
) -> RideTransactionOutcome:
    return RideTransactionOutcome(
        transaction_id=transaction_id,
        actual_amount=Money(amount_paise=amount_paise),
        completed_at=completed,
    )


def history_features(
    customer_id: str,
    count: int,
    mean: str = "1.00",
    stddev: str = "0.01",
    overrun_rate: str = "0.40",
    mean_positive: str = "0.02",
) -> CustomerHistoryFeatures:
    return CustomerHistoryFeatures(
        customer_id=customer_id,
        completed_ride_count=count,
        mean_fare_ratio=Decimal(mean),
        fare_ratio_stddev=Decimal(stddev),
        overrun_rate=Decimal(overrun_rate),
        mean_positive_overrun_ratio=Decimal(mean_positive),
    )


def scaled_distribution(
    context: RideTransactionContext,
    scale: Decimal,
    model_version: str = "fixture",
) -> FareDistributionPrediction:
    ratios = (
        Decimal("0.80"), Decimal("0.85"), Decimal("0.90"), Decimal("1.00"),
        Decimal("1.05"), Decimal("1.10"), Decimal("1.12"), Decimal("1.15"),
        Decimal("1.20"), Decimal("1.30"),
    )
    return FareDistributionPrediction(
        transaction_id=context.transaction_id,
        model_version=model_version,
        quantiles=tuple(
            (
                quantile,
                Money(
                    amount_paise=int(
                        (
                            Decimal(context.estimated_amount.amount_paise)
                            * ratio
                            * scale
                        ).to_integral_value(rounding=ROUND_CEILING)
                    )
                ),
            )
            for quantile, ratio in zip(QUANTILES, ratios, strict=True)
        ),
    )

