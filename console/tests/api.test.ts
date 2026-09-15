import { ApiFailure, createApiClient } from '../src/api'

describe('API client', () => {
  it('sends bearer authorization and an idempotency key for mutations', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 'campaign-1' }), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    }))
    const api = createApiClient({ baseUrl: 'https://research.test', token: 'secret', fetcher })

    await api.createCampaign({ title: 'Rigidity', objective: 'Prove the target', programs: ['quantum'] }, 'operation-key')

    expect(fetcher).toHaveBeenCalledWith(
      'https://research.test/v1/campaigns',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer secret', 'Idempotency-Key': 'operation-key' }),
        body: JSON.stringify({ title: 'Rigidity', objective: 'Prove the target', programs: ['quantum'] }),
      }),
    )
  })

  it('preserves the structured server failure for visible remediation', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: 'STALE_REVISION',
        message: 'Experiment changed',
        operation_id: 'op-17',
        retryable: true,
        remediation: 'Reload the experiment and retry.',
        details: { expected: 2, actual: 3 },
      },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } }))
    const api = createApiClient({ baseUrl: '', token: 'secret', fetcher })

    await expect(api.transitionExperiment('experiment-1', 'cancel', 2, 'cancel-key')).rejects.toMatchObject({
      name: 'ApiFailure',
      status: 409,
      code: 'STALE_REVISION',
      operationId: 'op-17',
      retryable: true,
      remediation: 'Reload the experiment and retry.',
    } satisfies Partial<ApiFailure>)
  })

  it('reports non-JSON network failures without inventing a server result', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    const api = createApiClient({ baseUrl: '', token: 'secret', fetcher })

    await expect(api.list('campaigns')).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      retryable: true,
      message: 'Failed to fetch',
    })
  })
})

it('follows collection pages instead of silently dropping later records', async () => {
  const response = (body: unknown) => new Response(JSON.stringify(body), {headers:{'Content-Type':'application/json'}})
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response({items:[{id:'a'}],next_cursor:'a'}))
    .mockResolvedValueOnce(response({items:[{id:'b'}],next_cursor:null}))
  const api = createApiClient({baseUrl:'',token:'test',fetcher})
  await expect(api.list('artifacts')).resolves.toEqual([{id:'a'},{id:'b'}])
  expect(fetcher.mock.calls[1][0]).toBe('/v1/artifacts?after=a')
})

it('rejects a repeated server cursor instead of spinning forever', async () => {
  const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify({items:[{id:'a'}],next_cursor:'a'}), {headers:{'Content-Type':'application/json'}}))
  const api = createApiClient({baseUrl:'',token:'test',fetcher})
  await expect(api.list('artifacts')).rejects.toMatchObject({code:'COLLECTION_LIMIT'})
})

it('preserves event page continuation even when no visible events were returned', async () => {
  const page = {items: [], next_cursor: 5000, has_more: true, window: 'forward', scan_limited: true}
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(page), {headers:{'Content-Type':'application/json'}}))
  await expect(createApiClient({baseUrl:'',token:'test',fetcher}).events(5)).resolves.toEqual(page)
})

it('continues through an empty filtered collection page', async () => {
  const response = (body: unknown) => new Response(JSON.stringify(body), {headers:{'Content-Type':'application/json'}})
  const fetcher = vi.fn()
    .mockResolvedValueOnce(response({items:[],next_cursor:'scanned'}))
    .mockResolvedValueOnce(response({items:[{id:'visible'}],next_cursor:null}))
  await expect(createApiClient({baseUrl:'',token:'test',fetcher}).list('claims','?experiment_id=e1')).resolves.toEqual([{id:'visible'}])
  expect(fetcher.mock.calls[1][0]).toBe('/v1/claims?experiment_id=e1&after=scanned')
})
