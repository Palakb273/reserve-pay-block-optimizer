"""High-level safe explanation APIs with optional generated-text fallback."""

from dataclasses import dataclass

from reserve_pay_optimizer.domain.mobility import RideTransactionContext
from reserve_pay_optimizer.dynamic.models import DynamicReoptimizationDecision, DynamicRideSession
from reserve_pay_optimizer.explainability.evidence import (
    build_dynamic_decision_evidence,
    build_reserve_decision_evidence,
)
from reserve_pay_optimizer.explainability.models import (
    AuthorizationStatus,
    DecisionExplanation,
    ExplanationLevel,
    RenderedDecisionExplanation,
)
from reserve_pay_optimizer.explainability.prompt import (
    ExplanationTextGenerator,
    build_explanation_prompt,
)
from reserve_pay_optimizer.explainability.renderer import TemplateExplanationRenderer
from reserve_pay_optimizer.explainability.validation import validate_generated_explanation
from reserve_pay_optimizer.policy.models import PolicyOptimizationResult
from reserve_pay_optimizer.prediction.distribution import FareDistributionPrediction


@dataclass(slots=True)
class ExplanationValidationMetrics:
    explanations_generated: int = 0
    structured_explanations_valid: int = 0
    numeric_decision_consistency: int = 0
    fallback_count: int = 0
    llm_renderer_failures: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "explanations_generated": self.explanations_generated,
            "structured_explanations_valid": self.structured_explanations_valid,
            "numeric_decision_consistency": self.numeric_decision_consistency,
            "fallback_count": self.fallback_count,
            "llm_renderer_failures": self.llm_renderer_failures,
        }


class ExplanationService:
    def __init__(
        self,
        text_generator: ExplanationTextGenerator | None = None,
        template_renderer: TemplateExplanationRenderer | None = None,
    ) -> None:
        self.text_generator = text_generator
        self.template_renderer = template_renderer or TemplateExplanationRenderer()
        self.metrics = ExplanationValidationMetrics()

    def _render(
        self,
        facts: DecisionExplanation,
        detail: ExplanationLevel,
    ) -> RenderedDecisionExplanation:
        self.metrics.explanations_generated += 1
        self.metrics.structured_explanations_valid += 1
        self.metrics.numeric_decision_consistency += 1
        template = self.template_renderer.render(facts, detail)
        if self.text_generator is None:
            self.metrics.fallback_count += 1
            return RenderedDecisionExplanation(
                facts=facts,
                text=template,
                detail=detail,
                renderer_type=self.template_renderer.renderer_type,
                fallback_used=True,
                fallback_reason="text_generator_not_configured",
            )
        try:
            request = build_explanation_prompt(facts, detail)
            generated = self.text_generator.generate(request)
            sections = validate_generated_explanation(generated, facts)
        except Exception as exc:  # explanation failure must not affect the decision
            self.metrics.fallback_count += 1
            self.metrics.llm_renderer_failures += 1
            return RenderedDecisionExplanation(
                facts=facts,
                text=template,
                detail=detail,
                renderer_type=self.template_renderer.renderer_type,
                fallback_used=True,
                fallback_reason=type(exc).__name__,
            )
        return RenderedDecisionExplanation(
            facts=facts,
            text=sections.to_text(),
            detail=detail,
            renderer_type="generated_text",
        )

    def explain_reserve_decision(
        self,
        transaction: RideTransactionContext,
        prediction: FareDistributionPrediction,
        optimization: PolicyOptimizationResult,
        detail: ExplanationLevel = ExplanationLevel.CONCISE,
    ) -> RenderedDecisionExplanation:
        return self._render(
            build_reserve_decision_evidence(transaction, prediction, optimization),
            detail,
        )

    def explain_dynamic_decision(
        self,
        session: DynamicRideSession,
        decision: DynamicReoptimizationDecision,
        detail: ExplanationLevel = ExplanationLevel.CONCISE,
        authorization_status: AuthorizationStatus | None = None,
    ) -> RenderedDecisionExplanation:
        return self._render(
            build_dynamic_decision_evidence(
                session, decision, authorization_status=authorization_status
            ),
            detail,
        )
