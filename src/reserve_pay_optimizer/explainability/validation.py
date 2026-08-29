"""Bounded validation for optional generated explanation JSON."""

from dataclasses import dataclass
import json

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.explainability.errors import InvalidGeneratedExplanation
from reserve_pay_optimizer.explainability.models import DecisionExplanation

MAX_SECTION_CHARS = 2000
MAX_TOTAL_CHARS = 8000
_FIELDS = {
    "transaction_id",
    "recommended_block_paise",
    "estimated_collection_probability",
    "authorization_status",
    "summary",
    "why_this_amount",
    "tradeoff",
    "personalization",
    "dynamic_update",
    "confidence_note",
}
_REQUIRED_TEXT = ("summary", "why_this_amount", "tradeoff", "confidence_note")
_FORBIDDEN_PRIVACY_TERMS = (
    "customer_overrun_bias",
    "customer_variance_multiplier",
    "pricing_noise",
    "actual_amount",
)


@dataclass(frozen=True, slots=True)
class GeneratedExplanationSections:
    summary: str
    why_this_amount: str
    tradeoff: str
    personalization: str | None
    dynamic_update: str | None
    confidence_note: str

    def to_text(self) -> str:
        sections = (
            ("Summary", self.summary),
            ("Why this amount", self.why_this_amount),
            ("Trade-off", self.tradeoff),
            ("Personalization", self.personalization),
            ("Dynamic update", self.dynamic_update),
            ("Probability note", self.confidence_note),
        )
        return "\n\n".join(f"{label}: {text}" for label, text in sections if text)


def validate_generated_explanation(
    raw: str,
    facts: DecisionExplanation,
) -> GeneratedExplanationSections:
    if not isinstance(raw, str) or len(raw) > MAX_TOTAL_CHARS:
        raise InvalidGeneratedExplanation("generated response is missing or too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidGeneratedExplanation("generated response is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise InvalidGeneratedExplanation("generated response schema does not match")
    expected_authorization = (
        facts.dynamic_context.authorization_status.value
        if facts.dynamic_context is not None
        else "not_applicable"
    )
    expected = {
        "transaction_id": facts.transaction_id,
        "recommended_block_paise": facts.recommended_block.amount_paise,
        "estimated_collection_probability": format_ratio(
            facts.estimated_collection_probability
        ),
        "authorization_status": expected_authorization,
    }
    for field, expected_value in expected.items():
        if value[field] != expected_value:
            raise InvalidGeneratedExplanation(
                f"generated response changed authoritative field {field}"
            )
    for field in _REQUIRED_TEXT:
        if not isinstance(value[field], str) or not value[field].strip():
            raise InvalidGeneratedExplanation(f"{field} must be non-empty text")
    for field in ("personalization", "dynamic_update"):
        if value[field] is not None and (
            not isinstance(value[field], str) or not value[field].strip()
        ):
            raise InvalidGeneratedExplanation(f"{field} must be text or null")
    text_values = [value[field] for field in _REQUIRED_TEXT]
    text_values.extend(value[field] for field in ("personalization", "dynamic_update") if value[field])
    if any(len(text) > MAX_SECTION_CHARS for text in text_values):
        raise InvalidGeneratedExplanation("generated response section is too large")
    combined = " ".join(text_values).casefold()
    if any(term in combined for term in _FORBIDDEN_PRIVACY_TERMS):
        raise InvalidGeneratedExplanation("generated response exposed a forbidden field")
    if expected_authorization == "recommendation_only" and "successfully blocked" in combined:
        raise InvalidGeneratedExplanation("generated response invented authorization")
    return GeneratedExplanationSections(
        summary=value["summary"],
        why_this_amount=value["why_this_amount"],
        tradeoff=value["tradeoff"],
        personalization=value["personalization"],
        dynamic_update=value["dynamic_update"],
        confidence_note=value["confidence_note"],
    )
