"""Typed candidate diagnostics and final optimization result."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.domain.reserve import ReserveDecision
from reserve_pay_optimizer.optimization.config import OptimizationConfig

OPTIMIZED_STRATEGY_ID = "optimized_reserve"
OPTIMIZED_STRATEGY_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ScoreComponents:
    under_block_component: Decimal
    excess_component: Decimal
    friction_component: Decimal

    @property
    def total(self) -> Decimal:
        return self.under_block_component + self.excess_component + self.friction_component

    def to_dict(self) -> dict[str, str]:
        return {
            "under_block_component": format_ratio(self.under_block_component),
            "excess_component": format_ratio(self.excess_component),
            "friction_component": format_ratio(self.friction_component),
            "total_score": format_ratio(self.total),
        }


@dataclass(frozen=True, slots=True)
class CandidateScore:
    block_amount: Money
    estimated_collection_probability: Decimal
    estimated_under_block_probability: Decimal
    expected_excess_block_paise_exact: Decimal
    expected_excess_block_ratio: Decimal
    friction_ratio: Decimal
    score_components: ScoreComponents

    @property
    def objective_score(self) -> Decimal:
        return self.score_components.total

    @property
    def expected_excess_block(self) -> Money:
        rounded = int(self.expected_excess_block_paise_exact.to_integral_value(rounding=ROUND_CEILING))
        return Money.from_non_negative_paise(rounded)

    def to_dict(self) -> dict[str, object]:
        return {
            "block_amount_paise": self.block_amount.amount_paise,
            "estimated_collection_probability": format_ratio(self.estimated_collection_probability),
            "estimated_under_block_probability": format_ratio(self.estimated_under_block_probability),
            "expected_excess_block_paise": self.expected_excess_block.amount_paise,
            "expected_excess_block_ratio": format_ratio(self.expected_excess_block_ratio),
            "friction_ratio": format_ratio(self.friction_ratio),
            "objective_score": format_ratio(self.objective_score),
            "score_components": self.score_components.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    transaction_id: str
    estimated_amount: Money
    recommended_block: Money
    estimated_collection_probability: Decimal
    estimated_under_block_probability: Decimal
    expected_excess_block: Money
    expected_excess_block_ratio: Decimal
    friction_ratio: Decimal
    objective_score: Decimal
    score_components: ScoreComponents
    candidate_count: int
    model_version: str
    optimization_config: OptimizationConfig
    top_candidates: tuple[CandidateScore, ...] = ()

    @property
    def reserve_decision(self) -> ReserveDecision:
        return ReserveDecision(
            transaction_id=self.transaction_id,
            strategy=OPTIMIZED_STRATEGY_ID,
            strategy_version=OPTIMIZED_STRATEGY_VERSION,
            block_amount=self.recommended_block,
            parameters=tuple(
                (key, str(value)) for key, value in self.optimization_config.to_dict().items()
            ) + (("model_version", self.model_version),),
        )

    def to_dict(self, *, include_candidates: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "transaction_id": self.transaction_id,
            "estimated_amount_paise": self.estimated_amount.amount_paise,
            "recommended_block_paise": self.recommended_block.amount_paise,
            "estimated_collection_probability": format_ratio(self.estimated_collection_probability),
            "estimated_under_block_probability": format_ratio(self.estimated_under_block_probability),
            "expected_excess_block_paise": self.expected_excess_block.amount_paise,
            "expected_excess_block_ratio": format_ratio(self.expected_excess_block_ratio),
            "friction_ratio": format_ratio(self.friction_ratio),
            "objective_score": format_ratio(self.objective_score),
            "score_components": self.score_components.to_dict(),
            "candidate_count": self.candidate_count,
            "model_version": self.model_version,
            "optimization_config": self.optimization_config.to_dict(),
        }
        if include_candidates:
            result["best_candidate_scores"] = [candidate.to_dict() for candidate in self.top_candidates]
        return result
