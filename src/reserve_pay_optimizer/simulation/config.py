"""Typed, validated configuration for deterministic mobility simulation."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from reserve_pay_optimizer.config import INDIA_STANDARD_TIME
from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.types import SupportedCity
from reserve_pay_optimizer.simulation.profiles import (
    DEFAULT_CITY_PROFILES,
    CitySimulationProfile,
)


DEFAULT_CITY_WEIGHTS: tuple[tuple[SupportedCity, int], ...] = tuple(
    (city, 1) for city in SupportedCity
)


def _decimal_field(value: object, field: str) -> list[ValidationIssue]:
    if not isinstance(value, Decimal) or not value.is_finite():
        return [
            ValidationIssue(field, "invalid_number", f"{field} must be a finite Decimal.")
        ]
    return []


@dataclass(frozen=True, slots=True)
class FareModelConfig:
    """Synthetic fare constants shared by all city profiles."""

    base_fare_paise: int = 4500
    distance_rate_paise_per_km: Decimal = Decimal("1400")
    duration_rate_paise_per_minute: Decimal = Decimal("220")
    minimum_distance_km: Decimal = Decimal("0.8")
    maximum_distance_km: Decimal = Decimal("40.0")
    maximum_surge_multiplier: Decimal = Decimal("2.00")
    pricing_noise_ratio: Decimal = Decimal("0.0125")
    near_estimate_ratio: Decimal = Decimal("0.02")

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        if isinstance(self.base_fare_paise, bool) or not isinstance(
            self.base_fare_paise, int
        ):
            issues.append(
                ValidationIssue(
                    "base_fare_paise", "invalid_type", "base_fare_paise must be an integer."
                )
            )
        elif self.base_fare_paise <= 0:
            issues.append(
                ValidationIssue(
                    "base_fare_paise", "must_be_positive", "base_fare_paise must be positive."
                )
            )
        decimal_fields = (
            "distance_rate_paise_per_km",
            "duration_rate_paise_per_minute",
            "minimum_distance_km",
            "maximum_distance_km",
            "maximum_surge_multiplier",
            "pricing_noise_ratio",
            "near_estimate_ratio",
        )
        for field in decimal_fields:
            issues.extend(_decimal_field(getattr(self, field), field))
        if not issues:
            if self.distance_rate_paise_per_km <= 0:
                issues.append(ValidationIssue("distance_rate_paise_per_km", "must_be_positive", "Distance rate must be positive."))
            if self.duration_rate_paise_per_minute <= 0:
                issues.append(ValidationIssue("duration_rate_paise_per_minute", "must_be_positive", "Duration rate must be positive."))
            if self.minimum_distance_km <= 0:
                issues.append(ValidationIssue("minimum_distance_km", "must_be_positive", "Minimum distance must be positive."))
            if self.maximum_distance_km <= self.minimum_distance_km:
                issues.append(ValidationIssue("maximum_distance_km", "invalid_range", "Maximum distance must exceed minimum distance."))
            if self.maximum_surge_multiplier < 1 or (
                Decimal(1) < self.maximum_surge_multiplier < Decimal("1.05")
            ):
                issues.append(ValidationIssue("maximum_surge_multiplier", "invalid_range", "Maximum surge must be 1.00 or at least 1.05."))
            for field in ("pricing_noise_ratio", "near_estimate_ratio"):
                value = getattr(self, field)
                if value < 0 or value > 1:
                    issues.append(ValidationIssue(field, "invalid_probability", f"{field} must be between 0 and 1."))
        if issues:
            raise DomainValidationError(issues)


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    transaction_count: int = 100
    seed: int = 42
    customer_pool_size: int = 25
    start_datetime: datetime = datetime(2026, 1, 1, tzinfo=INDIA_STANDARD_TIME)
    end_datetime: datetime = datetime(2026, 12, 31, 23, 59, 59, tzinfo=INDIA_STANDARD_TIME)
    city_weights: tuple[tuple[SupportedCity, int], ...] = DEFAULT_CITY_WEIGHTS
    city_profiles: tuple[CitySimulationProfile, ...] = DEFAULT_CITY_PROFILES
    fare_model: FareModelConfig = FareModelConfig()
    customer_behavior_enabled: bool = False

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        for field in ("transaction_count", "seed", "customer_pool_size"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int):
                issues.append(
                    ValidationIssue(field, "invalid_type", f"{field} must be an integer.")
                )
        if not isinstance(self.customer_behavior_enabled, bool):
            issues.append(
                ValidationIssue(
                    "customer_behavior_enabled",
                    "invalid_type",
                    "customer_behavior_enabled must be boolean.",
                )
            )
        if isinstance(self.transaction_count, int) and self.transaction_count <= 0:
            issues.append(
                ValidationIssue("transaction_count", "must_be_positive", "transaction_count must be positive.")
            )
        if isinstance(self.customer_pool_size, int) and self.customer_pool_size <= 0:
            issues.append(
                ValidationIssue("customer_pool_size", "must_be_positive", "customer_pool_size must be positive.")
            )
        for field in ("start_datetime", "end_datetime"):
            value = getattr(self, field)
            if not isinstance(value, datetime):
                issues.append(ValidationIssue(field, "invalid_type", f"{field} must be a datetime."))
            elif value.tzinfo is None or value.utcoffset() is None:
                issues.append(ValidationIssue(field, "timezone_required", f"{field} must include a UTC offset."))
        if (
            isinstance(self.start_datetime, datetime)
            and isinstance(self.end_datetime, datetime)
            and self.start_datetime.tzinfo is not None
            and self.end_datetime.tzinfo is not None
            and self.end_datetime < self.start_datetime
        ):
            issues.append(ValidationIssue("end_datetime", "invalid_range", "end_datetime cannot be before start_datetime."))

        if not isinstance(self.city_weights, tuple) or not self.city_weights:
            issues.append(ValidationIssue("city_weights", "invalid_weights", "city_weights must be a non-empty tuple."))
        else:
            seen_cities: set[SupportedCity] = set()
            for index, item in enumerate(self.city_weights):
                field = f"city_weights[{index}]"
                if not isinstance(item, tuple) or len(item) != 2:
                    issues.append(ValidationIssue(field, "invalid_weights", "Each city weight must be a (city, weight) pair."))
                    continue
                city, weight = item
                if not isinstance(city, SupportedCity):
                    issues.append(ValidationIssue(field, "unsupported_city", "City weight uses an unsupported city."))
                elif city in seen_cities:
                    issues.append(ValidationIssue(field, "duplicate_city", f"Duplicate city weight: {city.value}."))
                else:
                    seen_cities.add(city)
                if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
                    issues.append(ValidationIssue(field, "invalid_weight", "City weights must be positive integers."))

        profile_cities: list[SupportedCity] = []
        if not isinstance(self.city_profiles, tuple) or not self.city_profiles:
            issues.append(ValidationIssue("city_profiles", "missing_profiles", "At least one city profile is required."))
        else:
            for index, profile in enumerate(self.city_profiles):
                if not isinstance(profile, CitySimulationProfile):
                    issues.append(ValidationIssue(f"city_profiles[{index}]", "invalid_type", "Each city profile must be CitySimulationProfile."))
                    continue
                profile_cities.append(profile.city)
                if isinstance(self.fare_model, FareModelConfig) and not (
                    self.fare_model.minimum_distance_km
                    <= profile.typical_distance_km
                    <= self.fare_model.maximum_distance_km
                ):
                    issues.append(ValidationIssue(f"city_profiles[{index}]", "invalid_range", "Typical distance must be inside the fare-model distance range."))
            if len(profile_cities) != len(set(profile_cities)):
                issues.append(ValidationIssue("city_profiles", "duplicate_city", "City profiles must have unique cities."))
        weighted_cities = {
            city
            for city, _ in self.city_weights
            if isinstance(city, SupportedCity)
        } if isinstance(self.city_weights, tuple) and all(isinstance(item, tuple) and len(item) == 2 for item in self.city_weights) else set()
        missing_profiles = weighted_cities - set(profile_cities)
        for city in sorted(missing_profiles, key=lambda value: value.value):
            issues.append(ValidationIssue("city_profiles", "missing_profile", f"Missing simulation profile for {city.value}."))
        if not isinstance(self.fare_model, FareModelConfig):
            issues.append(ValidationIssue("fare_model", "invalid_type", "fare_model must be FareModelConfig."))
        if issues:
            raise DomainValidationError(issues)

    @property
    def profiles_by_city(self) -> dict[SupportedCity, CitySimulationProfile]:
        return {profile.city: profile for profile in self.city_profiles}
