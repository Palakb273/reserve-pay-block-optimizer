"""Provider-neutral optional text-generation request and deterministic prompt."""

from dataclasses import dataclass
import json
from typing import Protocol

from reserve_pay_optimizer.explainability.models import DecisionExplanation, ExplanationLevel


@dataclass(frozen=True, slots=True)
class ExplanationGenerationRequest:
    prompt: str
    structured_facts: dict[str, object]
    detail: ExplanationLevel


class ExplanationTextGenerator(Protocol):
    def generate(self, request: ExplanationGenerationRequest) -> str:
        ...


def build_explanation_prompt(
    explanation: DecisionExplanation,
    detail: ExplanationLevel,
) -> ExplanationGenerationRequest:
    facts = explanation.to_dict()
    prompt = """You are explaining an already-computed Reserve Pay block decision.

Do not calculate or recommend a different amount.
Use only the supplied structured facts.
Do not claim probabilities are guarantees.
Do not invent causal rupee contributions.
Do not claim these are Razorpay production policies or coefficients.
Do not label customers as good, bad, or risky.
Describe customer history only as aggregated observed transactions.
For dynamic decisions, distinguish current authorized funds from recommended additional reserve.
Do not claim authorization occurred unless authorization_status is simulated_confirmed or mock_provider_confirmed.
When authorization_status is mock_provider_confirmed, state that no external or real payment network was called.

Return one JSON object with these exact fields:
transaction_id, recommended_block_paise, estimated_collection_probability,
authorization_status, summary, why_this_amount, tradeoff, personalization,
dynamic_update, confidence_note.

The first four fields must copy the supplied facts exactly. Text sections must be concise strings;
personalization and dynamic_update may be null when inapplicable.

Structured facts:
""" + json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return ExplanationGenerationRequest(prompt=prompt, structured_facts=facts, detail=detail)
