"""Deterministic India mobility transaction generator."""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
from hashlib import sha256
from random import Random
from dataclasses import dataclass

from reserve_pay_optimizer.config import INDIA_STANDARD_TIME
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.simulation.config import FareModelConfig, SimulationConfig
from reserve_pay_optimizer.simulation.models import SimulationDataset, SimulationRecord
from reserve_pay_optimizer.simulation.profiles import (
    TIME_BAND_PROFILES,
    CitySimulationProfile,
    time_band_for_hour,
)


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(value, maximum))


def _random_decimal_gauss(rng: Random, sigma: Decimal) -> Decimal:
    return Decimal(str(rng.gauss(0.0, float(sigma))))


@dataclass(frozen=True, slots=True)
class _SyntheticCustomerBehavior:
    overrun_bias: Decimal
    variance_multiplier: Decimal


def _customer_behavior(seed: int, customer_id: str) -> _SyntheticCustomerBehavior:
    """Derive a hidden stable profile without Python's nondeterministic hash()."""

    digest = sha256(f"{seed}:{customer_id}:phase7".encode("utf-8")).digest()
    profile_rng = Random(int.from_bytes(digest[:8], "big"))
    return _SyntheticCustomerBehavior(
        overrun_bias=Decimal(str(profile_rng.uniform(-0.035, 0.09))),
        variance_multiplier=Decimal(str(profile_rng.uniform(0.65, 1.60))),
    )


def _weighted_city(
    rng: Random, weights: tuple[tuple[SupportedCity, int], ...]
) -> SupportedCity:
    ticket = rng.randrange(sum(weight for _, weight in weights))
    cumulative = 0
    for city, weight in weights:
        cumulative += weight
        if ticket < cumulative:
            return city
    raise AssertionError("Validated city weights must select a city")


def _timestamp(rng: Random, config: SimulationConfig) -> datetime:
    start = config.start_datetime.astimezone(INDIA_STANDARD_TIME)
    end = config.end_datetime.astimezone(INDIA_STANDARD_TIME)
    seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, seconds))


def _distance(
    rng: Random, profile: CitySimulationProfile, fare: FareModelConfig
) -> Decimal:
    low = max(
        fare.minimum_distance_km,
        profile.typical_distance_km - profile.distance_spread_km,
    )
    high = min(
        fare.maximum_distance_km,
        profile.typical_distance_km + profile.distance_spread_km * Decimal("1.8"),
    )
    mode = _clamp(profile.typical_distance_km, low, high)
    sampled = Decimal(
        str(rng.triangular(float(low), float(high), float(mode)))
    )
    return sampled.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _estimated_duration_minutes(
    rng: Random,
    distance_km: Decimal,
    profile: CitySimulationProfile,
    timestamp: datetime,
) -> int:
    time_profile = TIME_BAND_PROFILES[time_band_for_hour(timestamp.hour)]
    weekend_factor = Decimal("0.90") if timestamp.weekday() >= 5 else Decimal(1)
    planning_jitter = Decimal(str(rng.uniform(0.92, 1.08)))
    minutes = (
        distance_km
        / profile.average_speed_kmph
        * Decimal(60)
        * time_profile.traffic_factor
        * weekend_factor
        * planning_jitter
    )
    return max(1, int(minutes.to_integral_value(rounding=ROUND_CEILING)))


def _surge_multiplier(
    rng: Random,
    profile: CitySimulationProfile,
    timestamp: datetime,
    fare: FareModelConfig,
) -> Decimal:
    if fare.maximum_surge_multiplier == Decimal(1):
        return Decimal("1.00")
    time_profile = TIME_BAND_PROFILES[time_band_for_hour(timestamp.hour)]
    probability = min(
        Decimal("0.45"),
        profile.base_surge_probability
        * time_profile.surge_probability_multiplier,
    )
    if rng.random() >= float(probability):
        return Decimal("1.00")
    high = fare.maximum_surge_multiplier
    mode = min(Decimal("1.20"), high)
    sampled = Decimal(str(rng.triangular(1.05, float(high), float(mode))))
    step = Decimal("0.05")
    rounded = (sampled / step).to_integral_value(rounding=ROUND_HALF_UP) * step
    return _clamp(rounded, Decimal("1.05"), high).quantize(Decimal("0.01"))


def _fare_paise(
    distance_km: Decimal,
    duration_minutes: int,
    surge_multiplier: Decimal,
    fare: FareModelConfig,
    rounding: str,
) -> int:
    amount = (
        Decimal(fare.base_fare_paise)
        + distance_km * fare.distance_rate_paise_per_km
        + Decimal(duration_minutes) * fare.duration_rate_paise_per_minute
    ) * surge_multiplier
    return max(1, int(amount.to_integral_value(rounding=rounding)))


