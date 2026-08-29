from decimal import Decimal

from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.prediction.config import QUANTILES
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from tests.fixtures import make_context


def distribution_prediction(
    transaction_id: str = "TXN-001",
    amounts: tuple[int, ...] = (5000, 6000, 7500, 10000, 12000, 14000, 14500, 15000, 16000, 18000),
) -> FareDistributionPrediction:
    return FareDistributionPrediction(
        transaction_id=transaction_id,
        model_version="fixture_v1",
        quantiles=tuple(
            (quantile, Money(amount)) for quantile, amount in zip(QUANTILES, amounts, strict=True)
        ),
    )


def optimization_context(transaction_id: str = "TXN-001", estimate: int = 10000):
    return make_context(transaction_id, estimate)
