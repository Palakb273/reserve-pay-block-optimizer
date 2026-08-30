import type { ApiErrorBody, DynamicDemoResponse, EvidenceResponse, HealthResponse, OptimizeInput, OptimizeResponse, WhatIfResponse } from '../types/api'

export class DashboardApiError extends Error {
  constructor(public code: string, message: string) {
    super(message)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  const body = await response.json() as T | ApiErrorBody
  if (!response.ok) {
    const error = body as ApiErrorBody
    throw new DashboardApiError(error.error?.code ?? 'dashboard_error', error.error?.message ?? 'The dashboard request failed.')
  }
  return body as T
}

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  optimize: (transaction: OptimizeInput) => request<OptimizeResponse>('/api/optimize', { method: 'POST', body: JSON.stringify(transaction) }),
  agentDecide: (transaction: OptimizeInput) => request<import('../types/api').AgentDecideResponse>('/api/agent/decide', { method: 'POST', body: JSON.stringify({ transaction }) }),
  whatIf: (base: OptimizeInput, overrides: Record<string, unknown>) => request<WhatIfResponse>('/api/what-if', { method: 'POST', body: JSON.stringify({ base, overrides }) }),
  authorizeMock: (transaction: OptimizeInput, idempotencyKey: string, simulateFailure = false) => request<{ recommendation: OptimizeResponse; execution: Record<string, unknown> }>('/api/mock/authorize', { method: 'POST', body: JSON.stringify({ transaction, idempotency_key: idempotencyKey, simulate_failure: simulateFailure }) }),
  dynamicDemo: (riskProfile: string, failFirstIncrease: boolean) => request<DynamicDemoResponse>('/api/dynamic-demo', { method: 'POST', body: JSON.stringify({ risk_profile: riskProfile, fail_first_increase: failFirstIncrease }) }),
  evidence: () => request<EvidenceResponse>('/api/evidence'),
}
