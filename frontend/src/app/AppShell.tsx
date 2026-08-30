import { useEffect, useState } from 'react'
import { Activity, BarChart3, Calculator, FlaskConical } from 'lucide-react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'

const links = [
  { to: '/optimizer', label: 'Optimizer', icon: Calculator },
  { to: '/what-if', label: 'What-if Simulator', icon: FlaskConical },
  { to: '/evidence', label: 'Evidence', icon: BarChart3 },
]

export function AppShell() {
  const [health, setHealth] = useState<'checking' | 'ready' | 'unavailable'>('checking')
  useEffect(() => {
    void api.health()
      .then(result => setHealth(result.models_loaded ? 'ready' : 'unavailable'))
      .catch(() => setHealth('unavailable'))
  }, [])
  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark"><Activity size={21} /></span><div><strong>Reserve Pay Block Optimizer</strong><small>Hackathon Prototype</small></div></div>
      <nav aria-label="Primary navigation">{links.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to}><Icon size={17} />{label}</NavLink>)}</nav>
      <div className={`system-chip ${health}`}><span /> {health === 'ready' ? 'Models ready' : health === 'checking' ? 'Checking models' : 'Models unavailable'}</div>
    </header>
    <main><Outlet /></main>
    <footer><span>Modeled estimates, not guarantees.</span><span>Mock Reserve Pay · Synthetic India mobility data</span></footer>
  </div>
}
