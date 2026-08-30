import type { DynamicDemoResponse, EvidenceResponse, OptimizeResponse, WhatIfResponse } from '../types/api'

export const optimizeResponse: OptimizeResponse = {
  transaction: { estimated_amount_paise: 65000 },
  prediction: {
    mode: 'personalized', history_count: 8, model_version: 'fare_distribution_personalized_v1',
    quantiles_paise: { '0.05': 60100, '0.50': 67600, '0.90': 72400, '0.95': 74100, '0.97': 74903, '0.99': 77200 },
    modeled_range: { lower_amount_paise: 60100, upper_amount_paise: 74100, label: 'Modeled Q05–Q95 interval' },
  },
  decision: {
    recommended_block_paise: 74903,
    estimated_collection_probability: '0.970000',
    expected_excess_block_paise: 7120,
    objective_score: '0.183420',
    score_components: { under_block_component: '0.120000' },
  },
  policy: { profile: 'balanced', target_collection_probability: '0.970000' },
  explanation: {
    summary: 'The balanced policy selects the smallest candidate meeting modeled coverage.',
    details: 'The result uses decision-time context and eight eligible completed rides.',
    factors: [
      { code: 'policy', label: 'Balanced policy', direction: 'increase', evidence: {} },
      { code: 'history', label: 'Stable history', direction: 'decrease', evidence: {} },
    ],
    objective_components: { under_block: '0.120000', excess: '0.043420' },
    candidate_comparison: [], history_summary: { eligible_rides: 8 }, explanation_id: 'exp-test-1',
  },
  meta: { project_version: '0.11.0', processing_ms: 13.2, financial_logic_location: 'python_backend' },
}

export const revisedResponse: OptimizeResponse = {
  ...optimizeResponse,
  transaction: { estimated_amount_paise: 65000 },
  prediction: {
    ...optimizeResponse.prediction,
    quantiles_paise: { ...optimizeResponse.prediction.quantiles_paise, '0.97': 82300, '0.99': 84900 },
  },
  decision: { ...optimizeResponse.decision, recommended_block_paise: 82300, expected_excess_block_paise: 9060 },
}

export const whatIfResponse: WhatIfResponse = {
  previous: optimizeResponse,
  revised: revisedResponse,
  difference: { recommended_block_paise: 7397, q97_paise: 7397, expected_excess_block_paise: 1940 },
  applied_overrides: { traffic_level: 'heavy' },
}

export const dynamicSuccess: DynamicDemoResponse = {
  provider: 'mock', risk_profile: 'balanced', failure_injected: false, actual_amount_decision_time_use: false,
  timeline: [
    { stage: 'Initial', recommended_target_paise: 74903, authorized_amount_paise: 74903, additional_required_paise: 0, execution_status: 'authorized', q97_paise: 74903, q99_paise: 77200 },
    { stage: 'Traffic Update', recommended_target_paise: 82300, authorized_amount_paise: 82300, additional_required_paise: 7397, execution_status: 'authorized', q97_paise: 82300, q99_paise: 84900 },
  ],
}

export const dynamicFailure: DynamicDemoResponse = {
  ...dynamicSuccess,
  failure_injected: true,
  timeline: [
    dynamicSuccess.timeline[0],
    { ...dynamicSuccess.timeline[1], authorized_amount_paise: 74903, execution_status: 'failed', error: { code: 'provider_rejected', message: 'Injected failure' } },
  ],
}

const metric = (strategy: string, success: string, excess: number) => ({
  strategy, transaction_count: 10000, collection_success_rate: success,
  under_block_rate: String(1 - Number(success)), average_excess_block_paise: excess,
  average_under_block_paise: 300, capital_efficiency: '0.920000', average_block_amount_paise: 71100,
})

export const evidenceResponse: EvidenceResponse = {
  provenance: {
    dataset: 'Synthetic India Mobility', record_count: 10000, seed: 202611,
    predictor: 'fare_distribution_personalized_v1', policy: 'balanced',
    target_collection_probability: '0.970000', project_version: '0.11.0',
    dataset_fingerprint_sha256: 'abcdef0123456789abcdef0123456789',
    synthetic_data_disclaimer: 'These results use synthetic city profiles and are not production city statistics.',
  },
  strategies: {
    exact_estimate: metric('exact_estimate', '0.410000', 800),
    fixed_buffer_20: metric('fixed_buffer_20', '0.995000', 11000),
    optimized_balanced: metric('optimized_balanced', '0.971000', 6200),
  },
  deltas: { collection_success_percentage_points_vs_exact: '56.100', average_excess_reduction_paise_vs_fixed_20: 4800 },
  block_distribution: [{ lower_paise: 50000, upper_paise: 59999, count: 3200 }, { lower_paise: 60000, upper_paise: 69999, count: 6800 }],
  tradeoff_points: [
    { strategy: 'exact_estimate', average_excess_block_paise: 800, collection_success_rate: '0.410000' },
    { strategy: 'fixed_buffer_20', average_excess_block_paise: 11000, collection_success_rate: '0.995000' },
    { strategy: 'optimized_balanced', average_excess_block_paise: 6200, collection_success_rate: '0.971000' },
  ],
  per_city: { hyderabad: { record_count: 1420, optimized_collection_success_rate: '0.969000', optimized_average_excess_block_paise: 6100 } },
  personalization: {
    stable_history: { prediction_mode: 'personalized', history_count: 8, q97_paise: 70100, recommended_block_paise: 70100 },
    overrun_prone: { prediction_mode: 'personalized', history_count: 8, q97_paise: 79900, recommended_block_paise: 79900 },
  },
  dynamic: {
    record_count: 500,
    static: metric('static', '0.920000', 5200), dynamic: metric('dynamic', '0.968000', 6900),
    dynamic_diagnostics: { average_initial_block_paise: 70100, average_final_authorized_block_paise: 74800, rides_requiring_additional_block_rate: '0.480000' },
  },
}

