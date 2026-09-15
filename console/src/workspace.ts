import { ApiFailure, completeReads, loadWorkspace, type ApiClient } from './api'
import type { CoreRecord, WorkspaceData } from './types'

export const ACTIVITY_LIMIT = 1000

const collections = {
  campaign: 'campaigns', problem: 'problems', experiment: 'experiments', branch: 'branches',
  task: 'tasks', claim: 'claims', artifact: 'artifacts', review: 'reviews', session: 'sessions', program: 'programs',
} as const
type Collection = typeof collections[keyof typeof collections]

export function replaceRecord<T extends CoreRecord>(items: T[], record: T): T[] {
  const previous = items.find(item => item.id === record.id)
  if (previous && previous.revision > record.revision) return items
  return previous ? items.map(item => item.id === record.id ? record : item) : [...items, record]
}

/** Read one bounded event page; the caller commits its watermark only with this result. */
export async function refreshWorkspace(api: ApiClient, current: WorkspaceData): Promise<WorkspaceData> {
  if (!current.eventPage) return loadWorkspace(api)
  const page = await api.events(current.eventPage.next_cursor)
  const details = new Map<string, Collection>()
  const claimScopes = new Set<string>()
  let fallback = false
  const add = (collection: Collection, id: unknown) => {
    if (typeof id === 'string' && id) details.set(`${collection}/${encodeURIComponent(id)}`, collection)
  }
  for (const event of page.items) {
    const kind = event.kind.split('.')[0]
    if (Object.hasOwn(collections, kind)) add(collections[kind as keyof typeof collections], event.aggregate_id)
    else if (kind === 'verification') {
      if (typeof event.payload.experiment_id === 'string') claimScopes.add(event.payload.experiment_id)
      else fallback = true
    } else if (event.kind === 'context.checkpointed') add('artifacts', event.aggregate_id)
    else if (!['resources', 'workspace', 'message', 'source'].includes(kind)) fallback = true
    if (event.kind === 'problem.reviewed') add('reviews', event.payload.review_id)
    if (event.kind === 'branch.checkpointed') add('artifacts', event.payload.checkpoint_id)
  }

  // Unknown event types may affect several collections. Preserve correctness with an explicit
  // full snapshot fallback; ordinary events fetch only the changed record or experiment scope.
  if (fallback) {
    const snapshot = await loadWorkspace(api)
    return {...snapshot, events: mergeEvents(current.events, page.items), eventPage: page}
  }
  const [records, scopedClaims, status] = await completeReads([
    completeReads([...details].map(async ([path, collection]) => {
      const record = await api.request<CoreRecord>(`/v1/${path}`)
      if (!record.id || !Number.isInteger(record.revision)) throw new ApiFailure({code:'INVALID_SERVER_RESPONSE',message:'Canonical detail response has no record identity or revision.'})
      return {collection, record}
    })),
    completeReads([...claimScopes].map(async id => ({id, items: await api.list<WorkspaceData['claims'][number]>('claims', `?experiment_id=${encodeURIComponent(id)}`)}))),
    api.status(),
  ])
  const next = {...current, status, events: mergeEvents(current.events, page.items), eventPage: page}
  for (const {collection, record} of records) {
    // The collection discriminator came from the canonical event's resource kind.
    Object.assign(next, {[collection]: replaceRecord(next[collection], record)})
  }
  for (const {id, items} of scopedClaims) next.claims = [...next.claims.filter(item => item.experiment_id !== id), ...items]
  return next
}

function mergeEvents(previous: WorkspaceData['events'], incoming: WorkspaceData['events']) {
  if (!incoming.length) return previous
  return [...new Map([...previous, ...incoming].map(event => [event.sequence, event])).values()]
    .sort((a, b) => a.sequence - b.sequence).slice(-ACTIVITY_LIMIT)
}
