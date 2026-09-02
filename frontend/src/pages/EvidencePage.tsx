import { useEffect, useState } from 'react'
import { BarChart3, Database, Fingerprint, MapPin, Scale, ShieldCheck, Sparkles } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { api, DashboardApiError } from '../api/client'
import { ErrorState, LoadingState } from '../components/States'
import type { EvidenceResponse } from '../types/api'
import { formatMoney, formatProbability, titleCase } from '../utils/format'

const strategyLabels = { exact_estimate: 'Exact Estimate', fixed_buffer_20: 'Fixed 20%', optimized_balanced: 'Optimized' }

export function EvidencePage() {
  const [evidence, setEvidence] = useState<EvidenceResponse | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { void api.evidence().then(setEvidence).catch(reason => setError(reason instanceof DashboardApiError ? reason.message : 'Evidence could not be loaded.')) }, [])
  if (error) return <section className="page"><ErrorState message={error} /></section>
  if (!evidence) return <section className="page evidence-loading"><LoadingState label="Loading precomputed evidence" /></section>
  const strategies = evidence.primary_strategy_comparison.metrics
  const optimized = strategies.optimized_balanced
  const histogram = evidence.primary_strategy_comparison.block_distribution.map(bin => ({ label: `₹${Math.round(bin.lower_paise / 100)}`, count: bin.count }))
  const tradeoff = evidence.primary_strategy_comparison.tradeoff_points.map(point => ({ name: strategyLabels[point.strategy as keyof typeof strategyLabels] ?? point.strategy, excess: point.average_excess_block_paise / 100, success: Number(point.collection_success_rate) * 100 }))
  const calibrationQuantiles = ['0.50', '0.90', '0.95', '0.97', '0.99']
  const confidence = evidence.primary_strategy_comparison.confidence_intervals_95
  return <section className="page evidence-page">
    <div className="page-heading"><div><span className="eyebrow">Reproducible backtest</span><h1>Evidence, not a hard-coded demo</h1><p>Three strategies evaluated on the same fresh, deterministic synthetic mobility dataset.</p></div><div className="provenance-chip"><Database size={17} /><div><strong>{evidence.metadata.record_count.toLocaleString('en-IN')} records</strong><span>Seed {evidence.metadata.dataset_seed}</span></div></div></div>
    <div className="provenance-bar"><span><Database size={15} /> {evidence.metadata.dataset}</span><span><Sparkles size={15} /> {evidence.metadata.personalized_model.model_version}</span><span><ShieldCheck size={15} /> Balanced / 97%</span><span>v{evidence.metadata.project_version}</span></div>
    <div className="kpi-grid">
      <article><span>Collection success</span><strong>{formatProbability(optimized.collection_success_rate)}</strong><small>realized on simulated outcomes</small></article>
      <article><span>Average excess block</span><strong>{formatMoney(optimized.average_excess_block_paise)}</strong><small>unused reserve per ride</small></article>
      <article><span>Under-block rate</span><strong>{formatProbability(optimized.under_block_rate)}</strong><small>retrospective outcome metric</small></article>
      <article><span>Capital efficiency</span><strong>{formatProbability(optimized.capital_efficiency)}</strong><small>actual ÷ blocked capital</small></article>
    </div>
    <div className="evidence-grid">
      <article className="panel strategy-panel">
        <div className="panel-heading"><div><span className="step-number">01</span><div><h2>Same rides, three strategies</h2><p>Calculated from existing evaluation services</p></div></div></div>
        <div className="delta-callouts"><div><b>+{evidence.primary_strategy_comparison.deltas.optimized_collection_success_percentage_points_vs_exact} pts</b><span>collection success vs Exact</span></div><div><b>{formatMoney(evidence.primary_strategy_comparison.deltas.optimized_average_excess_reduction_paise_vs_fixed_20)}</b><span>less average excess vs Fixed 20%</span></div></div>
        <div className="table-wrap"><table><thead><tr><th>Metric</th>{Object.values(strategyLabels).map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
          <tr><td>Collection success</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatProbability(strategies[key as keyof typeof strategyLabels].collection_success_rate)}</td>)}</tr>
          <tr><td>Average excess</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatMoney(strategies[key as keyof typeof strategyLabels].average_excess_block_paise)}</td>)}</tr>
          <tr><td>Under-block rate</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatProbability(strategies[key as keyof typeof strategyLabels].under_block_rate)}</td>)}</tr>
          <tr><td>Capital efficiency</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatProbability(strategies[key as keyof typeof strategyLabels].capital_efficiency)}</td>)}</tr>
        </tbody></table></div>
      </article>
      <article className="panel chart-panel">
        <div className="panel-heading"><div><BarChart3 size={19} /><div><h2>Optimized block distribution</h2><p>Deterministically binned recommended amounts</p></div></div></div>
        <div className="chart-box" aria-label="Optimized block distribution chart"><ResponsiveContainer width="100%" height="100%"><BarChart data={histogram}><CartesianGrid vertical={false} stroke="#e8ece9" /><XAxis dataKey="label" tickLine={false} axisLine={false} interval={2} /><YAxis tickLine={false} axisLine={false} width={36} /><Tooltip /><Bar dataKey="count" fill="#0e7c66" radius={[5,5,0,0]} /></BarChart></ResponsiveContainer></div>
      </article>
      <article className="panel chart-panel tradeoff-panel">
        <div className="panel-heading"><div><Scale size={19} /><div><h2>Excess versus success</h2><p>Each point is one complete strategy</p></div></div></div>
        <div className="chart-box" aria-label="Excess versus success chart"><ResponsiveContainer width="100%" height="100%"><ScatterChart margin={{ left: 4, right: 18, top: 12, bottom: 6 }}><CartesianGrid stroke="#e8ece9" /><XAxis type="number" dataKey="excess" name="Average excess ₹" unit="₹" /><YAxis type="number" dataKey="success" name="Collection success" unit="%" domain={['dataMin - 3', 100]} /><Tooltip cursor={{ strokeDasharray: '3 3' }} /><Scatter data={tradeoff} fill="#ef7c55" /></ScatterChart></ResponsiveContainer></div>
        <div className="point-legend">{tradeoff.map(point => <span key={point.name}><i />{point.name}</span>)}</div>
      </article>
      <article className="panel city-panel">
        <div className="panel-heading"><div><MapPin size={19} /><div><h2>India-specific diagnostics</h2><p>Synthetic profiles, not production city statistics</p></div></div></div>
        <div className="city-grid">{Object.entries(evidence.cities).map(([city, value]) => <div key={city}><span>{titleCase(city)}</span><strong>{formatProbability(value.optimized_collection_success_rate)}</strong><small>{value.record_count.toLocaleString('en-IN')} rides · {formatMoney(value.optimized_average_excess_block_paise)} excess</small></div>)}</div>
      </article>
    </div>
    {confidence && <div className="evidence-statistics">
      <article className="panel calibration-panel">
        <div className="panel-heading"><div><ShieldCheck size={19} /><div><h2>Calibration on fresh rides</h2><p>Observed coverage is empirical, not guaranteed</p></div></div></div>
        <div className="table-wrap"><table><thead><tr><th>Quantile</th><th>Target</th><th>Observed</th><th>Error</th></tr></thead><tbody>
          {calibrationQuantiles.map(key => { const metric = evidence.prediction.quantiles[key]; return <tr key={key}><td>Q{Math.round(Number(key) * 100)}</td><td>{formatProbability(metric.target_coverage)}</td><td>{formatProbability(metric.observed_coverage)}</td><td>{(Number(metric.calibration_error) * 100).toFixed(2)} pts</td></tr> })}
        </tbody></table></div>
        <small>Raw crossing: {formatProbability(evidence.prediction.raw_quantile_crossing.record_frequency)} · Median MAE {formatMoney(Math.round(Number(evidence.prediction.median_mae_paise)))}</small>
        <p><strong>Limitation:</strong> high-quantile under-coverage is material on this synthetic cohort; production use requires recalibration and external validation.</p>
      </article>
      <article className="panel confidence-panel">
        <div className="panel-heading"><div><Fingerprint size={19} /><div><h2>95% statistical confidence</h2><p>Wilson success intervals and seeded bootstrap excess intervals</p></div></div></div>
        <div className="confidence-list">{Object.keys(strategyLabels).map(key => { const interval = confidence[key]; return <div key={key}><span>{strategyLabels[key as keyof typeof strategyLabels]}</span><strong>{formatProbability(interval.collection_success_rate.lower)}–{formatProbability(interval.collection_success_rate.upper)}</strong><small>Average excess {formatMoney(Math.round(Number(interval.average_excess_block_paise.point_estimate)))} · {interval.average_excess_block_paise.samples.toLocaleString('en-IN')} resamples</small></div> })}</div>
        <div className="agent-equivalence"><ShieldCheck size={15} /><b>{evidence.agents.decision_mismatches} mismatches</b><span>across {evidence.agents.runs.toLocaleString('en-IN')} direct vs agent decisions</span></div>
      </article>
    </div>}
    <div className="evidence-bottom">
      <article className="panel personalization-proof"><span className="eyebrow">Personalization evidence</span><h2>Same ride. Different completed history.</h2><div>{(['stable_history','overrun_prone'] as const).map(profile => <div key={profile}><span>{profile === 'stable_history' ? 'Stable history' : 'Overrun-prone history'}</span><strong>{formatMoney(evidence.personalization.same_ride_history_demo[profile].recommended_block_paise)}</strong><small>Q97 {formatMoney(evidence.personalization.same_ride_history_demo[profile].q97_paise)} · {evidence.personalization.same_ride_history_demo[profile].history_count} rides</small></div>)}</div></article>
      <article className="panel dynamic-proof"><span className="eyebrow">Dynamic evidence</span><h2>Static versus adaptive reserve</h2><div className="dynamic-proof-grid"><div><span>Static success</span><strong>{formatProbability(evidence.dynamic.static.collection_success_rate)}</strong></div><div><span>Dynamic success</span><strong>{formatProbability(evidence.dynamic.dynamic.collection_success_rate)}</strong></div><div><span>Average initial block</span><strong>{formatMoney(evidence.dynamic.dynamic_diagnostics.average_initial_block_paise)}</strong></div><div><span>Average final block</span><strong>{formatMoney(evidence.dynamic.dynamic_diagnostics.average_final_authorized_block_paise)}</strong></div></div><small>{formatProbability(evidence.dynamic.dynamic_diagnostics.rides_requiring_additional_block_rate)} of simulated rides required an increase.</small></article>
    </div>
    <article className="panel"><span className="eyebrow">Advanced evidence</span><h2>Auditable validation details</h2>
      <details><summary>Risk-profile collapse</summary><p>All profiles selected the same block on {formatProbability(evidence.risk_profiles.collapse_analysis.all_three_same_rate)} of rides. {evidence.risk_profiles.collapse_analysis.interpretation}</p></details>
      <details><summary>Personalization cohorts</summary><p>{evidence.personalization.test_records.toLocaleString('en-IN')} records; minimum history {evidence.personalization.minimum_personalization_history}; history-depth and observed-segment diagnostics are included in the artifact.</p></details>
      <details><summary>Dynamic benefit categories</summary><pre>{JSON.stringify(evidence.dynamic.benefit_breakdown, null, 2)}</pre></details>
      <details><summary>Agent, explanation, and execution validation</summary><p>Agent equivalence {formatProbability(evidence.agents.decision_equivalence_rate)}; explanations {evidence.explainability.record_count}; mock lifecycle {evidence.reserve_pay_mock_validation.passed_scenarios}/{evidence.reserve_pay_mock_validation.total_scenarios} passed.</p></details>
      <details><summary>Limitations</summary><ul>{evidence.limitations.map(item => <li key={item}>{item}</li>)}</ul></details>
    </article>
    <div className="evidence-disclaimer"><Fingerprint size={16} /><span>Synthetic evidence only; not production city statistics. Dataset fingerprint: <code>{evidence.metadata.dataset_fingerprint_sha256.slice(0, 16)}…</code> Evidence fingerprint: <code>{evidence.metadata.evidence_fingerprint_sha256.slice(0, 16)}…</code></span></div>
  </section>
}
