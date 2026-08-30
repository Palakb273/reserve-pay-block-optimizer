import type { OptimizeInput } from '../types/api'

export const DEFAULT_TRANSACTION: OptimizeInput = {
  transaction_id: 'DASHBOARD-DEMO-001',
  estimated_amount_paise: 65000,
  city: 'hyderabad',
  distance_km: '18.4',
  estimated_duration_minutes: 42,
  surge_multiplier: '1.18',
  timestamp: '2027-01-15T18:30:00+05:30',
  customer_profile: 'stable_history',
  risk_profile: 'balanced',
}
