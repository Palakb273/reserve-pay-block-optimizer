import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { agentDecideResponse, optimizeResponse } from '../test/fixtures'
import { OptimizerPage } from './OptimizerPage'

const mocks = vi.hoisted(() => ({
  optimize: vi.fn(),
  agentDecide: vi.fn(),
  authorizeMock: vi.fn(),
}))

vi.mock('../api/client', () => ({
  DashboardApiError: class extends Error {},
  api: {
    optimize: mocks.optimize,
    agentDecide: mocks.agentDecide,
    authorizeMock: mocks.authorizeMock,
  },
}))

describe('OptimizerPage', () => {
  beforeEach(() => {
    mocks.optimize.mockReset().mockResolvedValue(optimizeResponse)
    mocks.agentDecide.mockReset().mockResolvedValue(agentDecideResponse)
    mocks.authorizeMock.mockReset().mockResolvedValue({
      execution: { status: 'authorized', authorized_amount_paise: 74903 },
    })
  })

  it('renders backend recommendation, uncertainty and personalization evidence', async () => {
    render(<OptimizerPage />)
    expect((await screen.findAllByText('₹749.03')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('97.0%').length).toBeGreaterThan(0)
    expect(screen.getByText('Personalized')).toBeInTheDocument()
    expect(screen.getByText(/Actual fare and provider state are excluded/)).toBeInTheDocument()
    expect(mocks.optimize).toHaveBeenCalledWith(expect.objectContaining({ risk_profile: 'balanced' }))
  })

  it('renders Agent Decision Trace with tool execution sequence', async () => {
    const user = userEvent.setup()
    render(<OptimizerPage />)
    expect(await screen.findByText('Reserve Intelligence Agent Trace')).toBeInTheDocument()
    expect(screen.getByText('RUN-TEST-001')).toBeInTheDocument()
    
    // Expand trace
    await user.click(screen.getByRole('button', { name: /View Tool Trace/ }))
    expect(await screen.findByText(/1\. get_customer_history/)).toBeInTheDocument()
    expect(screen.getByText(/4\. optimize_block/)).toBeInTheDocument()
  })

  it('changes policy through the real request and keeps execution separate', async () => {
    const user = userEvent.setup()
    render(<OptimizerPage />)
    await screen.findAllByText('₹749.03')
    await user.click(screen.getByRole('button', { name: /Conservative/ }))
    await user.click(screen.getByRole('button', { name: /Calculate recommended block/ }))
    await waitFor(() =>
      expect(mocks.optimize).toHaveBeenLastCalledWith(
        expect.objectContaining({ risk_profile: 'conservative' })
      )
    )
    await user.click(screen.getByRole('button', { name: /Authorize recommended block/ }))
    expect(await screen.findByText('AUTHORIZED')).toBeInTheDocument()
    expect(mocks.authorizeMock).toHaveBeenCalledTimes(1)
  })
})
