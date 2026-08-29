"""Central Phase-7 personalization configuration."""

from decimal import Decimal

PERSONALIZED_MODEL_VERSION = "fare_distribution_personalized_v1"
MINIMUM_PERSONALIZATION_HISTORY = 3
CHRONOLOGICAL_SPLIT_STRATEGY = "transaction_timestamp_ascending_70_15_15"

HISTORY_FEATURE_NAMES = (
    "customer_history_count",
    "customer_mean_fare_ratio",
    "customer_fare_ratio_stddev",
    "customer_overrun_rate",
    "customer_mean_positive_overrun_ratio",
)

# Evaluation-only, observed-history segment definitions. These are not policies.
STABLE_MAX_STDDEV = Decimal("0.025")
STABLE_MAX_MEAN_DISTANCE_FROM_ONE = Decimal("0.03")
VARIABLE_MIN_STDDEV = Decimal("0.05")
OVERRUN_PRONE_MIN_RATE = Decimal("0.60")
OVERRUN_PRONE_MIN_MEAN_RATIO = Decimal("1.05")

