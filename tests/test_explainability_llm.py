import json
import unittest

from reserve_pay_optimizer.domain.evaluation import format_ratio
from reserve_pay_optimizer.explainability.models import ExplanationLevel
from reserve_pay_optimizer.explainability.service import ExplanationService
from tests.dynamic_fixtures import DeterministicPersonalizedPredictor, context
from reserve_pay_optimizer.dynamic.service import DynamicRideService
from reserve_pay_optimizer.policy.risk import RiskProfile


class FakeGenerator:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        if callable(self.response):
            return self.response(request)
        return self.response


def valid_response(request):
    facts = request.structured_facts
    return json.dumps(
        {
            "transaction_id": facts["transaction_id"],
            "recommended_block_paise": facts["recommended_block_paise"],
            "estimated_collection_probability": facts["estimated_collection_probability"],
            "authorization_status": "not_applicable",
            "summary": "This is an already-computed reserve recommendation.",
            "why_this_amount": "It is the lowest-objective feasible candidate in the supplied facts.",
            "tradeoff": "The supplied objective balances modeled under-block risk and excess funds.",
            "personalization": "Only aggregated completed-ride history was used.",
            "dynamic_update": None,
            "confidence_note": "The probability is a modeled estimate, not a guarantee.",
        }
    )


class ExplanationGeneratorTests(unittest.TestCase):
    def setUp(self):
        predictor = DeterministicPersonalizedPredictor(5)
        session = DynamicRideService(predictor).start_dynamic_session(
            context(), RiskProfile.BALANCED
        )
        self.sources = (
            session.initial_context,
            session.initial_prediction,
            session.initial_optimization,
        )

    def test_protocol_receives_structured_facts_only_and_valid_output_is_used(self):
        generator = FakeGenerator(valid_response)
        service = ExplanationService(generator)
        rendered = service.explain_reserve_decision(
            *self.sources, detail=ExplanationLevel.DETAILED
        )
        self.assertEqual(rendered.renderer_type, "generated_text")
        self.assertFalse(rendered.fallback_used)
        request = generator.requests[0]
        serialized = json.dumps(request.structured_facts).casefold()
        self.assertNotIn("actual_amount", serialized)
        self.assertNotIn("customer_overrun_bias", serialized)
        for guardrail in (
            "Do not calculate or recommend a different amount",
            "Do not claim probabilities are guarantees",
            "Do not label customers as good, bad, or risky",
        ):
            self.assertIn(guardrail, request.prompt)

    def test_invalid_changed_block_falls_back_without_changing_decision(self):
        def changed(request):
            value = json.loads(valid_response(request))
            value["recommended_block_paise"] += 1
            return json.dumps(value)

        generator = FakeGenerator(changed)
        service = ExplanationService(generator)
        expected = self.sources[2].recommended_block
        rendered = service.explain_reserve_decision(*self.sources)
        self.assertTrue(rendered.fallback_used)
        self.assertEqual(rendered.renderer_type, "template")
        self.assertEqual(rendered.facts.recommended_block, expected)
        self.assertEqual(service.metrics.llm_renderer_failures, 1)

    def test_invalid_json_and_provider_exception_both_fall_back(self):
        for generator in (
            FakeGenerator("not json"),
            FakeGenerator(error=RuntimeError("offline")),
        ):
            service = ExplanationService(generator)
            rendered = service.explain_reserve_decision(*self.sources)
            self.assertTrue(rendered.fallback_used)
            self.assertIn("is recommended", rendered.text)
            self.assertEqual(service.metrics.llm_renderer_failures, 1)


if __name__ == "__main__":
    unittest.main()
