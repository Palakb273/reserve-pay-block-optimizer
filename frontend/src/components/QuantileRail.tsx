import type { OptimizeResponse } from '../types/api'
import { formatMoney } from '../utils/format'

export function QuantileRail({ result }: { result: OptimizeResponse }) {
  const quantiles = result.prediction.quantiles_paise
  const points = ['0.50', '0.90', '0.95', '0.97', '0.99'] as const
  const values = [...points.map(key => quantiles[key]), result.transaction.estimated_amount_paise, result.decision.recommended_block_paise]
  const min = Math.min(...values) * 0.98
  const max = Math.max(...values) * 1.02
  const position = (value: number) => `${((value - min) / Math.max(max - min, 1)) * 100}%`
  return <div className="quantile-card" aria-label="Modeled fare quantiles">
    <div className="quantile-heading"><span>Conditional fare quantiles</span><small>Discrete modeled estimates · not a density curve</small></div>
    <div className="rail-wrap">
      <div className="rail-line" />
      {points.map(key => <div className="rail-point" style={{ left: position(quantiles[key]) }} key={key}>
        <span className="dot" /><b>Q{Number(key) * 100}</b><small>{formatMoney(quantiles[key])}</small>
      </div>)}
      <div className="rail-marker estimate" style={{ left: position(result.transaction.estimated_amount_paise) }}><span>Estimate</span></div>
      <div className="rail-marker recommendation" style={{ left: position(result.decision.recommended_block_paise) }}><span>Recommended</span></div>
    </div>
  </div>
}
