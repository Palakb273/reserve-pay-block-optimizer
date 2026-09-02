"""Central stable product configuration.

Prediction, risk, and optimization settings are deliberately absent.
"""

from datetime import timedelta, timezone
from decimal import Decimal

from reserve_pay_optimizer.domain.types import Currency, SupportedCity, TransactionDomain

MOBILITY_DOMAIN = TransactionDomain.MOBILITY
SUPPORTED_CURRENCY = Currency.INR
SUPPORTED_MOBILITY_CITIES = frozenset(SupportedCity)

# Money is constrained to a signed 64-bit integer number of paise so the
# representation can move safely between common application/datastore layers.
MAX_AMOUNT_PAISE = (1 << 63) - 1

# Public HTTP inputs are bounded before conversion to the floating-point ML
# boundary. These deliberately exceed the Phase-3 simulator's typical 0.8–40 km
# and <=2x surge range while rejecting values that are not credible ride inputs.
MAX_MOBILITY_DISTANCE_KM = Decimal("500")
MAX_MOBILITY_DURATION_MINUTES = 24 * 60
MAX_MOBILITY_SURGE_MULTIPLIER = Decimal("5")

# India does not observe daylight-saving time, so a fixed offset is accurate.
INDIA_STANDARD_TIME = timezone(timedelta(hours=5, minutes=30), name="IST")

# Phase 2 baseline defaults and deterministic metric precision.
DEFAULT_FIXED_BUFFER_PERCENTAGE = Decimal("20")
METRIC_RATIO_QUANTUM = Decimal("0.000001")
