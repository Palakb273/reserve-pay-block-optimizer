import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { evidenceResponse } from '../test/fixtures'
import { EvidencePage } from './EvidencePage'

vi.mock('../api/client', () => ({
  DashboardApiError: class extends Error {},
  api: { evidence: vi.fn().mockResolvedValue(evidenceResponse) },
}))

describe('EvidencePage', () => {
  it('renders provenance, all baselines, calculated KPIs and audit charts', async () => {
    render(<EvidencePage />)
    expect(await screen.findByText('10,000 records')).toBeInTheDocument()
    expect(screen.getAllByText('Exact Estimate').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Fixed 20%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Optimized').length).toBeGreaterThan(0)
    expect(screen.getAllByText('97.1%').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Optimized block distribution chart')).toBeInTheDocument()
    expect(screen.getAllByText(/not production city statistics/).length).toBeGreaterThan(0)
    expect(screen.getByText('Calibration on fresh rides')).toBeInTheDocument()
    expect(screen.getByText('95% statistical confidence')).toBeInTheDocument()
    expect(screen.getByText('0 mismatches')).toBeInTheDocument()
  })
})
