"""Deterministic offline rendering of authoritative explanation evidence."""

from decimal import Decimal, ROUND_HALF_UP

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.domain.money import Money
from reserve_pay_optimizer.explainability.models import (
    AuthorizationStatus,
    DecisionExplanation,
    DecisionType,
    ExplanationLevel,
)


def format_inr(value: Money) -> str:
    return f"₹{value.amount_rupees:.2f}"


def format_percent(value: Decimal) -> str:
    percent = (value * Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{percent}%"


class TemplateExplanationRenderer:
    """Always-available renderer; it performs no financial calculation."""

    renderer_type = "template"

    def render(
        self,
        explanation: DecisionExplanation,
        detail: ExplanationLevel = ExplanationLevel.CONCISE,
    ) -> str:
        if explanation.decision_type is DecisionType.DYNAMIC_REOPTIMIZATION:
            return self._dynamic(explanation, detail)
        return self._static(explanation, detail)

    def _policy_and_tradeoff(self, explanation: DecisionExplanation) -> list[str]:
        policy = explanation.risk_policy
        lines = [
            f"The {policy.profile.value.title()} merchant profile requires at least approximately "
            f"{format_percent(policy.target_collection_probability)} modeled collection coverage. "
            f"The selected block has estimated coverage of approximately "
            f"{format_percent(explanation.estimated_collection_probability)}."
        ]
        if explanation.tradeoff_summary.selected_block_exceeds_profile_quantile:
            lines.append(
                f"The policy threshold is a minimum feasibility requirement, not a command to "
                f"select exactly {format_inr(explanation.tradeoff_summary.profile_quantile_amount)}. "
                "Among candidates meeting that threshold, the existing optimizer selected the "
                "candidate with the lowest configured objective score."
            )
        else:
            lines.append(
                "Among candidates meeting the policy threshold, the existing optimizer selected "
                "the candidate with the lowest configured objective score."
            )
        return lines

    def _personalization(self, explanation: DecisionExplanation) -> str:
        history = explanation.history_summary
        if explanation.prediction_mode == "personalized" and history is not None:
            return (
                f"The personalized model used aggregates from {history.completed_ride_count} prior "
                f"completed rides: mean final-to-estimated ratio "
                f"{format_ratio(history.mean_fare_ratio)}, overrun rate "
                f"{format_percent(history.overrun_rate)}, and fare-ratio standard deviation "
                f"{format_ratio(history.fare_ratio_stddev)}. These observed aggregates were model "
                "inputs; they are not a customer label or a precise causal rupee contribution."
            )
        count = history.completed_ride_count if history else 0
        return (
            f"Only {count} eligible completed rides were available, below the personalization "
            "threshold, so the base transaction-level prediction model was used."
        )

    def _static(
        self, explanation: DecisionExplanation, detail: ExplanationLevel
    ) -> str:
        lines = [
            f"{format_inr(explanation.recommended_block)} is recommended for the current "
            f"{format_inr(explanation.estimated_amount)} fare estimate.",
            *self._policy_and_tradeoff(explanation),
        ]
        if detail is ExplanationLevel.CONCISE:
            return "\n\n".join(lines)
        quantiles = explanation.prediction_summary.to_dict()
        lines.extend(
            [
                "The predicted final-fare distribution is: "
                + ", ".join(
                    f"Q{key[2:]} {format_inr(Money(amount))}"
                    for key, amount in quantiles.items()
                )
                + ". Upper quantiles are increasingly conservative modeled estimates, not guarantees.",
                self._personalization(explanation),
                f"At the selected block, expected unused reserve is "
                f"{format_inr(explanation.expected_excess_block)} "
                f"(ratio {format_ratio(explanation.expected_excess_ratio)}), while the "
                f"customer-friction ratio is {format_ratio(explanation.friction_ratio)}.",
                "Objective components: "
                f"under-block {format_ratio(explanation.objective_components.under_block_component)}, "
                f"expected excess {format_ratio(explanation.objective_components.excess_component)}, "
                f"customer friction {format_ratio(explanation.objective_components.friction_component)}, "
                f"total {format_ratio(explanation.objective_score)}. These are project "
                "experimental weights, not Razorpay production policy.",
            ]
        )
        if explanation.candidate_comparison:
            lines.append(
                "Best policy-compliant candidates: "
                + "; ".join(
                    f"{format_inr(item.block_amount)} → score {format_ratio(item.objective_score)}"
                    + (" (selected)" if item.selected else "")
                    for item in explanation.candidate_comparison
                )
                + "."
            )
        return "\n\n".join(lines)

    def _dynamic(
        self, explanation: DecisionExplanation, detail: ExplanationLevel
    ) -> str:
        dynamic = explanation.dynamic_context
        if dynamic is None:
            raise ValueError("dynamic explanation requires dynamic_context")
        changes = []
        labels = {
            "estimated_amount_paise": "estimated fare (paise)",
            "distance_km": "projected distance (km)",
            "estimated_duration_minutes": "projected duration (minutes)",
            "surge_multiplier": "surge multiplier",
        }
        for change in dynamic.changed_fields:
            changes.append(
                f"{labels[change.field]} changed from {change.previous_value} to {change.revised_value}"
            )
        if changes:
            change_text = "Observed update: " + "; ".join(changes) + "."
        else:
            change_text = "The update changed the validated decision-time context."
        lines = [
            f"The current authorized block is {format_inr(dynamic.previous_authorized_block)}.",
            change_text,
            f"The updated target block is {format_inr(dynamic.recommended_target_block)}. "
            f"Recommended additional reserve is {format_inr(dynamic.additional_block_required)}.",
        ]
        if dynamic.authorization_status is AuthorizationStatus.SIMULATED_CONFIRMED:
            lines.append(
                "That total was confirmed only in simulated/application session state or by the "
                "configured mock reserve provider. No external or real payment network was called."
            )
        else:
            lines.append(
                "This is a recommendation only. No additional funds have been marked authorized."
            )
        if detail is ExplanationLevel.CONCISE:
            return "\n\n".join(lines)
        previous = dynamic.previous_quantiles.to_dict()
        revised = dynamic.revised_quantiles.to_dict()
        lines.append(
            "Predicted distribution changes: "
            + "; ".join(
                f"Q{key[2:]} {format_inr(Money(previous[key]))} → {format_inr(Money(revised[key]))}"
                for key in previous
            )
            + ". These are modeled estimates, not guarantees."
        )
        lines.extend(self._policy_and_tradeoff(explanation))
        lines.append(self._personalization(explanation))
        lines.append(
            "The additional amount uses exactly max(recommended target block − current authorized "
            "block, 0). A lower target therefore produces no additional request and does not imply "
            "a mid-ride release."
        )
        lines.append(
            f"Expected unused reserve at the new target is {format_inr(explanation.expected_excess_block)}; "
            f"objective score {format_ratio(explanation.objective_score)}."
        )
        return "\n\n".join(lines)
