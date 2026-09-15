import type {
  Campaign, EventPage, Experiment, Ledger, Problem, ServiceStatus, WorkspaceData,
} from './types'

export interface ApiErrorBody {
  code: string
  message: string
  operation_id?: string
  retryable?: boolean
  remediation?: string
  details?: unknown
}

export class ApiFailure extends Error {
  readonly status: number
  readonly code: string
  readonly operationId?: string
  readonly retryable: boolean
  readonly remediation?: string
  readonly details?: unknown

  constructor(error: ApiErrorBody, status = 0) {
    super(error.message)
    this.name = 'ApiFailure'
    this.status = status
    this.code = error.code
    this.operationId = error.operation_id
    this.retryable = Boolean(error.retryable)
    this.remediation = error.remediation
    this.details = error.details
  }
}

interface ClientOptions {
  baseUrl: string
  token: string
  fetcher?: typeof fetch
}

export interface CampaignInput {
  title: string
  objective: string
  programs: Array<'quantum' | 'classical'>
}

export interface ProblemInput {
  campaign_id: string
  title: string
  program: 'quantum' | 'classical'
  informal_statement: string
  formal_statement: string
  assumptions: string[]
  definitions: Record<string, string>
  source: string
  environment_digest: string
  target_theorem: string
}

export interface ExperimentInput {
  campaign_id: string
  problem_id: string
  models: Array<{ runtime: string; model: string; parameters: Record<string, unknown> }>
  budget: { max_cost_usd: string; max_concurrency: number; max_runtime_seconds: number }
  policy: string
  mode: string
}

const trimBase = (value: string) => value.replace(/\/+$/, '')

export function createApiClient({ baseUrl, token, fetcher = fetch }: ClientOptions) {
  const base = trimBase(baseUrl)

  async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    new Headers(init.headers).forEach((value, key) => {
      headers[key.toLowerCase() === 'idempotency-key' ? 'Idempotency-Key' : key] = value
    })
    if (init.body) headers['Content-Type'] = 'application/json'
    if (authenticated) headers.Authorization = `Bearer ${token}`

    let response: Response
    try {
      response = await fetcher(`${base}${path}`, { ...init, headers })
    } catch (error) {
      const message = error instanceof Error ? error.message : 'The service could not be reached.'
      throw new ApiFailure({ code: 'NETWORK_ERROR', message, retryable: true, remediation: 'Check the API URL and network, then retry.' })
    }

    const contentType = response.headers.get('content-type') ?? ''
    const body: unknown = contentType.includes('application/json') ? await response.json() : await response.text()
    if (!response.ok) {
      const candidate = typeof body === 'object' && body !== null && 'error' in body
        ? (body as { error: ApiErrorBody }).error
        : { code: `HTTP_${response.status}`, message: typeof body === 'string' && body ? body : response.statusText, retryable: response.status >= 500 }
      throw new ApiFailure(candidate, response.status)
    }
    return body as T
  }

  const mutate = <T>(path: string, payload: unknown, idempotencyKey: string) => request<T>(path, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(payload),
  })

  return {
    request,
    list: async <T>(resource: string, query = ''): Promise<T[]> => {
      const items: T[] = []
      const cursors = new Set<string>()
      let cursor: string | undefined
      do {
        const separator = query.includes('?') ? '&' : '?'
        const suffix = cursor ? `${separator}after=${encodeURIComponent(cursor)}` : ''
        const result: { items: T[]; next_cursor?: string | null } = await request(`/v1/${resource}${query}${suffix}`)
        if (!Array.isArray(result.items)) throw new ApiFailure({code:'INVALID_SERVER_RESPONSE', message:'Collection response has no items array.'})
        items.push(...result.items)
        cursor = result.next_cursor ?? undefined
        if (cursor && (cursors.has(cursor) || cursors.size >= 10000 || items.length > 50000)) {
          throw new ApiFailure({code:'COLLECTION_LIMIT', message:'Collection pagination cannot safely continue.', remediation:'Use a scoped query or inspect the API pagination diagnostics.'})
        }
        if (cursor) cursors.add(cursor)
      } while (cursor)
      return items
    },
    status: () => request<ServiceStatus>('/v1/status'),
    events: async (after?: number): Promise<EventPage> => {
      const page = await request<EventPage>(`/v1/events?${after !== undefined ? `after=${after}&` : 'tail=true&'}limit=100`)
      if (!Array.isArray(page.items) || !Number.isSafeInteger(page.next_cursor) || page.next_cursor < (after ?? 0)
        || typeof page.has_more !== 'boolean' || typeof page.scan_limited !== 'boolean'
        || page.window !== (after === undefined ? 'latest' : 'forward')
        || (after !== undefined && page.has_more && page.next_cursor === after)) {
        throw new ApiFailure({code: 'INVALID_EVENT_PAGE', message: 'The server returned an invalid event continuation.', remediation: 'Inspect the API event pagination diagnostics and retry the read.'})
      }
      return page
    },
    createCampaign: (input: CampaignInput, key: string) => mutate<Campaign>('/v1/campaigns', input, key),
    createProblem: (input: ProblemInput, key: string) => mutate<Problem>('/v1/problems', input, key),
    createExperiment: (input: ExperimentInput, key: string) => mutate<Experiment>('/v1/experiments', input, key),
    transitionExperiment: (id: string, action: 'start' | 'pause' | 'resume' | 'cancel', revision: number, key: string) =>
      mutate<Experiment>(`/v1/experiments/${id}/transition`, { action, expected_revision: revision }, key),
    reviewProblem: (id: string, decision: 'approved' | 'rejected', rationale: string, key: string) =>
      mutate(`/v1/problems/${id}/reviews`, { decision, rationale }, key),
    ledger: (id: string) => request<Ledger>(`/v1/experiments/${id}/ledger`),
    exportExperiment: (id: string) => request<unknown>(`/v1/experiments/${id}/export`),
    artifactContent: (id: string) => request<{ content: string }>(`/v1/artifacts/${id}/content`),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>

export async function loadWorkspace(api: ApiClient): Promise<WorkspaceData> {
  // Capture the watermark first: writes during collection loading are replayed next poll.
  const eventPage = await api.events()
  const [campaigns, problems, experiments, branches, tasks, claims, artifacts, reviews, sessions, programs, status] = await completeReads([
    api.list<WorkspaceData['campaigns'][number]>('campaigns'),
    api.list<WorkspaceData['problems'][number]>('problems'),
    api.list<WorkspaceData['experiments'][number]>('experiments'),
    api.list<WorkspaceData['branches'][number]>('branches'),
    api.list<WorkspaceData['tasks'][number]>('tasks'),
    api.list<WorkspaceData['claims'][number]>('claims'),
    api.list<WorkspaceData['artifacts'][number]>('artifacts'),
    api.list<WorkspaceData['reviews'][number]>('reviews'),
    api.list<WorkspaceData['sessions'][number]>('sessions'),
    api.list<WorkspaceData['programs'][number]>('programs'),
    api.status(),
  ])
  return { campaigns, problems, experiments, branches, tasks, claims, artifacts, reviews, sessions, programs, events: eventPage.items, eventPage, status }
}

/** Keep a read cycle in flight until every sibling request has settled, including failures. */
export async function completeReads<const Reads extends readonly Promise<unknown>[]>(reads: Reads): Promise<{ -readonly [K in keyof Reads]: Awaited<Reads[K]> }> {
  const results = await Promise.allSettled(reads)
  return results.map(result => {
    if (result.status === 'rejected') throw result.reason
    return result.value
  }) as { -readonly [K in keyof Reads]: Awaited<Reads[K]> }
}
