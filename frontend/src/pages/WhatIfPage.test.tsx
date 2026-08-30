import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { dynamicFailure, dynamicSuccess, whatIfResponse } from '../test/fixtures'
import { WhatIfPage } from './WhatIfPage'

const mocks = vi.hoisted(() => ({ whatIf: vi.fn(), dynamicDemo: vi.fn() }))
vi.mock('../api/client', () => ({
  DashboardApiError: class extends Error {},
  api: { whatIf: mocks.whatIf, dynamicDemo: mocks.dynamicDemo },
}))

describe('WhatIfPage', () => {
  beforeEach(() => {
    mocks.whatIf.mockReset().mockResolvedValue(whatIfResponse)
    mocks.dynamicDemo.mockReset().mockImplementation((_risk: string, failure: boolean) => Promise.resolve(failure ? dynamicFailure : dynamicSuccess))
  })

  it('shows a recalculated previous-versus-new decision', async () => {
    render(<WhatIfPage />)
    expect((await screen.findAllByText('₹823.00')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹749.03').length).toBeGreaterThan(0)
    await waitFor(() => expect(mocks.whatIf).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ traffic_level: 'heavy' })))
  })

  it('proves a failed provider increase leaves the authorized amount unchanged', async () => {
    const user = userEvent.setup()
    render(<WhatIfPage />)
    await screen.findByText('Dynamic ride timeline')
    await user.click(screen.getByRole('button', { name: /Failure demo/ }))
    expect(await screen.findByText(/Target ₹823.00 · authorized remains ₹749.03/)).toBeInTheDocument()
  })
})
