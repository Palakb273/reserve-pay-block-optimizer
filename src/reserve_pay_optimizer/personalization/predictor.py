"""Automatic history lookup and cold-start model routing."""

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.personalization.config import MINIMUM_PERSONALIZATION_HISTORY
from reserve_pay_optimizer.personalization.history import CustomerHistoryProvider
from reserve_pay_optimizer.personalization.model import PersonalizedConditionalFareDistributionModel
from reserve_pay_optimizer.personalization.models import PersonalizedFareDistributionPrediction
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel


class PersonalizedFarePredictor:
    def __init__(
        self,
        base_predictor: ConditionalFareDistributionModel,
        personalized_predictor: PersonalizedConditionalFareDistributionModel,
        history_provider: CustomerHistoryProvider,
        min_history: int = MINIMUM_PERSONALIZATION_HISTORY,
    ) -> None:
        if isinstance(min_history, bool) or not isinstance(min_history, int) or min_history <= 0:
            raise ValueError("min_history must be a positive integer")
        self.base_predictor = base_predictor
        self.personalized_predictor = personalized_predictor
        self.history_provider = history_provider
        self.min_history = min_history

    def predict(
        self, context: RideTransactionContext
    ) -> PersonalizedFareDistributionPrediction:
        history = self.history_provider.features_for(context)
        if history.completed_ride_count < self.min_history:
            mode = "base"
            distribution = self.base_predictor.predict(context)
        else:
            mode = "personalized"
            distribution = self.personalized_predictor.predict(context, history)
        return PersonalizedFareDistributionPrediction.from_distribution(
            distribution,
            prediction_mode=mode,
            history_features=history,
            history_as_of=context.timestamp,
        )

