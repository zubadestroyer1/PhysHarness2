import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../src/App'

const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), {
  status,
  headers: { 'Content-Type': 'application/json' },
}))

const emptyWorkspaceFetch = () => vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
  const path = String(input)
  if (path.endsWith('/v1/status')) return json({ version: '0.1.0', mode: 'local', checks: [], qualifications: [] })
  if (path.includes('/v1/events')) return json({ items: [] })
  return json({ items: [] })
})

describe('research console', () => {
  it('requires a user supplied token and renders actionable empty states', async () => {
    vi.stubGlobal('fetch', emptyWorkspaceFetch())
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('heading', { name: /connect to the research service/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/bearer token/i), 'operator-token')
    await user.click(screen.getByRole('button', { name: /connect/i }))

    expect(await screen.findByText(/no campaigns yet/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create campaign/i })).toBeInTheDocument()
  })

  it('keeps semantic, proof, assumptions, and novelty evidence visibly separate', async () => {
    const fetcher = emptyWorkspaceFetch()
    fetcher.mockImplementation((input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/v1/status')) return json({
        version: '0.1.0', mode: 'managed',
        checks: [{ name: 'api', status: 'healthy', detail: 'Process responds' }],
        qualifications: [{ wave: 'verification', status: 'unqualified', detail: 'Independent kernel unavailable' }],
      })
      if (path.endsWith('/v1/campaigns')) return json({ items: [{ id: 'c1', project_id: 'p1', revision: 1, created_at: '2026-09-14T00:00:00Z', title: 'Quantum structure', objective: 'Test rigidity', programs: ['quantum'] }] })
      if (path.endsWith('/v1/problems')) return json({ items: [{ id: 'p1', project_id: 'p1', revision: 2, created_at: '2026-09-14T00:00:00Z', campaign_id: 'c1', title: 'Channel rigidity', program: 'quantum', informal_statement: 'Informal target', formal_statement: 'theorem target', assumptions: ['finite dimensional'], definitions: {}, source: 'Operator notes', environment_digest: 'abc', target_theorem: 'target', target_digest: 'def', semantic_review: 'approved', novelty_status: 'unreviewed' }] })
      if (path.endsWith('/v1/claims')) return json({ items: [{ id: 'cl1', project_id: 'p1', revision: 1, created_at: '2026-09-14T00:00:00Z', experiment_id: 'e1', statement: 'Candidate equality', assumptions: ['finite dimensional'], evidence: 'conditional', proof_status: 'unqualified', novelty_status: 'unknown' }] })
      if (path.includes('/v1/events')) return json({ items: [] })
      return json({ items: [] })
    })
    vi.stubGlobal('fetch', fetcher)
    sessionStorage.setItem('physharness.token', 'token')
    render(<App />)

    await userEvent.click(await screen.findByRole('button', { name: /channel rigidity/i }))
    const detail = screen.getByRole('complementary', { name: /evidence detail/i })
    expect(within(detail).getByText('Approved')).toBeInTheDocument()
    expect(within(detail).getByText('Unreviewed')).toBeInTheDocument()
    expect(within(detail).getByText('finite dimensional')).toBeInTheDocument()
    expect(screen.getByText(/process responds/i)).toBeInTheDocument()
    expect(screen.getByText(/independent kernel unavailable/i)).toBeInTheDocument()
  })

  it('creates an experiment with exact runtime, model, decimal budget and idempotency', async () => {
    const fetcher = emptyWorkspaceFetch()
    fetcher.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'POST' && path.endsWith('/v1/experiments')) return json({ id: 'e2', revision: 1, status: 'draft' }, 201)
      if (path.endsWith('/v1/status')) return json({ version: '0.1.0', mode: 'local', checks: [], qualifications: [] })
      if (path.endsWith('/v1/campaigns')) return json({ items: [{ id: 'c1', project_id: 'p1', revision: 1, created_at: '2026-09-14T00:00:00Z', title: 'Rigidity', objective: 'Target', programs: ['quantum'] }] })
      if (path.endsWith('/v1/problems')) return json({ items: [{ id: 'p1', project_id: 'p1', revision: 1, created_at: '2026-09-14T00:00:00Z', campaign_id: 'c1', title: 'Main target', program: 'quantum', informal_statement: 'Target', formal_statement: '', assumptions: [], definitions: {}, source: 'notes', environment_digest: 'digest', target_theorem: 'target', target_digest: 'target-digest', semantic_review: 'pending' }] })
      if (path.includes('/v1/events')) return json({ items: [] })
      return json({ items: [] })
    })
    vi.stubGlobal('fetch', fetcher)
    vi.stubGlobal('crypto', { randomUUID: () => 'fixed-idempotency-key' })
    sessionStorage.setItem('physharness.token', 'token')
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /new experiment/i }))
    await user.selectOptions(screen.getByLabelText(/problem/i), 'p1')
    await user.type(screen.getByLabelText(/runtime/i), 'codex-sdk')
    await user.type(screen.getByLabelText(/^model$/i), 'gpt-research')
    await user.clear(screen.getByLabelText(/max cost/i))
    await user.type(screen.getByLabelText(/max cost/i), '12.50')
    await user.click(screen.getByRole('button', { name: /create experiment/i }))

    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/experiments$/),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': 'fixed-idempotency-key' }),
        body: expect.stringContaining('"max_cost_usd":"12.50"'),
      }),
    ))
    const call = fetcher.mock.calls.find(([input, init]) => String(input).endsWith('/v1/experiments') && init?.method === 'POST')
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
      campaign_id: 'c1', problem_id: 'p1',
      models: [{ runtime: 'codex-sdk', model: 'gpt-research', parameters: {} }],
      budget: { max_cost_usd: '12.50' },
    })
  })

  it('sends cancellation with the displayed revision and keeps stale revision remediation visible', async () => {
    const fetcher = emptyWorkspaceFetch()
    fetcher.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'POST' && path.includes('/transition')) return json({ error: { code: 'STALE_REVISION', message: 'Experiment changed', operation_id: 'op-stale', retryable: true, remediation: 'Reload before cancelling.', details: { actual: 8 } } }, 409)
      if (path.endsWith('/v1/status')) return json({ version: '0.1.0', mode: 'local', checks: [], qualifications: [] })
      if (path.endsWith('/v1/campaigns')) return json({ items: [{ id: 'c1', project_id: 'p1', revision: 1, created_at: '2026-09-14T00:00:00Z', title: 'Rigidity', objective: 'Target', programs: ['quantum'] }] })
      if (path.endsWith('/v1/experiments')) return json({ items: [{ id: 'e1', project_id: 'p1', revision: 7, created_at: '2026-09-14T00:00:00Z', campaign_id: 'c1', problem_id: 'p1', models: [], budget: { max_cost_usd: '5.00', max_concurrency: 1, max_runtime_seconds: 60 }, policy: 'direct', mode: 'private', status: 'running', target_digest: 'target' }] })
      if (path.includes('/v1/events')) return json({ items: [] })
      return json({ items: [] })
    })
    vi.stubGlobal('fetch', fetcher)
    vi.stubGlobal('crypto', { randomUUID: () => 'cancel-key' })
    sessionStorage.setItem('physharness.token', 'token')
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /open experiment rigidity/i }))
    await user.click(screen.getByRole('button', { name: /cancel experiment/i }))

    expect(await screen.findByText('STALE_REVISION')).toBeInTheDocument()
    expect(screen.getByText('Reload before cancelling.')).toBeInTheDocument()
    expect(screen.getByText('op-stale')).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining('/v1/experiments/e1/transition'), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'Idempotency-Key': 'cancel-key' }),
      body: JSON.stringify({ action: 'cancel', expected_revision: 7 }),
    }))
  })

  it('shows reviewer authorization failures with server remediation and operation ID', async () => {
    const fetcher = emptyWorkspaceFetch()
    fetcher.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'POST' && path.includes('/reviews')) return json({ error: { code: 'FORBIDDEN', message: 'This identity does not have the required capability.', operation_id: 'op-review', retryable: false, remediation: 'Use an identity assigned the reviewer role.', details: {} } }, 403)
      if (path.endsWith('/v1/status')) return json({ version: '0.1.0', mode: 'local', checks: [], qualifications: [] })
      if (path.endsWith('/v1/campaigns')) return json({ items: [{ id: 'c1', project_id: 'project', revision: 1, created_at: '2026-09-14T00:00:00Z', title: 'Review program', objective: 'Review target meaning', programs: ['classical'] }] })
      if (path.endsWith('/v1/problems')) return json({ items: [{ id: 'p1', project_id: 'project', revision: 1, created_at: '2026-09-14T00:00:00Z', campaign_id: 'c1', title: 'Classical target', program: 'classical', informal_statement: 'Target', formal_statement: 'theorem target', assumptions: [], definitions: {}, source: 'paper', environment_digest: 'a'.repeat(64), target_theorem: 'target', target_digest: 'b'.repeat(64), semantic_review: 'pending' }] })
      if (path.includes('/v1/events')) return json({ items: [] })
      return json({ items: [] })
    })
    vi.stubGlobal('fetch', fetcher)
    sessionStorage.setItem('physharness.token', 'researcher-token')
    const user = userEvent.setup()
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /classical target/i }))
    await user.click(screen.getByRole('button', { name: /review target meaning/i }))
    await user.type(screen.getByLabelText(/rationale/i), 'The source and target align.')
    await user.click(screen.getByRole('button', { name: /record review/i }))

    expect(await screen.findByText('FORBIDDEN')).toBeInTheDocument()
    expect(screen.getByText('Use an identity assigned the reviewer role.')).toBeInTheDocument()
    expect(screen.getByText('op-review')).toBeInTheDocument()
  })
})
