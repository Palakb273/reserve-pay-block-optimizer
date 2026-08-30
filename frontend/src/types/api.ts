export type RiskProfile = 'aggressive' | 'balanced' | 'conservative'
export type CustomerProfile = 'cold_start' | 'stable_history' | 'overrun_prone'
export type City = 'delhi' | 'mumbai' | 'bengaluru' | 'hyderabad' | 'pune' | 'chennai' | 'kolkata'

export interface OptimizeInput {
  transaction_id: string
  estimated_amount_paise: number
  city: City
  distance_km: string
  estimated_duration_minutes: number
  surge_multiplier: string
  timestamp: string
  customer_profile: CustomerProfile
  risk_profile: RiskProfile
}

export interface OptimizeResponse {
  transaction: Record<string, unknown> & { estimated_amount_paise: number }
  prediction: {
    mode: 'base' | 'personalized'
    history_count: number
    model_version: string
    quantiles_paise: Record<'0.05' | '0.50' | '0.90' | '0.95' | '0.97' | '0.99', number>
    modeled_range: { lower_amount_paise: number; upper_amount_paise: number; label: string }
  }
  decision: {
    recommended_block_paise: number
    estimated_collection_probability: string
    expected_excess_block_paise: number
    objective_score: string
    score_components: Record<string, string>
  }
  policy: { profile: RiskProfile; target_collection_probability: string }
  explanation: {
    summary: string
    details: string
    factors: Array<{ code: string; label: string; direction: string; evidence: Record<string, string | number | boolean> }>
    objective_components: Record<string, string>
    candidate_comparison: Array<{ block_amount_paise: number; estimated_collection_probability: string; objective_score: string; selected: boolean }>
    history_summary: null | Record<string, string | number>
    explanation_id: string
  }
  meta: { project_version: string; processing_ms: number; financial_logic_location: string }
}

export interface ToolAuditRecord {
  sequence: number
  tool_name: string
  input_fingerprint_sha256: string
  output_fingerprint_sha256: string
  arguments: Record<string, unknown>
  result: Record<string, unknown>
  started_at: string
  completed_at: string
  status: string
  error?: string | null
}

export interface AgentDecideResponse {
  run_id: string
  decision: {
    transaction_id: string
    agent_run_id: string
    recommended_block_paise: number
    estimated_collection_probability: string
    estimated_under_block_probability: string
    risk_profile: RiskProfile
    risk: 'LOW' | 'MEDIUM' | 'HIGH'
    prediction_mode: string
    history_count: number
    model_version: string
    objective_score: string
    reason_code: string
    reason: string
    confidence: string
    merchant_history_available: boolean
    merchant_history: Record<string, unknown> | null
  }
  explanation: {
    transaction_id: string
    agent_run_id: string
    explanation_id: string
    summary: string
    details: string
    factors: Array<{ code: string; label: string; direction: string; evidence: Record<string, unknown> }>
    confidence_note: string
    renderer: string
  }
  tool_trace: ToolAuditRecord[]
  metrics: {
    processing_ms: number
    step_count: number
    tool_call_count: number
    financial_logic_location: string
  }
}

export interface WhatIfResponse {
  previous: OptimizeResponse
  revised: OptimizeResponse
  difference: {
    recommended_block_paise: number
    q97_paise: number
    expected_excess_block_paise: number
  }
  applied_overrides: Record<string, unknown>
}

export interface DynamicStage {
  stage: string
  estimated_amount_paise?: number
  actual_amount_paise?: number
  q97_paise?: number
  q99_paise?: number
  recommended_target_paise: number
  authorized_amount_paise: number
  additional_required_paise: number
  execution_status: string
  error?: { code: string; message: string } | null
}

export interface DynamicDemoResponse {
  provider: 'mock'
  risk_profile: RiskProfile
  timeline: DynamicStage[]
  failure_injected: boolean
  actual_amount_decision_time_use: false
}

export interface StrategyEvidence {
  strategy: string
  transaction_count: number
  collection_success_rate: string
  under_block_rate: string
  average_excess_block_paise: number
  average_under_block_paise: number
  capital_efficiency: string
  average_block_amount_paise: number
}

export interface EvidenceResponse {
  provenance: {
    dataset: string
    record_count: number
    seed: number
    predictor: string
    policy: string
    target_collection_probability: string
    project_version: string
    dataset_fingerprint_sha256: string
    synthetic_data_disclaimer: string
  }
  strategies: Record<'exact_estimate' | 'fixed_buffer_20' | 'optimized_balanced', StrategyEvidence>
  deltas: { collection_success_percentage_points_vs_exact: string; average_excess_reduction_paise_vs_fixed_20: number }
  block_distribution: Array<{ lower_paise: number; upper_paise: number; count: number }>
  tradeoff_points: Array<{ strategy: string; average_excess_block_paise: number; collection_success_rate: string }>
  per_city: Record<string, { record_count: number; optimized_collection_success_rate: string; optimized_average_excess_block_paise: number }>
  personalization: Record<'stable_history' | 'overrun_prone', { prediction_mode: string; history_count: number; q97_paise: number; recommended_block_paise: number }>
  dynamic: {
    record_count: number
    static: StrategyEvidence
    dynamic: StrategyEvidence
    dynamic_diagnostics: { average_initial_block_paise: number; average_final_authorized_block_paise: number; rides_requiring_additional_block_rate: string }
  }
  strategy_comparison?: {
    confidence_intervals_95: Record<string, {
      collection_success_rate: { point_estimate: string; lower: string; upper: string; method: string }
      average_excess_block_paise: { point_estimate: string; lower: string; upper: string; method: string; samples: number }
    }>
  }
  prediction_calibration?: {
    quantiles: Record<string, {
      target_coverage: string
      observed_coverage: string
      calibration_error: string
      absolute_calibration_error: string
      pinball_loss_paise: string
    }>
    mean_pinball_loss_paise: string
    median_mae_paise: string
    raw_quantile_crossing: { record_count: number; record_frequency: string; adjacent_pair_count: number }
    prediction_mode_counts: Record<string, number>
  }
  agent_consistency?: {
    record_count: number
    successful_runs: number
    decision_mismatches: number
    average_tool_calls: number
  }
}

export interface ApiErrorBody {
  error: { code: string; message: string; details: Array<Record<string, unknown>> }
}

export interface HealthResponse {
  status: 'ok'
  version: string
  models_loaded: boolean
}