def _actual_fare_and_duration(
    rng: Random,
    distance_km: Decimal,
    estimated_duration_minutes: int,
    surge_multiplier: Decimal,
    timestamp: datetime,
    profile: CitySimulationProfile,
    fare: FareModelConfig,
    customer_behavior: _SyntheticCustomerBehavior | None = None,
) -> tuple[int, int]:
    behavior = customer_behavior or _SyntheticCustomerBehavior(Decimal(0), Decimal(1))
    time_profile = TIME_BAND_PROFILES[time_band_for_hour(timestamp.hour)]
    route_change = _clamp(
        _random_decimal_gauss(
            rng, profile.route_variation_ratio * behavior.variance_multiplier
        ),
        Decimal("-0.30"),
        Decimal("0.45"),
    )
    traffic_sigma = (
        profile.traffic_variation_ratio
        * time_profile.uncertainty_multiplier
        * behavior.variance_multiplier
    )
    traffic_change = _clamp(
        _random_decimal_gauss(rng, traffic_sigma),
        Decimal("-0.35"),
        Decimal("0.70"),
    )
    actual_distance = _clamp(
        distance_km * (Decimal(1) + route_change),
        fare.minimum_distance_km,
        fare.maximum_distance_km * Decimal("1.5"),
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    duration_factor = Decimal(1) + traffic_change + route_change * Decimal("0.35")
    actual_duration = max(
        1,
        int(
            (Decimal(estimated_duration_minutes) * duration_factor).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        ),
    )
    noise_sigma = fare.pricing_noise_ratio * (
        Decimal(1) + (surge_multiplier - Decimal(1)) * Decimal("0.50")
    ) * behavior.variance_multiplier
    pricing_noise = _clamp(
        _random_decimal_gauss(rng, noise_sigma),
        Decimal("-0.08"),
        Decimal("0.08"),
    )
    unnoised_fare = Decimal(
        _fare_paise(
            actual_distance,
            actual_duration,
            surge_multiplier,
            fare,
            ROUND_HALF_UP,
        )
    )
    actual_fare = max(
        1,
        int(
            (
                unnoised_fare
                * (Decimal(1) + pricing_noise + behavior.overrun_bias)
            ).to_integral_value(
                rounding=ROUND_HALF_UP
            )
        ),
    )
    return actual_fare, actual_duration


def simulate_transactions(config: SimulationConfig) -> SimulationDataset:
    """Generate valid, reproducible context/outcome pairs from one configuration."""

    rng = Random(config.seed)
    profiles = config.profiles_by_city
    records: list[SimulationRecord] = []
    for index in range(1, config.transaction_count + 1):
        city = _weighted_city(rng, config.city_weights)
        profile = profiles[city]
        timestamp = _timestamp(rng, config)
        distance_km = _distance(rng, profile, config.fare_model)
        duration = _estimated_duration_minutes(
            rng, distance_km, profile, timestamp
        )
        surge = _surge_multiplier(rng, profile, timestamp, config.fare_model)
        estimated_paise = _fare_paise(
            distance_km,
            duration,
            surge,
            config.fare_model,
            ROUND_CEILING,
        )
        if config.customer_behavior_enabled:
            customer_id = f"C{rng.randrange(config.customer_pool_size) + 1:04d}"
            customer_behavior = _customer_behavior(config.seed, customer_id)
        else:
            customer_id = ""
            customer_behavior = None
        actual_paise, actual_duration = _actual_fare_and_duration(
            rng,
            distance_km,
            duration,
            surge,
            timestamp,
            profile,
            config.fare_model,
            customer_behavior,
        )
        if not config.customer_behavior_enabled:
            customer_id = f"C{rng.randrange(config.customer_pool_size) + 1:04d}"
        transaction_id = f"SIM-{index:06d}"
        context = RideTransactionContext(
            transaction_id=transaction_id,
            customer_id=customer_id,
            estimated_amount=Money(amount_paise=estimated_paise),
            city=city,
            distance_km=distance_km,
            estimated_duration_minutes=duration,
            surge_multiplier=surge,
            timestamp=timestamp,
        )
        outcome = RideTransactionOutcome(
            transaction_id=transaction_id,
            actual_amount=Money(amount_paise=actual_paise),
            completed_at=timestamp + timedelta(minutes=actual_duration),
        )
        records.append(SimulationRecord(transaction=context, outcome=outcome))
    return SimulationDataset(config=config, records=tuple(records))
