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
  const optimized = evidence.strategies.optimized_balanced
  const histogram = evidence.block_distribution.map(bin => ({ label: `₹${Math.round(bin.lower_paise / 100)}`, count: bin.count }))
  const tradeoff = evidence.tradeoff_points.map(point => ({ name: strategyLabels[point.strategy as keyof typeof strategyLabels] ?? point.strategy, excess: point.average_excess_block_paise / 100, success: Number(point.collection_success_rate) * 100 }))
  return <section className="page evidence-page">
    <div className="page-heading"><div><span className="eyebrow">Reproducible backtest</span><h1>Evidence, not a hard-coded demo</h1><p>Three strategies evaluated on the same fresh, deterministic synthetic mobility dataset.</p></div><div className="provenance-chip"><Database size={17} /><div><strong>{evidence.provenance.record_count.toLocaleString('en-IN')} records</strong><span>Seed {evidence.provenance.seed}</span></div></div></div>
    <div className="provenance-bar"><span><Database size={15} /> {evidence.provenance.dataset}</span><span><Sparkles size={15} /> {evidence.provenance.predictor}</span><span><ShieldCheck size={15} /> Balanced / 97%</span><span>v{evidence.provenance.project_version}</span></div>
    <div className="kpi-grid">
      <article><span>Collection success</span><strong>{formatProbability(optimized.collection_success_rate)}</strong><small>realized on simulated outcomes</small></article>
      <article><span>Average excess block</span><strong>{formatMoney(optimized.average_excess_block_paise)}</strong><small>unused reserve per ride</small></article>
      <article><span>Under-block rate</span><strong>{formatProbability(optimized.under_block_rate)}</strong><small>retrospective outcome metric</small></article>
      <article><span>Capital efficiency</span><strong>{formatProbability(optimized.capital_efficiency)}</strong><small>actual ÷ blocked capital</small></article>
    </div>
    <div className="evidence-grid">
      <article className="panel strategy-panel">
        <div className="panel-heading"><div><span className="step-number">01</span><div><h2>Same rides, three strategies</h2><p>Calculated from existing evaluation services</p></div></div></div>
        <div className="delta-callouts"><div><b>+{evidence.deltas.collection_success_percentage_points_vs_exact} pts</b><span>collection success vs Exact</span></div><div><b>{formatMoney(evidence.deltas.average_excess_reduction_paise_vs_fixed_20)}</b><span>less average excess vs Fixed 20%</span></div></div>
        <div className="table-wrap"><table><thead><tr><th>Metric</th>{Object.values(strategyLabels).map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>
          <tr><td>Collection success</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatProbability(evidence.strategies[key as keyof typeof strategyLabels].collection_success_rate)}</td>)}</tr>
          <tr><td>Average excess</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatMoney(evidence.strategies[key as keyof typeof strategyLabels].average_excess_block_paise)}</td>)}</tr>
          <tr><td>Under-block rate</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatProbability(evidence.strategies[key as keyof typeof strategyLabels].under_block_rate)}</td>)}</tr>
          <tr><td>Capital efficiency</td>{Object.keys(strategyLabels).map(key => <td key={key}>{formatProbability(evidence.strategies[key as keyof typeof strategyLabels].capital_efficiency)}</td>)}</tr>
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
        <div className="city-grid">{Object.entries(evidence.per_city).map(([city, value]) => <div key={city}><span>{titleCase(city)}</span><strong>{formatProbability(value.optimized_collection_success_rate)}</strong><small>{value.record_count.toLocaleString('en-IN')} rides · {formatMoney(value.optimized_average_excess_block_paise)} excess</small></div>)}</div>
      </article>
    </div>
    <div className="evidence-bottom">
      <article className="panel personalization-proof"><span className="eyebrow">Personalization evidence</span><h2>Same ride. Different completed history.</h2><div>{(['stable_history','overrun_prone'] as const).map(profile => <div key={profile}><span>{profile === 'stable_history' ? 'Stable history' : 'Overrun-prone history'}</span><strong>{formatMoney(evidence.personalization[profile].recommended_block_paise)}</strong><small>Q97 {formatMoney(evidence.personalization[profile].q97_paise)} · {evidence.personalization[profile].history_count} rides</small></div>)}</div></article>
      <article className="panel dynamic-proof"><span className="eyebrow">Dynamic evidence</span><h2>Static versus adaptive reserve</h2><div className="dynamic-proof-grid"><div><span>Static success</span><strong>{formatProbability(evidence.dynamic.static.collection_success_rate)}</strong></div><div><span>Dynamic success</span><strong>{formatProbability(evidence.dynamic.dynamic.collection_success_rate)}</strong></div><div><span>Average initial block</span><strong>{formatMoney(evidence.dynamic.dynamic_diagnostics.average_initial_block_paise)}</strong></div><div><span>Average final block</span><strong>{formatMoney(evidence.dynamic.dynamic_diagnostics.average_final_authorized_block_paise)}</strong></div></div><small>{formatProbability(evidence.dynamic.dynamic_diagnostics.rides_requiring_additional_block_rate)} of simulated rides required an increase.</small></article>
    </div>
    <div className="evidence-disclaimer"><Fingerprint size={16} /><span>{evidence.provenance.synthetic_data_disclaimer} Dataset fingerprint: <code>{evidence.provenance.dataset_fingerprint_sha256.slice(0, 16)}…</code></span></div>
  </section>
}
