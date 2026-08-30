import { useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, ChevronDown, RefreshCcw, ShieldCheck, Sparkles, WalletCards } from 'lucide-react'
import { api, DashboardApiError } from '../api/client'
import { DEFAULT_TRANSACTION } from '../app/defaults'
import { QuantileRail } from '../components/QuantileRail'
import { ErrorState, LoadingState } from '../components/States'
import type { City, CustomerProfile, OptimizeInput, OptimizeResponse, RiskProfile } from '../types/api'
import { formatMoney, formatProbability, titleCase } from '../utils/format'

const profiles: Array<{ id: RiskProfile; label: string; target: string }> = [
  { id: 'aggressive', label: 'Aggressive', target: '93%' },
  { id: 'balanced', label: 'Balanced', target: '97%' },
  { id: 'conservative', label: 'Conservative', target: '99%' },
]

export function OptimizerPage() {
  const [input, setInput] = useState<OptimizeInput>({ ...DEFAULT_TRANSACTION })
  const [result, setResult] = useState<OptimizeResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [execution, setExecution] = useState<Record<string, unknown> | null>(null)
  const [executing, setExecuting] = useState(false)

  const optimize = async (payload = input) => {
    setLoading(true); setError(''); setExecution(null)
    try { setResult(await api.optimize(payload)) }
    catch (reason) { setError(reason instanceof DashboardApiError ? reason.message : 'The optimization service is unavailable.') }
    finally { setLoading(false) }
  }
  useEffect(() => { void optimize(DEFAULT_TRANSACTION) }, [])

  const submit = (event: FormEvent) => { event.preventDefault(); void optimize() }
  const reset = () => { const value = { ...DEFAULT_TRANSACTION }; setInput(value); void optimize(value) }
  const authorize = async () => {
    if (!result) return
    setExecuting(true); setError('')
    try {
      const response = await api.authorizeMock(input, `${input.transaction_id}:${result.decision.recommended_block_paise}:dashboard`)
      setExecution(response.execution)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Mock authorization failed.') }
    finally { setExecuting(false) }
  }

  return <section className="page optimizer-page">
    <div className="page-heading"><div><span className="eyebrow">Decision workspace</span><h1>How much should we reserve?</h1><p>Set the ride context. The Python decision engine predicts uncertainty, applies merchant policy, and returns one exact block.</p></div><button className="ghost-button" onClick={reset}><RefreshCcw size={16} /> Reset demo</button></div>
    <div className="optimizer-grid">
      <form className="panel input-panel" onSubmit={submit}>
        <div className="panel-heading"><div><span className="step-number">01</span><div><h2>Transaction context</h2><p>Information available before the ride begins</p></div></div></div>
        <div className="field-grid">
          <label><span>Estimated fare</span><div className="money-input"><b>₹</b><input aria-label="Estimated fare" type="number" min="1" step="1" value={input.estimated_amount_paise / 100} onChange={e => setInput({ ...input, estimated_amount_paise: Math.round(Number(e.target.value) * 100) })} /></div></label>
          <label><span>City</span><select aria-label="City" value={input.city} onChange={e => setInput({ ...input, city: e.target.value as City })}>{['delhi','mumbai','bengaluru','hyderabad','pune','chennai','kolkata'].map(city => <option value={city} key={city}>{titleCase(city)}</option>)}</select></label>
          <label><span>Distance</span><div className="suffix-input"><input aria-label="Distance" type="number" min="0" step="0.1" value={input.distance_km} onChange={e => setInput({ ...input, distance_km: e.target.value })} /><b>km</b></div></label>
          <label><span>Projected duration</span><div className="suffix-input"><input aria-label="Projected duration" type="number" min="0" value={input.estimated_duration_minutes} onChange={e => setInput({ ...input, estimated_duration_minutes: Number(e.target.value) })} /><b>min</b></div></label>
          <label><span>Surge multiplier</span><div className="suffix-input"><input aria-label="Surge multiplier" type="number" min="0.01" step="0.01" value={input.surge_multiplier} onChange={e => setInput({ ...input, surge_multiplier: e.target.value })} /><b>×</b></div></label>
          <label><span>Customer</span><select aria-label="Customer profile" value={input.customer_profile} onChange={e => setInput({ ...input, customer_profile: e.target.value as CustomerProfile })}><option value="cold_start">Cold Start</option><option value="stable_history">Stable History</option><option value="overrun_prone">Overrun-Prone History</option></select></label>
        </div>
        <fieldset className="risk-selector"><legend>Merchant risk policy</legend><div>{profiles.map(profile => <button aria-pressed={input.risk_profile === profile.id} type="button" key={profile.id} onClick={() => setInput({ ...input, risk_profile: profile.id })}><span>{profile.label}</span><small>{profile.target} minimum modeled coverage</small></button>)}</div></fieldset>
        <button className="primary-button" type="submit" disabled={loading}>{loading ? <LoadingState label="Optimizing" /> : <><Sparkles size={17} /> Calculate recommended block</>}</button>
        <small className="decision-boundary"><ShieldCheck size={14} /> Actual fare and provider state are excluded from this decision.</small>
      </form>

      <div className="result-column">
        {error && <ErrorState message={error} />}
        {!result && !error && <div className="panel result-skeleton"><LoadingState label="Loading recommendation" /></div>}
        {result && <>
          <article className="hero-result">
            <div className="hero-top"><span className="step-number light">02</span><span>Recommended block</span><span className="live-pill"><i /> Calculated</span></div>
            <div className="hero-number">{formatMoney(result.decision.recommended_block_paise)}</div>
            <div className="coverage-line"><CheckCircle2 size={19} /><strong>{formatProbability(result.decision.estimated_collection_probability)}</strong> modeled collection coverage</div>
            <div className="hero-metrics">
              <div><span>Estimated fare</span><strong>{formatMoney(result.transaction.estimated_amount_paise)}</strong></div>
              <div><span>Expected unused reserve</span><strong>{formatMoney(result.decision.expected_excess_block_paise)}</strong></div>
              <div><span>Modeled fare interval</span><strong>{formatMoney(result.prediction.modeled_range.lower_amount_paise)} – {formatMoney(result.prediction.modeled_range.upper_amount_paise)}</strong><small>Q05–Q95, not guaranteed</small></div>
              <div><span>Decision mode</span><strong>{titleCase(result.prediction.mode)}</strong><small>{result.prediction.history_count} eligible rides</small></div>
            </div>
            <div className="policy-strip"><ShieldCheck size={18} /><div><strong>{titleCase(result.policy.profile)} merchant policy</strong><span>Minimum modeled coverage {formatProbability(result.policy.target_collection_probability)}</span></div></div>
          </article>
          <QuantileRail result={result} />
          <article className="panel explanation-panel">
            <div className="panel-heading"><div><span className="step-number">03</span><div><h2>Why this amount?</h2><p>Deterministic evidence from the completed decision</p></div></div></div>
            <p className="explanation-copy">{result.explanation.summary}</p>
            <div className="factor-row">{result.explanation.factors.slice(0, 4).map(factor => <span key={factor.code}>{factor.label}</span>)}</div>
            <details><summary>View decision details <ChevronDown size={16} /></summary><p>{result.explanation.details}</p><div className="detail-grid"><div><span>Objective score</span><strong>{result.decision.objective_score}</strong></div>{Object.entries(result.explanation.objective_components).map(([key, value]) => <div key={key}><span>{titleCase(key)}</span><strong>{value}</strong></div>)}</div></details>
          </article>
          <article className="panel execution-panel">
            <div><span className="mock-label"><WalletCards size={16} /> Demo / Mock Reserve Provider</span><h2>Execution is optional and separate</h2><p>The recommendation exists before authorization. A failure never changes it.</p></div>
            <button className="secondary-button" onClick={authorize} disabled={executing}>{executing ? 'Authorizing…' : 'Authorize recommended block'}</button>
            {execution && <div className={`execution-status ${execution.status === 'authorized' ? 'success' : 'failed'}`}><strong>{String(execution.status).toUpperCase()}</strong><span>{execution.status === 'authorized' ? formatMoney(Number(execution.authorized_amount_paise)) : String((execution.error as { message?: string })?.message ?? 'Authorization failed')}</span></div>}
          </article>
        </>}
      </div>
    </div>
  </section>
}
