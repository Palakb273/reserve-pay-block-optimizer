"""Exhaustive deterministic minimization across bounded block candidates."""

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.optimization.candidates import generate_candidates
from reserve_pay_optimizer.optimization.config import OptimizationConfig
from reserve_pay_optimizer.optimization.distribution import QuantileDistribution
from reserve_pay_optimizer.optimization.models import CandidateScore, OptimizationResult
from reserve_pay_optimizer.optimization.objective import score_candidate
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


class ReserveBlockOptimizer:
    def __init__(self, config: OptimizationConfig | None = None) -> None:
        self.config = config or OptimizationConfig()

    def optimize(
        self,
        transaction: RideTransactionContext,
        prediction: FareDistributionPrediction,
    ) -> OptimizationResult:
        scored = self.score_candidates(transaction, prediction)
        return self.build_result(transaction, prediction, scored, candidate_count=len(scored))

    def score_candidates(
        self,
        transaction: RideTransactionContext,
        prediction: FareDistributionPrediction,
    ) -> tuple[CandidateScore, ...]:
        """Generate and score candidates once for unconstrained or policy use."""

        if prediction.transaction_id != transaction.transaction_id:
            raise ValueError("prediction transaction_id must match the transaction context")
        distribution = QuantileDistribution(prediction)
        candidates = generate_candidates(transaction, prediction, self.config)
        return tuple(
            score_candidate(transaction, distribution, candidate, self.config)
            for candidate in candidates
        )

    def build_result(
        self,
        transaction: RideTransactionContext,
        prediction: FareDistributionPrediction,
        eligible_scores: tuple[CandidateScore, ...],
        *,
        candidate_count: int,
    ) -> OptimizationResult:
        """Select the Phase-5 objective minimum from caller-defined eligible scores."""

        if not eligible_scores:
            raise ValueError("at least one eligible candidate score is required")
        selected = min(eligible_scores, key=lambda item: (item.objective_score, item.block_amount.amount_paise))
        ranked = tuple(
            sorted(eligible_scores, key=lambda item: (item.objective_score, item.block_amount.amount_paise))[:5]
        )
        return OptimizationResult(
            transaction_id=transaction.transaction_id,
            estimated_amount=transaction.estimated_amount,
            recommended_block=selected.block_amount,
            estimated_collection_probability=selected.estimated_collection_probability,
            estimated_under_block_probability=selected.estimated_under_block_probability,
            expected_excess_block=selected.expected_excess_block,
            expected_excess_block_ratio=selected.expected_excess_block_ratio,
            friction_ratio=selected.friction_ratio,
            objective_score=selected.objective_score,
            score_components=selected.score_components,
            candidate_count=candidate_count,
            model_version=prediction.model_version,
            optimization_config=self.config,
            top_candidates=ranked,
        )
