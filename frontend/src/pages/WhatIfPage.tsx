import { useEffect, useState } from 'react'
import { ArrowDown, CheckCircle2, CircleX, RefreshCcw, Route, TimerReset } from 'lucide-react'
import { api, DashboardApiError } from '../api/client'
import { DEFAULT_TRANSACTION } from '../app/defaults'
import { ErrorState, LoadingState } from '../components/States'
import type { CustomerProfile, DynamicDemoResponse, RiskProfile, WhatIfResponse } from '../types/api'
import { formatMoney, formatProbability, titleCase } from '../utils/format'

export function WhatIfPage() {
  const [distance, setDistance] = useState(22.6)
  const [traffic, setTraffic] = useState('heavy')
  const [surge, setSurge] = useState(1.28)
  const [risk, setRisk] = useState<RiskProfile>('balanced')
  const [customer, setCustomer] = useState<CustomerProfile>('stable_history')
  const [result, setResult] = useState<WhatIfResponse | null>(null)
  const [dynamic, setDynamic] = useState<DynamicDemoResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true); setError('')
    const timer = window.setTimeout(() => {
      void api.whatIf(DEFAULT_TRANSACTION, { distance_km: String(distance), traffic_level: traffic, surge_multiplier: String(surge), risk_profile: risk, customer_profile: customer })
        .then(setResult)
        .catch(reason => setError(reason instanceof DashboardApiError ? reason.message : 'What-if re-optimization failed.'))
        .finally(() => setLoading(false))
    }, 220)
    return () => window.clearTimeout(timer)
  }, [distance, traffic, surge, risk, customer])

  const runDynamic = (failure: boolean) => {
    setError('')
    void api.dynamicDemo(risk, failure).then(setDynamic).catch(reason => setError(reason instanceof Error ? reason.message : 'Dynamic demo failed.'))
  }
  useEffect(() => { runDynamic(false) }, [])
  const reset = () => { setDistance(22.6); setTraffic('heavy'); setSurge(1.28); setRisk('balanced'); setCustomer('stable_history') }

  return <section className="page whatif-page">
    <div className="page-heading"><div><span className="eyebrow">Interactive scenario</span><h1>What changes the reserve?</h1><p>Change legitimate decision-time conditions and compare two complete backend decisions.</p></div><button className="ghost-button" onClick={reset}><RefreshCcw size={16} /> Reset demo</button></div>
    {error && <ErrorState message={error} />}
    <div className="whatif-layout">
      <aside className="panel control-stack">
        <div className="panel-heading"><div><span className="step-number">01</span><div><h2>Scenario controls</h2><p>Updates debounce for 220 ms</p></div></div>{loading && <LoadingState label="Updating" />}</div>
        <label className="range-field"><span><b>Distance</b><output>{distance.toFixed(1)} km</output></span><input aria-label="Distance scenario" type="range" min="5" max="40" step="0.1" value={distance} onChange={e => setDistance(Number(e.target.value))} /></label>
        <label><span>Traffic / projected duration</span><select aria-label="Traffic" value={traffic} onChange={e => setTraffic(e.target.value)}><option value="light">Light · 0.82× duration</option><option value="normal">Normal · 1.00× duration</option><option value="heavy">Heavy · 1.28× duration</option><option value="severe">Severe · 1.55× duration</option></select><small className="helper">Traffic maps only to projected duration in the backend adapter.</small></label>
        <label className="range-field"><span><b>Surge</b><output>{surge.toFixed(2)}×</output></span><input aria-label="Surge scenario" type="range" min="1" max="2" step="0.01" value={surge} onChange={e => setSurge(Number(e.target.value))} /></label>
        <label><span>Risk profile</span><select aria-label="What-if risk profile" value={risk} onChange={e => setRisk(e.target.value as RiskProfile)}><option value="aggressive">Aggressive · 93%</option><option value="balanced">Balanced · 97%</option><option value="conservative">Conservative · 99%</option></select></label>
        <label><span>Customer profile</span><select aria-label="What-if customer profile" value={customer} onChange={e => setCustomer(e.target.value as CustomerProfile)}><option value="cold_start">Cold Start</option><option value="stable_history">Stable History</option><option value="overrun_prone">Overrun-Prone History</option></select></label>
      </aside>

      <div className="comparison-column">
        {result && <article className="comparison-card">
          <div className="comparison-side previous"><span>Previous block</span><strong>{formatMoney(result.previous.decision.recommended_block_paise)}</strong><small>Q97 {formatMoney(result.previous.prediction.quantiles_paise['0.97'])}</small></div>
          <div className="change-arrow"><ArrowDown size={24} /><b>{result.difference.recommended_block_paise >= 0 ? '+' : '−'}{formatMoney(Math.abs(result.difference.recommended_block_paise))}</b><span>recommended reserve</span></div>
          <div className="comparison-side revised"><span>New block</span><strong>{formatMoney(result.revised.decision.recommended_block_paise)}</strong><small>{formatProbability(result.revised.decision.estimated_collection_probability)} modeled coverage</small></div>
          <div className="delta-grid"><div><span>Q97 change</span><b>{formatMoney(result.previous.prediction.quantiles_paise['0.97'])} → {formatMoney(result.revised.prediction.quantiles_paise['0.97'])}</b></div><div><span>Expected unused reserve</span><b>{formatMoney(result.previous.decision.expected_excess_block_paise)} → {formatMoney(result.revised.decision.expected_excess_block_paise)}</b></div><div><span>Prediction mode</span><b>{titleCase(result.revised.prediction.mode)}</b></div></div>
        </article>}
        {!result && !error && <div className="panel"><LoadingState label="Preparing comparison" /></div>}

        <article className="panel timeline-panel">
          <div className="panel-heading"><div><span className="step-number">02</span><div><h2>Dynamic ride timeline</h2><p>Recommendation and provider authorization remain separate</p></div></div><div className="timeline-actions"><button onClick={() => runDynamic(false)}><CheckCircle2 size={15} /> Auto-confirm</button><button onClick={() => runDynamic(true)}><CircleX size={15} /> Failure demo</button></div></div>
          {!dynamic ? <LoadingState label="Loading dynamic ride" /> : <div className="timeline">{dynamic.timeline.map((stage, index) => <div className="timeline-stage" key={`${stage.stage}-${index}`}>
            <div className={`timeline-node ${stage.execution_status}`}><span>{index + 1}</span></div>
            <div className="timeline-content"><div><span className="timeline-label">{stage.stage}</span><strong>{formatMoney(stage.recommended_target_paise)}</strong><small>recommended target</small></div><dl><div><dt>Authorized</dt><dd>{formatMoney(stage.authorized_amount_paise)}</dd></div>{stage.q97_paise !== undefined && <div><dt>Q97 / Q99</dt><dd>{formatMoney(stage.q97_paise)} / {formatMoney(stage.q99_paise ?? 0)}</dd></div>}<div><dt>Additional</dt><dd>{formatMoney(stage.additional_required_paise)}</dd></div><div><dt>Execution</dt><dd className={stage.execution_status === 'failed' ? 'danger-text' : 'success-text'}>{titleCase(stage.execution_status)}</dd></div></dl>{stage.execution_status === 'failed' && <div className="failure-proof"><CircleX size={16} /><span>Target {formatMoney(stage.recommended_target_paise)} · authorized remains {formatMoney(stage.authorized_amount_paise)}</span></div>}</div>
          </div>)}</div>}
          <div className="timeline-note"><TimerReset size={16} /><span>Actual fare appears only at completion. It never flows back into re-optimization.</span><Route size={16} /></div>
        </article>
      </div>
    </div>
  </section>
}
