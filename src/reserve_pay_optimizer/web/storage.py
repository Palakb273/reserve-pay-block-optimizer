"""Pluggable application persistence for demo and MongoDB deployments."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any, Protocol
from uuid import uuid4

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.personalization.history import (
    calculate_customer_history_features_from_ratios,
)
from reserve_pay_optimizer.personalization.models import CustomerHistoryFeatures
from reserve_pay_optimizer.web.errors import DashboardError


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _mongo_safe(value: Any) -> Any:
    """Convert API/domain values to predictable BSON-safe primitives."""

    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, dict):
        return {str(key): _mongo_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mongo_safe(item) for item in value]
    return value


def _fingerprint(payload: dict[str, Any]) -> str:
    from hashlib import sha256

    canonical = json.dumps(
        _mongo_safe(payload),
        default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item),
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


class ApplicationStore(Protocol):
    """Persistence boundary used by the HTTP orchestration layer."""

    @property
    def backend(self) -> str: ...

    def ready(self) -> bool: ...

    def close(self) -> None: ...

    def save_optimization(
        self,
        transaction_id: str,
        customer_id: str,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> str: ...

    def get_optimization(self, run_id: str) -> dict[str, Any] | None: ...

    def save_agent_run(self, run_id: str, result: dict[str, Any]) -> None: ...

    def get_agent_run(self, run_id: str) -> dict[str, Any] | None: ...

    def save_completed_ride(self, ride: dict[str, Any]) -> str: ...


class InMemoryApplicationStore:
    """Process-local store used only by the checked-in demo and unit tests."""

    def __init__(self) -> None:
        self._optimizations: dict[str, dict[str, Any]] = {}
        self._agent_runs: dict[str, dict[str, Any]] = {}
        self._rides: dict[str, dict[str, Any]] = {}

    @property
    def backend(self) -> str:
        return "memory"

    def ready(self) -> bool:
        return True

    def close(self) -> None:
        return None

    def save_optimization(
        self,
        transaction_id: str,
        customer_id: str,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        run_id = f"opt_{uuid4().hex}"
        self._optimizations[run_id] = deepcopy(
            {
                "run_id": run_id,
                "transaction_id": transaction_id,
                "customer_id": customer_id,
                "request": request,
                "result": result,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        return run_id

    def get_optimization(self, run_id: str) -> dict[str, Any] | None:
        value = self._optimizations.get(run_id)
        return deepcopy(value) if value is not None else None

    def save_agent_run(self, run_id: str, result: dict[str, Any]) -> None:
        self._agent_runs[run_id] = deepcopy(result)

    def get_agent_run(self, run_id: str) -> dict[str, Any] | None:
        value = self._agent_runs.get(run_id)
        return deepcopy(value) if value is not None else None

    def save_completed_ride(self, ride: dict[str, Any]) -> str:
        transaction_id = str(ride["transaction_id"])
        existing = self._rides.get(transaction_id)
        if existing is not None:
            if _fingerprint(existing) != _fingerprint(ride):
                raise DashboardError(
                    "completed_ride_conflict",
                    "This transaction ID already exists with different ride data.",
                    status_code=409,
                )
            return "replayed"
        self._rides[transaction_id] = deepcopy(ride)
        return "created"


class MongoApplicationStore:
    """MongoDB-backed application store and customer-history provider."""

    def __init__(self, uri: str, database: str, *, timeout_ms: int = 5_000) -> None:
        if not uri:
            raise DashboardError(
                "mongodb_configuration_error",
                "MONGODB_URI is required when RPO_DATA_MODE=mongodb.",
                status_code=503,
            )
        try:
            from pymongo import ASCENDING, DESCENDING, MongoClient
        except ImportError as exc:
            raise DashboardError(
                "mongodb_driver_unavailable",
                "Install the project with the 'mongodb' dependency group.",
                status_code=503,
            ) from exc

        try:
            self._client = MongoClient(
                uri,
                appname="reserve-pay-block-optimizer",
                connectTimeoutMS=timeout_ms,
                serverSelectionTimeoutMS=timeout_ms,
                tz_aware=True,
            )
            self._database = self._client[database]
            self._client.admin.command("ping")
            self._optimizations = self._database["optimization_runs"]
            self._agent_runs = self._database["agent_runs"]
            self._rides = self._database["completed_rides"]
            self._optimizations.create_index("run_id", unique=True)
            self._optimizations.create_index(
                [("transaction_id", ASCENDING), ("created_at", DESCENDING)]
            )
            self._agent_runs.create_index("run_id", unique=True)
            self._rides.create_index("transaction_id", unique=True)
            self._rides.create_index(
                [("customer_id", ASCENDING), ("completed_at", ASCENDING)]
            )
        except DashboardError:
            raise
        except Exception as exc:
            raise DashboardError(
                "mongodb_unavailable",
                "MongoDB could not be reached or initialized.",
                status_code=503,
            ) from exc

    @property
    def backend(self) -> str:
        return "mongodb"

    def ready(self) -> bool:
        try:
            self._client.admin.command("ping")
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _without_id(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        value.pop("_id", None)
        return value

    def save_optimization(
        self,
        transaction_id: str,
        customer_id: str,
        request: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        run_id = f"opt_{uuid4().hex}"
        try:
            self._optimizations.insert_one(
                _mongo_safe(
                    {
                        "run_id": run_id,
                        "transaction_id": transaction_id,
                        "customer_id": customer_id,
                        "request": request,
                        "result": result,
                        "created_at": datetime.now(UTC),
                    }
                )
            )
        except Exception as exc:
            raise DashboardError(
                "optimization_write_failed",
                "The optimization result could not be persisted.",
                status_code=503,
            ) from exc
        return run_id

    def get_optimization(self, run_id: str) -> dict[str, Any] | None:
        try:
            return self._without_id(
                self._optimizations.find_one({"run_id": run_id})
            )
        except Exception as exc:
            raise DashboardError(
                "optimization_read_failed",
                "The optimization result store is unavailable.",
                status_code=503,
            ) from exc

    def save_agent_run(self, run_id: str, result: dict[str, Any]) -> None:
        try:
            self._agent_runs.replace_one(
                {"run_id": run_id},
                _mongo_safe(
                    {
                        "run_id": run_id,
                        "result": result,
                        "created_at": datetime.now(UTC),
                    }
                ),
                upsert=True,
            )
        except Exception as exc:
            raise DashboardError(
                "agent_run_write_failed",
                "The agent run could not be persisted.",
                status_code=503,
            ) from exc

    def get_agent_run(self, run_id: str) -> dict[str, Any] | None:
        try:
            document = self._agent_runs.find_one({"run_id": run_id})
        except Exception as exc:
            raise DashboardError(
                "agent_run_read_failed",
                "The agent run store is unavailable.",
                status_code=503,
            ) from exc
        if document is None:
            return None
        return document.get("result")

    def save_completed_ride(self, ride: dict[str, Any]) -> str:
        safe = _mongo_safe(ride)
        safe["payload_fingerprint"] = _fingerprint(ride)
        safe["recorded_at"] = datetime.now(UTC)
        transaction_id = str(ride["transaction_id"])
        try:
            existing = self._rides.find_one({"transaction_id": transaction_id})
        except Exception as exc:
            raise DashboardError(
                "completed_ride_read_failed",
                "The completed-ride store is unavailable.",
                status_code=503,
            ) from exc
        if existing is not None:
            if existing.get("payload_fingerprint") != safe["payload_fingerprint"]:
                raise DashboardError(
                    "completed_ride_conflict",
                    "This transaction ID already exists with different ride data.",
                    status_code=409,
                )
            return "replayed"
        try:
            self._rides.insert_one(safe)
        except Exception as exc:
            try:
                existing = self._rides.find_one({"transaction_id": transaction_id})
            except Exception:
                existing = None
            if existing and existing.get("payload_fingerprint") == safe["payload_fingerprint"]:
                return "replayed"
            raise DashboardError(
                "completed_ride_write_failed",
                "The completed ride could not be stored.",
                status_code=503,
            ) from exc
        return "created"

    def features_for(self, transaction: RideTransactionContext) -> CustomerHistoryFeatures:
        try:
            cursor = self._rides.find(
                {
                    "customer_id": transaction.customer_id,
                    "transaction_id": {"$ne": transaction.transaction_id},
                    "completed_at": {"$lt": _utc(transaction.timestamp)},
                },
                {"_id": 0, "estimated_amount_paise": 1, "actual_amount_paise": 1},
            ).sort([("completed_at", 1), ("transaction_id", 1)])
            ratios = tuple(
                Decimal(int(item["actual_amount_paise"]))
                / Decimal(int(item["estimated_amount_paise"]))
                for item in cursor
            )
        except Exception as exc:
            raise DashboardError(
                "customer_history_read_failed",
                "Customer history could not be read from MongoDB.",
                status_code=503,
            ) from exc
        return calculate_customer_history_features_from_ratios(
            transaction.customer_id, ratios
        )
