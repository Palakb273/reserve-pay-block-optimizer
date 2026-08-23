"""Transparent synthetic city and time-band assumptions for simulation only."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.types import SupportedCity


def _finite_positive(value: object, field: str) -> list[ValidationIssue]:
    if not isinstance(value, Decimal) or not value.is_finite():
        return [
            ValidationIssue(field, "invalid_number", f"{field} must be a finite Decimal.")
        ]
    if value <= 0:
        return [
            ValidationIssue(field, "must_be_positive", f"{field} must be positive.")
        ]
    return []


def _probability(value: object, field: str) -> list[ValidationIssue]:
    if not isinstance(value, Decimal) or not value.is_finite():
        return [
            ValidationIssue(field, "invalid_number", f"{field} must be a finite Decimal.")
        ]
    if value < 0 or value > 1:
        return [
            ValidationIssue(
                field,
                "invalid_probability",
                f"{field} must be between 0 and 1 inclusive.",
            )
        ]
    return []


@dataclass(frozen=True, slots=True)
class CitySimulationProfile:
    """A synthetic assumption set, not measured city or provider statistics."""

    city: SupportedCity
    typical_distance_km: Decimal
    distance_spread_km: Decimal
    average_speed_kmph: Decimal
    traffic_variation_ratio: Decimal
    route_variation_ratio: Decimal
    base_surge_probability: Decimal

    def __post_init__(self) -> None:
        issues: list[ValidationIssue] = []
        if not isinstance(self.city, SupportedCity):
            issues.append(
                ValidationIssue("city", "unsupported_city", "Profile city is not supported.")
            )
        for field in (
            "typical_distance_km",
            "distance_spread_km",
            "average_speed_kmph",
        ):
            issues.extend(_finite_positive(getattr(self, field), field))
        for field in ("traffic_variation_ratio", "route_variation_ratio"):
            issues.extend(_probability(getattr(self, field), field))
        issues.extend(
            _probability(self.base_surge_probability, "base_surge_probability")
        )
        if issues:
            raise DomainValidationError(issues)


class TimeBand(StrEnum):
    LOW_DEMAND = "low_demand"
    NORMAL_DAYTIME = "normal_daytime"
    MORNING_PEAK = "morning_peak"
    EVENING_PEAK = "evening_peak"


@dataclass(frozen=True, slots=True)
class TimeBandProfile:
    traffic_factor: Decimal
    uncertainty_multiplier: Decimal
    surge_probability_multiplier: Decimal


TIME_BAND_PROFILES: dict[TimeBand, TimeBandProfile] = {
    TimeBand.LOW_DEMAND: TimeBandProfile(
        traffic_factor=Decimal("0.85"),
        uncertainty_multiplier=Decimal("0.80"),
        surge_probability_multiplier=Decimal("0.50"),
    ),
    TimeBand.NORMAL_DAYTIME: TimeBandProfile(
        traffic_factor=Decimal("1.00"),
        uncertainty_multiplier=Decimal("1.00"),
        surge_probability_multiplier=Decimal("1.00"),
    ),
    TimeBand.MORNING_PEAK: TimeBandProfile(
        traffic_factor=Decimal("1.30"),
        uncertainty_multiplier=Decimal("1.30"),
        surge_probability_multiplier=Decimal("1.80"),
    ),
    TimeBand.EVENING_PEAK: TimeBandProfile(
        traffic_factor=Decimal("1.40"),
        uncertainty_multiplier=Decimal("1.40"),
        surge_probability_multiplier=Decimal("2.00"),
    ),
}


# Every value below is a synthetic simulation assumption. The relative
# differences create learnable variation; they are not production statistics.
DEFAULT_CITY_PROFILES: tuple[CitySimulationProfile, ...] = (
    CitySimulationProfile(
        SupportedCity.DELHI,
        Decimal("10.0"), Decimal("6.0"), Decimal("25.0"),
        Decimal("0.09"), Decimal("0.045"), Decimal("0.09"),
    ),
    CitySimulationProfile(
        SupportedCity.MUMBAI,
        Decimal("9.0"), Decimal("5.0"), Decimal("22.0"),
        Decimal("0.13"), Decimal("0.050"), Decimal("0.12"),
    ),
    CitySimulationProfile(
        SupportedCity.BENGALURU,
        Decimal("11.0"), Decimal("7.0"), Decimal("20.0"),
        Decimal("0.16"), Decimal("0.060"), Decimal("0.14"),
    ),
    CitySimulationProfile(
        SupportedCity.HYDERABAD,
        Decimal("10.0"), Decimal("6.0"), Decimal("27.0"),
        Decimal("0.10"), Decimal("0.045"), Decimal("0.10"),
    ),
    CitySimulationProfile(
        SupportedCity.PUNE,
        Decimal("8.0"), Decimal("5.0"), Decimal("25.0"),
        Decimal("0.11"), Decimal("0.050"), Decimal("0.10"),
    ),
    CitySimulationProfile(
        SupportedCity.CHENNAI,
        Decimal("10.0"), Decimal("6.0"), Decimal("26.0"),
        Decimal("0.10"), Decimal("0.045"), Decimal("0.09"),
    ),
    CitySimulationProfile(
        SupportedCity.KOLKATA,
        Decimal("8.0"), Decimal("5.0"), Decimal("23.0"),
        Decimal("0.12"), Decimal("0.050"), Decimal("0.10"),
    ),
)


def time_band_for_hour(hour: int) -> TimeBand:
    if 7 <= hour <= 10:
        return TimeBand.MORNING_PEAK
    if 17 <= hour <= 21:
        return TimeBand.EVENING_PEAK
    if 11 <= hour <= 16:
        return TimeBand.NORMAL_DAYTIME
    return TimeBand.LOW_DEMAND

