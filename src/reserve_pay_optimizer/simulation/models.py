"""Typed simulation records, datasets, and descriptive diagnostics."""

from dataclasses import dataclass
from decimal import Decimal

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.simulation.config import SimulationConfig

GENERATOR_ID = "india_mobility_v1"


@dataclass(frozen=True, slots=True)
class SimulationRecord:
    transaction: RideTransactionContext
    outcome: RideTransactionOutcome

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction": {
                "transaction_id": self.transaction.transaction_id,
                "customer_id": self.transaction.customer_id,
                "estimated_amount_paise": self.transaction.estimated_amount.amount_paise,
                "city": self.transaction.city.value,
                "distance_km": float(self.transaction.distance_km),
                "estimated_duration_minutes": self.transaction.estimated_duration_minutes,
                "surge_multiplier": float(self.transaction.surge_multiplier),
                "timestamp": self.transaction.timestamp.isoformat(),
            },
            "outcome": {
                "transaction_id": self.outcome.transaction_id,
                "actual_amount_paise": self.outcome.actual_amount.amount_paise,
                "completed_at": self.outcome.completed_at.isoformat(),
            },
        }


@dataclass(frozen=True, slots=True)
class SimulationDiagnostics:
    transaction_count: int
    unique_customer_count: int
    city_counts: tuple[tuple[str, int], ...]
    average_estimated_amount: Money
    average_actual_amount: Money
    actual_above_estimate_rate: Decimal
    actual_below_estimate_rate: Decimal
    actual_equal_estimate_rate: Decimal
    actual_near_estimate_rate: Decimal
    average_absolute_difference: Money
    surge_frequency: Decimal
    near_estimate_ratio: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "transaction_count": self.transaction_count,
            "unique_customer_count": self.unique_customer_count,
            "city_counts": dict(self.city_counts),
            "average_estimated_amount_paise": self.average_estimated_amount.amount_paise,
            "average_actual_amount_paise": self.average_actual_amount.amount_paise,
            "actual_above_estimate_rate": format_ratio(
                self.actual_above_estimate_rate
            ),
            "actual_below_estimate_rate": format_ratio(
                self.actual_below_estimate_rate
            ),
            "actual_equal_estimate_rate": format_ratio(
                self.actual_equal_estimate_rate
            ),
            "actual_near_estimate_rate": format_ratio(
                self.actual_near_estimate_rate
            ),
            "average_absolute_difference_paise": self.average_absolute_difference.amount_paise,
            "surge_frequency": format_ratio(self.surge_frequency),
            "near_estimate_ratio": format_ratio(self.near_estimate_ratio),
        }


@dataclass(frozen=True, slots=True)
class SimulationDataset:
    config: SimulationConfig
    records: tuple[SimulationRecord, ...]

    @property
    def transactions(self) -> tuple[RideTransactionContext, ...]:
        return tuple(record.transaction for record in self.records)

    @property
    def outcomes(self) -> tuple[RideTransactionOutcome, ...]:
        return tuple(record.outcome for record in self.records)

    def to_dict(self) -> dict[str, object]:
        from reserve_pay_optimizer.simulation.diagnostics import summarize_simulation

        diagnostics = summarize_simulation(
            self.records, self.config.fare_model.near_estimate_ratio
        )
        fare = self.config.fare_model
        return {
            "metadata": {
                "generator": GENERATOR_ID,
                "seed": self.config.seed,
                "transaction_count": self.config.transaction_count,
                "customer_pool_size": self.config.customer_pool_size,
                "start_datetime": self.config.start_datetime.isoformat(),
                "end_datetime": self.config.end_datetime.isoformat(),
                "city_weights": {
                    city.value: weight for city, weight in self.config.city_weights
                },
                "fare_model": {
                    "base_fare_paise": fare.base_fare_paise,
                    "distance_rate_paise_per_km": format(
                        fare.distance_rate_paise_per_km, "f"
                    ),
                    "duration_rate_paise_per_minute": format(
                        fare.duration_rate_paise_per_minute, "f"
                    ),
                    "minimum_distance_km": format(fare.minimum_distance_km, "f"),
                    "maximum_distance_km": format(fare.maximum_distance_km, "f"),
                    "maximum_surge_multiplier": format(
                        fare.maximum_surge_multiplier, "f"
                    ),
                    "pricing_noise_ratio": format(fare.pricing_noise_ratio, "f"),
                    "near_estimate_ratio": format(fare.near_estimate_ratio, "f"),
                },
                "city_profiles": [
                    {
                        "city": profile.city.value,
                        "typical_distance_km": format(
                            profile.typical_distance_km, "f"
                        ),
                        "distance_spread_km": format(
                            profile.distance_spread_km, "f"
                        ),
                        "average_speed_kmph": format(
                            profile.average_speed_kmph, "f"
                        ),
                        "traffic_variation_ratio": format(
                            profile.traffic_variation_ratio, "f"
                        ),
                        "route_variation_ratio": format(
                            profile.route_variation_ratio, "f"
                        ),
                        "base_surge_probability": format(
                            profile.base_surge_probability, "f"
                        ),
                        "basis": "synthetic_simulation_assumption",
                    }
                    for profile in self.config.city_profiles
                ],
                "diagnostics": diagnostics.to_dict(),
            },
            "records": [record.to_dict() for record in self.records],
        }

