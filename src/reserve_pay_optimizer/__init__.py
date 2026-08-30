"""Reserve Pay Block Optimizer package."""

__version__ = "0.14.0"

from reserve_pay_optimizer.agents import (
    AgentActionType,
    AgentError,
    AgentEvaluationReport,
    AgentModel,
    AgentModelAction,
    AgentOperationalMetrics,
    AgentOrchestrator,
    AgentResponse,
    AgentStateStatus,
    AgentToolRegistry,
    CustomerHistoryToolOutput,
    DecisionConsistencyError,
    DeterministicAgentModel,
    ExplanationAgent,
    ExplanationAgentResult,
    InvalidAgentResponseError,
    InvalidToolArgumentsError,
    MerchantHistoryToolOutput,
    OptimizationToolOutput,
    PredictionToolOutput,
    ReasonCode,
    ReserveAgentDecision,
    ReserveAgentRequest,
    ReserveAgentState,
    ReserveIntelligenceAgent,
    RiskLevel,
    RiskToolOutput,
    StepLimitExceededError,
    ToolAuditRecord,
    ToolExecutionError,
    ToolOrderError,
    UnknownToolError,
    evaluate_agent_orchestration,
)

from reserve_pay_optimizer.domain.errors import DomainValidationError, ValidationIssue
from reserve_pay_optimizer.domain.evaluation import (
    BaselineComparison,
    StrategyMetrics,
    TransactionEvaluation,
)
from reserve_pay_optimizer.domain.mobility import (
    RideTransactionContext,
    RideTransactionOutcome,
)
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.domain.types import Currency, SupportedCity, TransactionDomain
from reserve_pay_optimizer.dynamic.models import (
    DynamicReoptimizationDecision,
    DynamicRideSession,
    RideContextUpdate,
    RideUpdateReason,
)
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.dynamic.simulation import (
    DynamicSimulationDataset,
    DynamicSimulationRecord,
    simulate_dynamic_transactions,
)
from reserve_pay_optimizer.explainability.models import (
    DecisionExplanation,
    DecisionType,
    ExplanationLevel,
    RenderedDecisionExplanation,
)
from reserve_pay_optimizer.explainability.service import ExplanationService
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.models import OptimizationResult
from reserve_pay_optimizer.optimization.optimizer import ReserveBlockOptimizer
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.policy.optimizer import PolicyConstrainedOptimizer
from reserve_pay_optimizer.policy.risk import ReserveRiskPolicy, RiskProfile
from reserve_pay_optimizer.personalization.config import (
    MINIMUM_PERSONALIZATION_HISTORY,
    PERSONALIZED_MODEL_VERSION,
)
from reserve_pay_optimizer.personalization.history import (
    InMemoryCustomerHistoryProvider,
    calculate_customer_history_features,
)
from reserve_pay_optimizer.personalization.model import (
    PersonalizedConditionalFareDistributionModel,
)
from reserve_pay_optimizer.personalization.models import (
    CustomerHistoryFeatures,
    PersonalizedFareDistributionPrediction,
)
from reserve_pay_optimizer.personalization.predictor import PersonalizedFarePredictor
from reserve_pay_optimizer.prediction.config import MODEL_VERSION, ModelConfig
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction
from reserve_pay_optimizer.prediction.model import ConditionalFareDistributionModel
from reserve_pay_optimizer.reserve_pay import (
    MockFailureConfig,
    MockReserveProvider,
    RazorpayProvider,
    RazorpayProviderConfig,
    ReserveBlock,
    ReserveBlockStatus,
    ReservePayProvider,
    ReservePayService,
    RetryConfig,
)
from reserve_pay_optimizer.services.mobility_validation import (
    validate_mobility_transaction,
)
from reserve_pay_optimizer.simulation.config import FareModelConfig, SimulationConfig
from reserve_pay_optimizer.simulation.generator import simulate_transactions
from reserve_pay_optimizer.simulation.models import (
    SimulationDataset,
    SimulationDiagnostics,
    SimulationRecord,
)
from reserve_pay_optimizer.strategies.exact_estimate import ExactEstimateStrategy
from reserve_pay_optimizer.strategies.fixed_buffer import FixedBufferStrategy
from reserve_pay_optimizer.strategies.optimized import OptimizedReserveStrategy

__all__ = [
    "BaselineComparison",
    "Currency",
    "ConditionalFareDistributionModel",
    "CustomerHistoryFeatures",
    "DomainValidationError",
    "DynamicReoptimizationDecision",
    "DynamicRideService",
    "DynamicRideSession",
    "DynamicSimulationDataset",
    "DynamicSimulationRecord",
    "DecisionExplanation",
    "DecisionType",
    "ExactEstimateStrategy",
    "ExplanationLevel",
    "ExplanationService",
    "FareModelConfig",
    "FareDistributionPrediction",
    "FixedBufferStrategy",
    "Money",
    "MODEL_VERSION",
    "MINIMUM_PERSONALIZATION_HISTORY",
    "ModelConfig",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizedReserveStrategy",
    "PolicyConstrainedOptimizer",
    "PolicyOptimizationResult",
    "PERSONALIZED_MODEL_VERSION",
    "PersonalizedConditionalFareDistributionModel",
    "PersonalizedFareDistributionPrediction",
    "PersonalizedFarePredictor",
    "ReserveRiskPolicy",
    "RenderedDecisionExplanation",
    "ReserveBlockOptimizer",
    "ReserveBlock",
    "ReserveBlockStatus",
    "ReservePayProvider",
    "ReservePayService",
    "MockFailureConfig",
    "MockReserveProvider",
    "RazorpayProvider",
    "RazorpayProviderConfig",
    "RetryConfig",
    "RiskProfile",
    "RideContextUpdate",
    "RideUpdateReason",
    "RideTransactionContext",
    "RideTransactionOutcome",
    "ReserveDecision",
    "SimulationConfig",
    "SimulationDataset",
    "SimulationDiagnostics",
    "SimulationRecord",
    "StrategyMetrics",
    "SupportedCity",
    "TransactionDomain",
    "TransactionEvaluation",
    "ValidationIssue",
    "InMemoryCustomerHistoryProvider",
    "calculate_customer_history_features",
    "simulate_transactions",
    "simulate_dynamic_transactions",
    "validate_mobility_transaction",
    "AgentActionType",
    "AgentError",
    "AgentEvaluationReport",
    "AgentModel",
    "AgentModelAction",
    "AgentOperationalMetrics",
    "AgentOrchestrator",
    "AgentResponse",
    "AgentStateStatus",
    "AgentToolRegistry",
    "CustomerHistoryToolOutput",
    "DecisionConsistencyError",
    "DeterministicAgentModel",
    "ExplanationAgent",
    "ExplanationAgentResult",
    "InvalidAgentResponseError",
    "InvalidToolArgumentsError",
    "MerchantHistoryToolOutput",
    "OptimizationToolOutput",
    "PredictionToolOutput",
    "ReasonCode",
    "ReserveAgentDecision",
    "ReserveAgentRequest",
    "ReserveAgentState",
    "ReserveIntelligenceAgent",
    "RiskLevel",
    "RiskToolOutput",
    "StepLimitExceededError",
    "ToolAuditRecord",
    "ToolExecutionError",
    "ToolOrderError",
    "UnknownToolError",
    "evaluate_agent_orchestration",
    "__version__",
]
