"""Strict HTTP request schemas; authoritative money remains integer paise."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    estimated_amount_paise: int = Field(default=65_000, gt=0)
    city: CityName = "hyderabad"
    distance_km: Decimal = Field(default=Decimal("18.4"), ge=0)
    estimated_duration_minutes: int = Field(default=42, ge=0)
    surge_multiplier: Decimal = Field(default=Decimal("1.18"), gt=0)
    timestamp: datetime = datetime.fromisoformat("2027-01-15T18:30:00+05:30")
    customer_profile: CustomerProfileName = "stable_history"
    risk_profile: RiskProfileName = "balanced"


class WhatIfOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    distance_km: Decimal | None = Field(default=None, ge=0)
    estimated_duration_minutes: int | None = Field(default=None, ge=0)
    surge_multiplier: Decimal | None = Field(default=None, gt=0)
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
