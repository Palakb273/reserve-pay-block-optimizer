"""Strict HTTP request schemas; authoritative money remains integer paise."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from reserve_pay_optimizer.config import (
    MAX_AMOUNT_PAISE,
    MAX_MOBILITY_DISTANCE_KM,
    MAX_MOBILITY_DURATION_MINUTES,
    MAX_MOBILITY_SURGE_MULTIPLIER,
)

CityName = Literal[
    "delhi",
    "mumbai",
    "bengaluru",
    "hyderabad",
    "pune",
    "chennai",
    "kolkata",
]
CustomerProfileName = Literal["cold_start", "stable_history", "overrun_prone"]
RiskProfileName = Literal["aggressive", "balanced", "conservative"]
TrafficLevel = Literal["light", "normal", "heavy", "severe"]


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(default="DASHBOARD-DEMO-001", min_length=1, max_length=100)
    estimated_amount_paise: StrictInt = Field(
        default=65_000, gt=0, le=MAX_AMOUNT_PAISE
    )
    city: CityName = "hyderabad"
    distance_km: Decimal = Field(
        default=Decimal("18.4"), ge=0, le=MAX_MOBILITY_DISTANCE_KM
    )
    estimated_duration_minutes: StrictInt = Field(
        default=42, ge=0, le=MAX_MOBILITY_DURATION_MINUTES
    )
    surge_multiplier: Decimal = Field(
        default=Decimal("1.18"), gt=0, le=MAX_MOBILITY_SURGE_MULTIPLIER
    )
    timestamp: datetime = datetime.fromisoformat("2027-01-15T18:30:00+05:30")
    customer_id: str | None = Field(default=None, min_length=1, max_length=100)
    customer_profile: CustomerProfileName = "stable_history"
    risk_profile: RiskProfileName = "balanced"


class WhatIfOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_km: Decimal | None = Field(
        default=None, ge=0, le=MAX_MOBILITY_DISTANCE_KM
    )
    estimated_duration_minutes: StrictInt | None = Field(
        default=None, ge=0, le=MAX_MOBILITY_DURATION_MINUTES
    )
    surge_multiplier: Decimal | None = Field(
        default=None, gt=0, le=MAX_MOBILITY_SURGE_MULTIPLIER
    )
    traffic_level: TrafficLevel | None = None
    customer_profile: CustomerProfileName | None = None
    risk_profile: RiskProfileName | None = None


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base: OptimizeRequest
    overrides: WhatIfOverrides


class MockAuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction: OptimizeRequest
    idempotency_key: str = Field(min_length=1, max_length=200)
    simulate_failure: bool = False


class DynamicDemoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_profile: RiskProfileName = "balanced"
    fail_first_increase: bool = False


class AgentDecideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction: OptimizeRequest = Field(default_factory=OptimizeRequest)
    risk_profile: RiskProfileName | None = None
    customer_profile: CustomerProfileName | None = None


class CompletedRideRequest(BaseModel):
    """A completed production ride used for future, leakage-safe personalization."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    estimated_amount_paise: StrictInt = Field(gt=0, le=MAX_AMOUNT_PAISE)
    actual_amount_paise: StrictInt = Field(gt=0, le=MAX_AMOUNT_PAISE)
    city: CityName
    distance_km: Decimal = Field(ge=0, le=MAX_MOBILITY_DISTANCE_KM)
    estimated_duration_minutes: StrictInt = Field(
        ge=0, le=MAX_MOBILITY_DURATION_MINUTES
    )
    surge_multiplier: Decimal = Field(
        gt=0, le=MAX_MOBILITY_SURGE_MULTIPLIER
    )
    timestamp: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> "CompletedRideRequest":
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must include a UTC offset")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must include a UTC offset")
        if self.completed_at < self.timestamp:
            raise ValueError("completed_at cannot be before timestamp")
        return self
