"""Persistence-contract tests that do not require a live MongoDB server."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
import unittest

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.personalization.history import (
    calculate_customer_history_features_from_ratios,
)
from reserve_pay_optimizer.web.errors import DashboardError
from reserve_pay_optimizer.web.schemas import CompletedRideRequest
from reserve_pay_optimizer.web.schemas import OptimizeRequest
from reserve_pay_optimizer.web.services import DashboardService, DashboardSettings
from reserve_pay_optimizer.web.storage import InMemoryApplicationStore


ROOT = Path(__file__).resolve().parents[1]


class DatabaseLikeTestStore(InMemoryApplicationStore):
    @property
    def backend(self) -> str:
        return "mongodb"

    def features_for(self, transaction: RideTransactionContext):
        return calculate_customer_history_features_from_ratios(
            transaction.customer_id, ()
        )


class ApplicationStorageTests(unittest.TestCase):
    def test_optimization_and_agent_runs_are_retrievable(self) -> None:
        store = InMemoryApplicationStore()
        run_id = store.save_optimization(
            "T-1", "C-1", {"amount": 100}, {"recommended": 120}
        )
        optimization = store.get_optimization(run_id)
        self.assertIsNotNone(optimization)
        assert optimization is not None
        self.assertEqual(optimization["customer_id"], "C-1")

        store.save_agent_run("agent-1", {"run_id": "agent-1", "decision": {}})
        self.assertEqual(store.get_agent_run("agent-1")["run_id"], "agent-1")  # type: ignore[index]

    def test_completed_ride_ingestion_is_idempotent_and_conflict_safe(self) -> None:
        store = InMemoryApplicationStore()
        ride = {"transaction_id": "T-1", "actual_amount_paise": 120}
        self.assertEqual(store.save_completed_ride(ride), "created")
        self.assertEqual(store.save_completed_ride(dict(ride)), "replayed")
        with self.assertRaises(DashboardError) as raised:
            store.save_completed_ride(
                {"transaction_id": "T-1", "actual_amount_paise": 121}
            )
        self.assertEqual(raised.exception.code, "completed_ride_conflict")

    def test_completed_ride_schema_rejects_temporal_leakage_shape(self) -> None:
        with self.assertRaises(ValueError):
            CompletedRideRequest(
                transaction_id="T-1",
                customer_id="C-1",
                estimated_amount_paise=100,
                actual_amount_paise=120,
                city="hyderabad",
                distance_km=Decimal("1"),
                estimated_duration_minutes=5,
                surge_multiplier=Decimal("1"),
                timestamp=datetime(2027, 1, 1, 12, tzinfo=UTC),
                completed_at=datetime(2027, 1, 1, 11, tzinfo=UTC),
            )

    def test_database_history_uses_the_canonical_formulas(self) -> None:
        features = calculate_customer_history_features_from_ratios(
            "C-1", (Decimal("1.0"), Decimal("1.2"))
        )
        self.assertEqual(features.completed_ride_count, 2)
        self.assertEqual(features.mean_fare_ratio, Decimal("1.1"))
        self.assertEqual(features.overrun_rate, Decimal("0.5"))

    def test_mongodb_mode_uses_real_customer_id_and_persists_run(self) -> None:
        service = DashboardService(
            DashboardSettings(
                repository_root=ROOT,
                data_mode="mongodb",
                ingest_api_key="x" * 32,
            ),
            store=DatabaseLikeTestStore(),
        )
        result = service.optimize(OptimizeRequest(customer_id="C-PRODUCTION-1"))
        self.assertEqual(result["transaction"]["customer_id"], "C-PRODUCTION-1")  # type: ignore[index]
        self.assertEqual(result["prediction"]["mode"], "base")  # type: ignore[index]
        self.assertEqual(result["meta"]["data_mode"], "mongodb")  # type: ignore[index]
        run_id = result["meta"]["run_id"]  # type: ignore[index]
        self.assertIsNotNone(service.optimization_run(run_id))

        with self.assertRaises(DashboardError) as missing_customer:
            service.optimize(OptimizeRequest())
        self.assertEqual(missing_customer.exception.code, "customer_id_required")


if __name__ == "__main__":
    unittest.main()
