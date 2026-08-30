"""Dashboard orchestration that delegates all financial logic to existing services."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from time import perf_counter

from reserve_pay_optimizer import __version__
from reserve_pay_optimizer.dynamic.serialization import parse_dynamic_scenario
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.explainability.models import ExplanationLevel
from reserve_pay_optimizer.explainability.service import ExplanationService
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.personalization.history import InMemoryCustomerHistoryProvider
from reserve_pay_optimizer.personalization.persistence import load_personalized_artifact
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.prediction.persistence import load_predictor_artifact
from reserve_pay_optimizer.reserve_pay.errors import ReservePayError
from reserve_pay_optimizer.reserve_pay.mock_provider import (
    MockFailureConfig,
    MockReserveProvider,
)
from reserve_pay_optimizer.reserve_pay.service import ReservePayService
from reserve_pay_optimizer.services.evaluation_input import parse_evaluation_dataset
from reserve_pay_optimizer.services.mobility_validation import parse_mobility_transaction
from reserve_pay_optimizer.web.errors import DashboardError
from reserve_pay_optimizer.web.schemas import (
    DynamicDemoRequest,
    MockAuthorizeRequest,
    OptimizeRequest,
    WhatIfRequest,
)

TRAFFIC_DURATION_MULTIPLIERS = {
    "light": Decimal("0.82"),
    "normal": Decimal("1.00"),
    "heavy": Decimal("1.28"),
    "severe": Decimal("1.55"),
}


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class DashboardSettings:
    repository_root: Path = _repository_root()
    base_model_path: Path | None = None
    personalized_model_path: Path | None = None
    evidence_path: Path | None = None

    @property
    def resolved_base_model(self) -> Path:
        return self.base_model_path or self.repository_root / "artifacts/prediction/fare_distribution_v1"

    @property
    def resolved_personalized_model(self) -> Path:
        return self.personalized_model_path or self.repository_root / "artifacts/prediction/fare_distribution_personalized_v1"

    @property
    def resolved_evidence(self) -> Path:
        return self.evidence_path or self.repository_root / "demo/evidence/dashboard_evidence.json"


class DashboardService:
    """Long-lived model holder and adapter for interactive dashboard requests."""

    _PROFILE_CUSTOMERS = {
        "cold_start": "C-COLD-START",
        "stable_history": "C-STABLE",
        "overrun_prone": "C-OVERRUN",
    }

    def __init__(self, settings: DashboardSettings | None = None) -> None:
        self.settings = settings or DashboardSettings()
        try:
            self.base_artifact = load_predictor_artifact(
                self.settings.resolved_base_model
            )
            self.personalized_artifact = load_personalized_artifact(
                self.settings.resolved_personalized_model
            )
        except Exception as exc:
            raise DashboardError(
                "model_artifact_unavailable",
                "Trusted dashboard model artifacts could not be loaded.",
                status_code=503,
            ) from exc
        self.predictors = self._load_demo_predictors()
        self.optimizer = ReserveBlockOptimizer()
        self.policy_optimizer = PolicyConstrainedOptimizer(self.optimizer)
        self.explanations = ExplanationService()
        self.mock_provider = MockReserveProvider()
        self.reserve_service = ReservePayService(self.mock_provider)
        self.dynamic_record, self.dynamic_history = self._load_dynamic_scenario()
        self.dynamic_predictor = PersonalizedFarePredictor(
            self.base_artifact.model,
            self.personalized_artifact.model,
            self.dynamic_history,
        )
        self.dynamic_service = DynamicRideService(self.dynamic_predictor, self.optimizer)

    def _read_json(self, relative: str) -> object:
        path = self.settings.repository_root / relative
        try:
            return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
        except (OSError, json.JSONDecodeError) as exc:
            raise DashboardError(
                "demo_fixture_unavailable",
                "A checked-in dashboard demo fixture could not be loaded.",
                status_code=503,
            ) from exc

    def _predictor(self, contexts, outcomes) -> PersonalizedFarePredictor:
        return PersonalizedFarePredictor(
            self.base_artifact.model,
            self.personalized_artifact.model,
            InMemoryCustomerHistoryProvider(tuple(contexts), tuple(outcomes)),
        )

    def _load_demo_predictors(self) -> dict[str, PersonalizedFarePredictor]:
        empty = self._predictor((), ())
        comparison = self._read_json("examples/personalization_comparison.json")
        if not isinstance(comparison, dict) or not isinstance(comparison.get("customers"), list):
            raise DashboardError("invalid_demo_fixture", "Customer demo fixture is invalid.", status_code=503)
        predictors = {"cold_start": empty}
        for customer in comparison["customers"]:
            if not isinstance(customer, dict):
                continue
            label = customer.get("label")
            profile = (
                "stable_history"
                if label == "stable_history_customer"
                else "overrun_prone" if label == "overrun_prone_history_customer" else None
            )
            history = customer.get("history")
            if profile and isinstance(history, dict):
                contexts, outcomes = parse_evaluation_dataset(history)
                predictors[profile] = self._predictor(contexts, outcomes)
        if set(predictors) != set(self._PROFILE_CUSTOMERS):
            raise DashboardError("invalid_demo_fixture", "Customer demo profiles are incomplete.", status_code=503)
        return predictors

    def _load_dynamic_scenario(self):
        payload = self._read_json("examples/dynamic_reoptimization.json")
        record, contexts, outcomes = parse_dynamic_scenario(payload)  # type: ignore[arg-type]
        return record, InMemoryCustomerHistoryProvider(contexts, outcomes)

    def _context(self, request: OptimizeRequest):
        customer_id = self._PROFILE_CUSTOMERS[request.customer_profile]
        return parse_mobility_transaction(
            {
                "transaction_id": request.transaction_id,
                "customer_id": customer_id,
                "estimated_amount_paise": request.estimated_amount_paise,
                "city": request.city,
                "distance_km": request.distance_km,
                "estimated_duration_minutes": request.estimated_duration_minutes,
                "surge_multiplier": request.surge_multiplier,
                "timestamp": request.timestamp.isoformat(),
            }
        )

    def optimize(self, request: OptimizeRequest) -> dict[str, object]:
        started = perf_counter()
        context = self._context(request)
        predictor = self.predictors[request.customer_profile]
        prediction = predictor.predict(context)
        policy = ReserveRiskPolicy.for_profile(RiskProfile(request.risk_profile))
        optimization = self.policy_optimizer.optimize(context, prediction, policy)
        concise = self.explanations.explain_reserve_decision(
            context, prediction, optimization, ExplanationLevel.CONCISE
        )
        detailed = self.explanations.explain_reserve_decision(
            context, prediction, optimization, ExplanationLevel.DETAILED
        )
        quantiles = {
            key: prediction.amount_for_quantile(key).amount_paise
            for key in ("0.05", "0.50", "0.90", "0.95", "0.97", "0.99")
        }
        facts = detailed.facts.facts_dict()
        return {
            "transaction": context.to_dict(),
            "prediction": {
                "mode": prediction.prediction_mode,
                "history_count": prediction.history_count,
                "model_version": prediction.model_version,
                "quantiles_paise": quantiles,
                "modeled_range": {
                    "lower_quantile": "0.05",
                    "upper_quantile": "0.95",
                    "lower_amount_paise": quantiles["0.05"],
                    "upper_amount_paise": quantiles["0.95"],
                    "label": "Modeled Q05–Q95 interval",
                },
            },
            "decision": optimization.to_dict(include_candidates=False),
            "policy": {
                "profile": policy.profile.value,
                "target_collection_probability": str(policy.target_collection_probability),
            },
            "explanation": {
                "summary": concise.text,
                "details": detailed.text,
                "factors": facts["decision_factors"],
                "objective_components": facts["objective_components"],
                "candidate_comparison": facts["candidate_comparison"],
                "history_summary": facts["history_summary"],
                "explanation_id": detailed.facts.explanation_id,
            },
            "meta": {
                "project_version": __version__,
                "processing_ms": round((perf_counter() - started) * 1000, 3),
                "financial_logic_location": "python_backend",
            },
        }

    def what_if(self, request: WhatIfRequest) -> dict[str, object]:
        previous = self.optimize(request.base)
        overrides = request.overrides.model_dump(exclude_none=True)
        if "traffic_level" in overrides and "estimated_duration_minutes" not in overrides:
            multiplier = TRAFFIC_DURATION_MULTIPLIERS[str(overrides.pop("traffic_level"))]
            overrides["estimated_duration_minutes"] = int(
                (Decimal(request.base.estimated_duration_minutes) * multiplier).to_integral_value(
                    rounding=ROUND_HALF_UP
                )
            )
        else:
            overrides.pop("traffic_level", None)
        revised_request = request.base.model_copy(
            update={**overrides, "transaction_id": f"{request.base.transaction_id}-WHATIF"}
        )
        revised = self.optimize(revised_request)
        previous_decision = previous["decision"]
        revised_decision = revised["decision"]
        previous_prediction = previous["prediction"]
        revised_prediction = revised["prediction"]
        assert isinstance(previous_decision, dict) and isinstance(revised_decision, dict)
        assert isinstance(previous_prediction, dict) and isinstance(revised_prediction, dict)
        previous_quantiles = previous_prediction["quantiles_paise"]
        revised_quantiles = revised_prediction["quantiles_paise"]
        assert isinstance(previous_quantiles, dict) and isinstance(revised_quantiles, dict)
        return {
            "previous": previous,
            "revised": revised,
            "difference": {
                "recommended_block_paise": int(revised_decision["recommended_block_paise"]) - int(previous_decision["recommended_block_paise"]),
                "q97_paise": int(revised_quantiles["0.97"]) - int(previous_quantiles["0.97"]),
                "expected_excess_block_paise": int(revised_decision["expected_excess_block_paise"]) - int(previous_decision["expected_excess_block_paise"]),
            },
            "applied_overrides": {
                **{key: str(value) if isinstance(value, Decimal) else value for key, value in overrides.items()},
                "traffic_duration_mapping": (
                    "Traffic is represented only through projected duration; it is not a model feature."
                    if request.overrides.traffic_level
                    else None
                ),
            },
        }

    def authorize_mock(self, request: MockAuthorizeRequest) -> dict[str, object]:
        recommendation = self.optimize(request.transaction)
        decision = recommendation["decision"]
        assert isinstance(decision, dict)
        context = self._context(request.transaction)
        from reserve_pay_optimizer.domain.reserve import ReserveDecision
        from reserve_pay_optimizer.domain.money import Money

        reserve_decision = ReserveDecision(
            transaction_id=context.transaction_id,
            strategy="dashboard_existing_optimization_result",
            strategy_version="1",
            block_amount=Money(int(decision["recommended_block_paise"])),
        )
        if request.simulate_failure:
            self.mock_provider.failure_config.fail_next_create = True
        try:
            execution = self.reserve_service.authorize_initial_block(
                reserve_decision,
                customer_reference=context.customer_id,
                idempotency_key=request.idempotency_key,
                metadata=(("source", "phase_11_dashboard"),),
            )
        except ReservePayError as exc:
            return {
                "recommendation": recommendation,
                "execution": {
                    "status": "failed",
                    "authorized_amount_paise": 0,
                    "error": exc.to_dict(),
                    "provider": "mock",
                },
            }
        return {
            "recommendation": recommendation,
            "execution": {"status": "authorized", **execution.to_dict()},
        }

    def dynamic_demo(self, request: DynamicDemoRequest) -> dict[str, object]:
        provider = MockReserveProvider(
            MockFailureConfig(fail_next_increase=request.fail_first_increase)
        )
        service = ReservePayService(provider, dynamic_service=self.dynamic_service)
        policy = ReserveRiskPolicy.for_profile(RiskProfile(request.risk_profile))
        session = self.dynamic_service.start_dynamic_session(
            self.dynamic_record.initial_transaction, policy
        )
        initial = service.authorize_initial_block(
            session.initial_optimization.reserve_decision,
            customer_reference=session.initial_context.customer_id,
            idempotency_key=f"{session.transaction_id}:dashboard-initial",
        )
        timeline: list[dict[str, object]] = [
            {
                "stage": "Initial",
                "estimated_amount_paise": session.current_context.estimated_amount.amount_paise,
                "q97_paise": session.latest_prediction.amount_for_quantile("0.97").amount_paise,
                "q99_paise": session.latest_prediction.amount_for_quantile("0.99").amount_paise,
                "recommended_target_paise": session.latest_optimization.recommended_block.amount_paise,
                "authorized_amount_paise": initial.block.authorized_amount.amount_paise,
                "additional_required_paise": 0,
                "execution_status": "authorized",
            }
        ]
        for update in self.dynamic_record.updates:
            application = self.dynamic_service.apply_context_update(session, update)
            session = application.session
            execution = service.request_additional_block(
                session,
                application.decision,
                block_id=initial.block.block_id,
                idempotency_key=f"{session.transaction_id}:{update.event_id}:dashboard",
            )
            session = execution.session
            timeline.append(
                {
                    "stage": "Traffic Update" if update.sequence_number == 1 else "Route Update",
                    "estimated_amount_paise": session.current_context.estimated_amount.amount_paise,
                    "q97_paise": application.decision.revised_q97.amount_paise,
                    "q99_paise": application.decision.revised_q99.amount_paise,
                    "recommended_target_paise": application.decision.recommended_target_block.amount_paise,
                    "authorized_amount_paise": session.current_authorized_block.amount_paise,
                    "additional_required_paise": application.decision.additional_block_required.amount_paise,
                    "execution_status": execution.status.value,
                    "error": execution.error,
                }
            )
        timeline.append(
            {
                "stage": "Completion",
                "actual_amount_paise": self.dynamic_record.outcome.actual_amount.amount_paise,
                "recommended_target_paise": session.latest_optimization.recommended_block.amount_paise,
                "authorized_amount_paise": session.current_authorized_block.amount_paise,
                "additional_required_paise": 0,
                "execution_status": "ride_completed",
            }
        )
        return {
            "provider": "mock",
            "risk_profile": policy.profile.value,
            "timeline": timeline,
            "failure_injected": request.fail_first_increase,
            "actual_amount_decision_time_use": False,
        }

    def evidence(self) -> dict[str, object]:
        try:
            value = json.loads(self.settings.resolved_evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DashboardError(
                "evidence_artifact_unavailable",
                "Precomputed dashboard evidence is unavailable. Run prepare-dashboard-evidence.",
                status_code=503,
            ) from exc
        required = {"provenance", "strategies", "block_distribution", "per_city", "personalization", "dynamic"}
        if not isinstance(value, dict) or not required.issubset(value):
            raise DashboardError(
                "invalid_evidence_artifact",
                "Precomputed dashboard evidence failed validation.",
                status_code=503,
            )
        return value

    def demo_scenarios(self) -> dict[str, object]:
        return {
            "customer_profiles": [
                {"id": "cold_start", "label": "Cold Start", "description": "No eligible completed rides; the base model is used."},
                {"id": "stable_history", "label": "Stable History", "description": "Eight tightly clustered completed rides."},
                {"id": "overrun_prone", "label": "Overrun-Prone History", "description": "Eight synthetic completed rides with repeated positive fare overruns."},
            ],
            "ride_scenarios": [
                {"id": "standard_hyderabad", "label": "Standard Hyderabad Ride"},
                {"id": "dynamic_traffic_route", "label": "Dynamic Traffic / Route Ride"},
                {"id": "provider_failure", "label": "Provider Failure Demo"},
            ],
            "default_transaction": OptimizeRequest().model_dump(mode="json"),
            "traffic_mapping": {
                key: str(value) for key, value in TRAFFIC_DURATION_MULTIPLIERS.items()
            },
        }
