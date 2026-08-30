import React, { lazy, Suspense } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './app/AppShell'
import { LoadingState } from './components/States'
import './styles.css'

const OptimizerPage = lazy(() => import('./pages/OptimizerPage').then(module => ({ default: module.OptimizerPage })))
const WhatIfPage = lazy(() => import('./pages/WhatIfPage').then(module => ({ default: module.WhatIfPage })))
const EvidencePage = lazy(() => import('./pages/EvidencePage').then(module => ({ default: module.EvidencePage })))
const page = (content: React.ReactNode) => <Suspense fallback={<section className="page evidence-loading"><LoadingState label="Loading screen" /></section>}>{content}</Suspense>

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><BrowserRouter><Routes>
    <Route element={<AppShell />}>
      <Route index element={<Navigate to="/optimizer" replace />} />
      <Route path="/optimizer" element={page(<OptimizerPage />)} />
      <Route path="/what-if" element={page(<WhatIfPage />)} />
      <Route path="/evidence" element={page(<EvidencePage />)} />
    </Route>
  </Routes></BrowserRouter></React.StrictMode>,
)
