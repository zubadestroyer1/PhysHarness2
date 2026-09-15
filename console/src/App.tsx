import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiFailure, completeReads, createApiClient, type CampaignInput, type ExperimentInput, type ProblemInput } from './api'
import { actionsFor } from './transitions'
import { ACTIVITY_LIMIT, refreshWorkspace, replaceRecord } from './workspace'
import { CampaignForm, ExperimentForm, ProblemForm, ReviewForm } from './forms'
import { EmptyState, ErrorBanner, EvidencePanel, Modal, StatusPill, StatusStrip, type Selection } from './components'
import { emptyWorkspace, type Campaign, type Experiment, type Ledger, type Problem, type WorkspaceData } from './types'

type Section = 'overview' | 'campaigns' | 'problems' | 'experiments' | 'claims' | 'activity'
type Dialog = 'campaign' | 'problem' | 'experiment' | 'review' | 'export' | null
const sections: Array<{ id: Section; label: string }> = [
  { id: 'overview', label: 'Overview' }, { id: 'campaigns', label: 'Campaigns' },
  { id: 'problems', label: 'Problems' }, { id: 'experiments', label: 'Experiments' },
  { id: 'claims', label: 'Claims & branches' }, { id: 'activity', label: 'Activity' },
]
const tokenKey = 'physharness.token'
const apiUrlKey = 'physharness.apiUrl'

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem(tokenKey) ?? '')
  const [apiUrl, setApiUrl] = useState(() => sessionStorage.getItem(apiUrlKey) ?? import.meta.env.VITE_API_URL ?? '')
  const [data, setData] = useState<WorkspaceData>(emptyWorkspace)
  const [loading, setLoading] = useState(Boolean(token))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [pollError, setPollError] = useState<ApiFailure | null>(null)
  const [section, setSection] = useState<Section>(() => sectionFromLocation())
  const [campaignId, setCampaignId] = useState<string | null>(null)
  const [selectedRecord, storeSelection] = useState<Selection>(null)
  const [dialog, setDialog] = useState<Dialog>(null)
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [ledgerError, setLedgerError] = useState<ApiFailure | null>(null)
  const [exportData, setExportData] = useState<unknown>(null)
  const [displayMode, setDisplayMode] = useState<'table' | 'graph'>('table')

  const sessionVersion = useRef(0)
  const selectionVersion = useRef(0)
  const requestVersion = useRef(0)
  const ledgerVersion = useRef(0)
  const selectionRef = useRef<Selection>(null)
  const dataRef = useRef(data)
  const refreshRef = useRef<(followup?: boolean) => Promise<void>>(async () => {})
  const selection = canonicalSelection(selectedRecord, data)
  const api = useMemo(() => createApiClient({ baseUrl: apiUrl, token }), [apiUrl, token])

  const closeDialog = () => {
    requestVersion.current++
    setDialog(null); setBusy(false); setExportData(null)
  }
  const setSelection = (next: Selection) => {
    selectionVersion.current++
    selectionRef.current = next
    storeSelection(next)
    setLedger(null); setLedgerError(null)
    closeDialog()
  }
  const refreshLedger = useCallback(async () => {
    const selected = selectionRef.current
    if (!token || selected?.kind !== 'experiment') return
    const session = sessionVersion.current, view = selectionVersion.current, request = ++ledgerVersion.current
    const current = () => session === sessionVersion.current && view === selectionVersion.current && request === ledgerVersion.current
    try {
      const value = await api.ledger(selected.item.id)
      if (current()) { setLedger(value); setLedgerError(null) }
    } catch (caught) {
      if (current()) { setLedger(null); setLedgerError(asApiFailure(caught)) }
    }
  }, [api, token])
  useEffect(() => { void refreshLedger() }, [refreshLedger, selectedRecord])

  useEffect(() => {
    if (!token) return
    const session = sessionVersion.current
    let mounted = true
    let inFlight: Promise<void> | null = null
    const current = () => mounted && session === sessionVersion.current
    const run = async (followup = false): Promise<void> => {
      while (inFlight) {
        await inFlight
        if (!followup) return
      }
      if (!current()) return
      const cycle = async () => {
        try {
          const [snapshot] = await completeReads([refreshWorkspace(api, dataRef.current), refreshLedger()])
          if (!current()) return
          // A transition may have completed while this read was pending. Never replace a
          // newer canonical revision with an older response from that read.
          const next = mergeCanonical(snapshot, dataRef.current)
          dataRef.current = next
          setData(next)
          setCampaignId(id => id && next.campaigns.some(item => item.id === id) ? id : next.campaigns[0]?.id ?? null)
          setPollError(null)
        } catch (caught) {
          if (current()) setPollError(asApiFailure(caught))
        } finally {
          if (current()) setLoading(false)
        }
      }
      inFlight = cycle()
      try { await inFlight } finally { inFlight = null }
    }
    refreshRef.current = run
    void run()
    const timer = window.setInterval(() => { void run() }, 5_000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [api, token, refreshLedger])
  useEffect(() => () => { sessionVersion.current++ }, [])
  const refresh = useCallback(() => refreshRef.current(), [])

  const connect = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const supplied = String(form.get('token')).trim()
    const suppliedUrl = String(form.get('apiUrl')).trim()
    sessionVersion.current++
    sessionStorage.setItem(tokenKey, supplied)
    sessionStorage.setItem(apiUrlKey, suppliedUrl)
    setApiUrl(suppliedUrl); setToken(supplied); setLoading(true)
  }
  const disconnect = () => {
    sessionVersion.current++
    sessionStorage.removeItem(tokenKey)
    sessionStorage.removeItem(apiUrlKey)
    dataRef.current = emptyWorkspace
    setToken(''); setData(emptyWorkspace); setSelection(null); setError(null); setPollError(null)
  }
  const move = (next: Section) => {
    setSection(next)
    window.history.replaceState(null, '', `#${next}`)
  }
  const mutate = async (operation: () => Promise<unknown>, onSuccess?: (value: unknown) => void) => {
    const session = sessionVersion.current, view = selectionVersion.current, request = ++requestVersion.current
    const current = () => session === sessionVersion.current && view === selectionVersion.current && request === requestVersion.current
    setBusy(true); setError(null)
    try {
      const result = await operation()
      if (!current()) return
      onSuccess?.(result)
      setDialog(null)
      await refreshRef.current(true)
    } catch (caught) { if (current()) setError(asApiFailure(caught)) }
    finally { if (current()) setBusy(false) }
  }
  const createCampaign = (input: CampaignInput) => mutate(() => api.createCampaign(input, crypto.randomUUID()))
  const createProblem = (input: ProblemInput) => mutate(() => api.createProblem(input, crypto.randomUUID()))
  const createExperiment = (input: ExperimentInput) => mutate(() => api.createExperiment(input, crypto.randomUUID()))
  const transition = (experiment: Experiment, action: 'start' | 'pause' | 'resume' | 'cancel') => mutate(
    () => api.transitionExperiment(experiment.id, action, experiment.revision, crypto.randomUUID()),
    result => {
      const next = {...dataRef.current, experiments: replaceRecord(dataRef.current.experiments, result as Experiment)}
      dataRef.current = next; setData(next)
    },
  )
  const review = (problem: Problem, decision: 'approved' | 'rejected', rationale: string) => mutate(() => api.reviewProblem(problem.id, decision, rationale, crypto.randomUUID()))
  const exportExperiment = async (experiment: Experiment) => {
    const session = sessionVersion.current, view = selectionVersion.current, request = ++requestVersion.current
    const current = () => session === sessionVersion.current && view === selectionVersion.current && request === requestVersion.current
    setBusy(true); setError(null); setExportData(null); setDialog('export')
    try { const result = await api.exportExperiment(experiment.id); if (current()) setExportData(result) }
    catch (caught) { if (current()) setError(asApiFailure(caught)) }
    finally { if (current()) setBusy(false) }
  }
  const selectArtifact = async (artifact: WorkspaceData['artifacts'][number]) => {
    setSelection({ kind: 'artifact', item: artifact })
    const session = sessionVersion.current, view = selectionVersion.current
    const current = () => session === sessionVersion.current && view === selectionVersion.current
    try {
      const result = await api.artifactContent(artifact.id)
      if (current()) storeSelection({ kind: 'artifact', item: { ...artifact, content: result.content } })
    } catch (caught) { if (current()) setError(asApiFailure(caught)) }
  }

  if (!token) return <ConnectionScreen apiUrl={apiUrl} connect={connect} />

  const campaign = data.campaigns.find(item => item.id === campaignId) ?? null
  const scopedProblems = campaign ? data.problems.filter(item => item.campaign_id === campaign.id) : data.problems
  const scopedExperiments = campaign ? data.experiments.filter(item => item.campaign_id === campaign.id) : data.experiments
  const experimentIds = new Set(scopedExperiments.map(item => item.id))
  const scopedArtifacts = data.artifacts.filter(item => !item.experiment_id || experimentIds.has(item.experiment_id))
  const scopedClaims = data.claims.filter(item => experimentIds.has(item.experiment_id))
  const scopedBranches = data.branches.filter(item => experimentIds.has(item.experiment_id))

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">PH</span><div><strong>PhysHarness</strong><small>private research console</small></div></div>
      <div className="topbar-actions"><span className="connection-label"><span className={data.status ? 'live-dot' : 'state-dot'} />{data.status ? 'Connected' : 'Connection unconfirmed'}</span><button className="button button--quiet" onClick={disconnect}>Disconnect</button></div>
    </header>
    <StatusStrip status={data.status} />
    {pollError && <div className="error-wrap"><ErrorBanner error={pollError} title="Refresh failed — displayed records may be stale" onRetry={refresh} /></div>}
    {error && !dialog && <div className="error-wrap"><ErrorBanner error={error} /></div>}
    <div className="workstation">
      <aside className="sidebar">
        <nav aria-label="Primary navigation">{sections.map(item => <button key={item.id} className={section === item.id ? 'active' : ''} aria-current={section === item.id ? 'page' : undefined} onClick={() => move(item.id)}>{item.label}</button>)}</nav>
        <div className="campaign-list"><div className="sidebar-heading"><p className="eyebrow">Research programs</p><button className="mini-button" onClick={() => setDialog('campaign')}>New</button></div>
          {data.campaigns.map(item => <button key={item.id} className={`campaign-button ${campaignId === item.id ? 'active' : ''}`} onClick={() => setCampaignId(item.id)}><span>{item.title}</span><small>{item.programs.join(' · ')}</small></button>)}
          {!data.campaigns.length && <p className="muted compact">No campaigns connected.</p>}
        </div>
        <div className="sidebar-foot"><span>Refresh interval</span><strong>5 seconds</strong><small>{data.eventPage?.window === 'forward' && data.eventPage.has_more ? 'Catching up; displayed records may be behind.' : 'Polling failures remain visible.'}</small></div>
      </aside>
      <main className="main-content">
        {loading && !data.status ? <LoadingState /> : <>
          {section === 'overview' && <Overview data={data} campaign={campaign} problems={scopedProblems} experiments={scopedExperiments} onCreateCampaign={() => setDialog('campaign')} onCreateExperiment={() => setDialog('experiment')} onSelectProblem={item => setSelection({ kind: 'problem', item })} onSelectExperiment={item => setSelection({ kind: 'experiment', item })} />}
          {section === 'campaigns' && <Campaigns campaigns={data.campaigns} onCreate={() => setDialog('campaign')} onSelect={setCampaignId} />}
          {section === 'problems' && <Problems problems={scopedProblems} onCreate={() => setDialog('problem')} onSelect={item => setSelection({ kind: 'problem', item })} />}
          {section === 'experiments' && <Experiments experiments={scopedExperiments} campaigns={data.campaigns} onCreate={() => setDialog('experiment')} onSelect={item => setSelection({ kind: 'experiment', item })} onTransition={transition} busy={busy} />}
          {section === 'claims' && <ClaimsAndBranches claims={scopedClaims} branches={scopedBranches} mode={displayMode} setMode={setDisplayMode} onClaim={item => setSelection({ kind: 'claim', item })} onBranch={item => setSelection({ kind: 'branch', item })} artifacts={scopedArtifacts} onArtifact={selectArtifact} />}
          {section === 'activity' && <Activity events={data.events} pending={Boolean(data.eventPage?.window === 'forward' && data.eventPage.has_more)} />}
        </>}
      </main>
      <EvidencePanel selection={selection} ledger={ledger} ledgerError={ledgerError} reviews={data.reviews} onReview={problem => { setSelection({ kind: 'problem', item: problem }); setDialog('review') }} onExport={exportExperiment} onTransition={transition} busy={busy} />
    </div>
    {dialog === 'campaign' && <Modal title="New campaign" description="Create a private research objective and select its scientific programs." onClose={closeDialog}>{error && <ErrorBanner error={error} />}<CampaignForm submit={createCampaign} busy={busy} /></Modal>}
    {dialog === 'problem' && <Modal title="Propose problem" description="Store the exact target, assumptions, source, and trusted environment identity." onClose={closeDialog}>{error && <ErrorBanner error={error} />}<ProblemForm campaigns={data.campaigns} submit={createProblem} busy={busy} /></Modal>}
    {dialog === 'experiment' && <Modal title="New experiment" description="Set exact model and runtime identities inside an explicit resource envelope." onClose={closeDialog}>{error && <ErrorBanner error={error} />}<ExperimentForm campaigns={data.campaigns} problems={data.problems} submit={createExperiment} busy={busy} /></Modal>}
    {dialog === 'review' && selection?.kind === 'problem' && <Modal title="Review target meaning" description="Record an expert semantic decision with rationale. Reviewer authorization is enforced by the API." onClose={closeDialog}>{error && <ErrorBanner error={error} />}<ReviewForm submit={(decision, rationale) => review(selection.item, decision, rationale)} busy={busy} /></Modal>}
    {dialog === 'export' && <Modal title="Experiment export" description="Canonical reproducibility manifest returned by the service, including missing qualification." onClose={closeDialog}>{error && <ErrorBanner error={error} />}{busy ? <p>Loading export…</p> : exportData ? <pre className="export-block">{JSON.stringify(exportData, null, 2)}</pre> : !error && <p className="muted">No export was returned.</p>}</Modal>}
  </div>
}

function ConnectionScreen({ apiUrl, connect }: { apiUrl: string; connect: (event: FormEvent<HTMLFormElement>) => void }) {
  return <main className="connection-screen"><section className="connection-card"><div className="brand brand--large"><span className="brand-mark">PH</span><div><strong>PhysHarness</strong><small>scientific research workstation</small></div></div><p className="eyebrow">Authenticated private workspace</p><h1>Connect to the research service</h1><p>Use a bearer token supplied by your operator. It is kept only in this browser session and is sent to authenticated <code>/v1</code> routes.</p><form className="form" onSubmit={connect}><label>API URL<input name="apiUrl" defaultValue={apiUrl} placeholder="Relative to this host" /></label><label>Bearer token<input name="token" type="password" autoComplete="off" required autoFocus /></label><button className="button button--primary">Connect</button></form><div className="integrity-note"><strong>Evidence stays explicit.</strong><span>Process health, semantic review, proof status, numerical evidence, assumptions, and novelty are displayed independently.</span></div></section></main>
}

function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <header className="page-header"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>{action}</header>
}

function Overview({ data, campaign, problems, experiments, onCreateCampaign, onCreateExperiment, onSelectProblem, onSelectExperiment }: { data: WorkspaceData; campaign: Campaign | null; problems: Problem[]; experiments: Experiment[]; onCreateCampaign: () => void; onCreateExperiment: () => void; onSelectProblem: (item: Problem) => void; onSelectExperiment: (item: Experiment) => void }) {
  if (!data.campaigns.length) return <><PageHeader eyebrow="Workspace overview" title="Research control plane" description={data.status ? 'The authenticated workspace is available. Start by defining a campaign and its exact scientific objective.' : 'No canonical workspace state has been loaded from the service.'} /><EmptyState title={data.status ? 'No campaigns yet' : 'Campaign data unavailable'} body={data.status ? 'Create a campaign before proposing reviewed targets or allocating experiments.' : 'Resolve the visible connection error and retry before creating records.'} action={data.status ? <button className="button button--primary" onClick={onCreateCampaign}>Create campaign</button> : undefined} /></>
  return <><PageHeader eyebrow="Workspace overview" title={campaign?.title ?? 'All campaigns'} description={campaign?.objective ?? 'Canonical research records returned by the service.'} action={problems.length ? <button className="button button--primary" onClick={onCreateExperiment}>New experiment</button> : undefined} /><div className="metric-grid"><Metric label="Problems" value={problems.length} detail={`${problems.filter(item => item.semantic_review === 'approved').length} semantically approved`} /><Metric label="Experiments" value={experiments.length} detail={`${experiments.filter(item => item.status === 'running').length} running`} /><Metric label="Recorded sessions" value={data.sessions.length} detail="project-wide total" /><Metric label="Claims" value={data.claims.filter(item => experiments.some(exp => exp.id === item.experiment_id)).length} detail="not equivalent to proofs" /></div><section className="split-section"><div className="content-card"><CardTitle title="Target queue" subtitle="Semantic review is shown independently." />{problems.length ? <div className="record-list">{problems.slice(0, 5).map(item => <button key={item.id} onClick={() => onSelectProblem(item)}><span><strong>{item.title}</strong><small>{item.program}</small></span><StatusPill value={item.semantic_review} /></button>)}</div> : <EmptyState title="No problems" body="Propose a target with assumptions, source, and environment digest." />}</div><div className="content-card"><CardTitle title="Execution" subtitle="A completed model run does not establish proof." />{experiments.length ? <div className="record-list">{experiments.slice(0, 5).map(item => <button key={item.id} aria-label={`Open experiment ${campaign?.title ?? item.id}`} onClick={() => onSelectExperiment(item)}><span><strong>{item.id.slice(0, 8)}</strong><small>${item.budget.max_cost_usd} envelope</small></span><StatusPill value={item.status} /></button>)}</div> : <EmptyState title="No experiments" body="Create an experiment after storing a problem target." />}</div></section></>
}

function Campaigns({ campaigns, onCreate, onSelect }: { campaigns: Campaign[]; onCreate: () => void; onSelect: (id: string) => void }) {
  return <><PageHeader eyebrow="Research portfolio" title="Campaigns" description="Objectives and program scope returned by the canonical campaign records." action={<button className="button button--primary" onClick={onCreate}>New campaign</button>} />{campaigns.length ? <div className="card-grid">{campaigns.map(item => <button className="campaign-card" key={item.id} onClick={() => onSelect(item.id)}><span className="program-kicker">{item.programs.join(' + ')}</span><h3>{item.title}</h3><p>{item.objective}</p><small>revision {item.revision}</small></button>)}</div> : <EmptyState title="No campaigns" body="Create the first research campaign to establish a scientific objective." />}</>
}

function Problems({ problems, onCreate, onSelect }: { problems: Problem[]; onCreate: () => void; onSelect: (item: Problem) => void }) {
  return <><PageHeader eyebrow="Canonical targets" title="Problems" description="Every target preserves exact assumptions, source, environment, and semantic review." action={<button className="button button--primary" onClick={onCreate}>Propose problem</button>} />{problems.length ? <div className="data-table" role="table" aria-label="Problems"><div className="table-row table-head" role="row"><span>Target</span><span>Program</span><span>Semantic</span><span>Revision</span></div>{problems.map(item => <button className="table-row" role="row" key={item.id} onClick={() => onSelect(item)}><span><strong>{item.title}</strong><small>{item.target_theorem}</small></span><span>{item.program}</span><span><StatusPill value={item.semantic_review} /></span><span>{item.revision}</span></button>)}</div> : <EmptyState title="No problems in this campaign" body="Propose a target with a formal statement and reviewable provenance." action={<button className="button button--secondary" onClick={onCreate}>Propose problem</button>} />}</>
}

function Experiments({ experiments, campaigns, onCreate, onSelect, onTransition, busy }: { experiments: Experiment[]; campaigns: Campaign[]; onCreate: () => void; onSelect: (item: Experiment) => void; onTransition: (item: Experiment, action: 'start' | 'pause' | 'resume' | 'cancel') => void; busy: boolean }) {
  return <><PageHeader eyebrow="Governed execution" title="Experiments" description="Exact runtime/model identity, optimistic revision, and server ledger remain visible." action={<button className="button button--primary" onClick={onCreate}>New experiment</button>} />{experiments.length ? <div className="experiment-stack">{experiments.map(item => { const campaign = campaigns.find(c => c.id === item.campaign_id); return <article className="experiment-card" key={item.id}><button className="experiment-main" aria-label={`Open experiment ${campaign?.title ?? item.id}`} onClick={() => onSelect(item)}><div><span className="program-kicker">{campaign?.title ?? 'Campaign unavailable'}</span><h3>{item.id.slice(0, 12)}</h3><p>{item.models.map(model => `${model.runtime} / ${model.model}`).join(', ') || 'No model configuration returned'}</p></div><div className="experiment-state"><StatusPill value={item.status} /><small>revision {item.revision}</small></div></button><div className="experiment-meta"><span>Budget <strong>${item.budget.max_cost_usd}</strong></span><span>Concurrency <strong>{item.budget.max_concurrency}</strong></span><span>Runtime <strong>{item.budget.max_runtime_seconds}s</strong></span><span>Policy <strong>{item.policy}</strong></span></div><div className="transition-row">{actionsFor(item.status).map(action => <button key={action} className={action === 'cancel' ? 'button button--danger' : 'button button--secondary'} disabled={busy} aria-label={`${action} experiment`} onClick={() => onTransition(item, action)}>{capitalize(action)}</button>)}</div></article> })}</div> : <EmptyState title="No experiments in this campaign" body="Define a problem first, then allocate an exact model and resource envelope." action={<button className="button button--secondary" onClick={onCreate}>New experiment</button>} />}</>
}

function ClaimsAndBranches({ claims, branches, artifacts, mode, setMode, onClaim, onBranch, onArtifact }: { claims: WorkspaceData['claims']; branches: WorkspaceData['branches']; artifacts: WorkspaceData['artifacts']; mode: 'table' | 'graph'; setMode: (mode: 'table' | 'graph') => void; onClaim: (item: WorkspaceData['claims'][number]) => void; onBranch: (item: WorkspaceData['branches'][number]) => void; onArtifact: (item: WorkspaceData['artifacts'][number]) => void }) {
  return <><PageHeader eyebrow="Research record" title="Claims & branches" description="Explore the real branch structure and evidence records returned by the service." action={<div className="segmented"><button className={mode === 'table' ? 'active' : ''} onClick={() => setMode('table')}>Table</button><button className={mode === 'graph' ? 'active' : ''} onClick={() => setMode('graph')}>Graph</button></div>} />{!claims.length && !branches.length ? <EmptyState title="No claims or branches" body="Records will appear here when experiments create canonical branches and submit claims." /> : mode === 'table' ? <div className="evidence-columns"><section className="content-card"><CardTitle title="Claims" subtitle="Evidence categories are server supplied." /><div className="record-list">{claims.map(item => <button key={item.id} onClick={() => onClaim(item)}><span><strong>{item.statement}</strong><small>{item.assumptions.length} assumptions</small></span><StatusPill value={item.evidence} /></button>)}</div></section><section className="content-card"><CardTitle title="Branches" subtitle="Relations describe collaboration, not proof." /><div className="record-list">{branches.map(item => <button key={item.id} onClick={() => onBranch(item)}><span><strong>{item.title}</strong><small>{item.objective}</small></span><StatusPill value={item.relation} /></button>)}</div></section></div> : <BranchGraph branches={branches} onSelect={onBranch} />}<section className="content-card artifact-section"><CardTitle title="Artifacts & logs" subtitle="Collection metadata and content come directly from the service." />{artifacts.length ? <div className="artifact-list">{artifacts.map(item => <button key={item.id} onClick={() => onArtifact(item)}><span>{item.artifact_kind}</span><small>{item.media_type}</small><code>{item.sha256}</code></button>)}</div> : <p className="muted">No artifact records returned for this workspace.</p>}</section></>
}

function BranchGraph({ branches, onSelect }: { branches: WorkspaceData['branches']; onSelect: (item: WorkspaceData['branches'][number]) => void }) {
  const roots = branches.filter(branch => !branch.parent_id || !branches.some(candidate => candidate.id === branch.parent_id))
  const draw = (branch: WorkspaceData['branches'][number]): React.ReactNode => <li key={branch.id}><button onClick={() => onSelect(branch)}><strong>{branch.title}</strong><span>{branch.relation}</span></button>{branches.some(child => child.parent_id === branch.id) && <ul>{branches.filter(child => child.parent_id === branch.id).map(draw)}</ul>}</li>
  return <div className="branch-graph"><ul>{roots.map(draw)}</ul></div>
}

function Activity({ events, pending }: { events: WorkspaceData['events']; pending: boolean }) {
  const newestFirst = useMemo(() => [...events].reverse(), [events])
  return <><PageHeader eyebrow="Append-only log" title="Activity" description={`Activity starts with up to 100 recent visible events and keeps the ${ACTIVITY_LIMIT.toLocaleString('en-US')} newest observed events. Earlier history is omitted from this display.`} /><p className="muted">{pending ? 'Catching up with additional event pages; displayed records may be behind.' : 'Events include correlated operation IDs and stored payloads.'}</p>{events.length ? <ol className="timeline">{newestFirst.map(item => <li key={item.sequence}><span className="timeline-marker" /><div><header><strong>{item.kind}</strong><time>{formatDate(item.created_at)}</time></header><p>Aggregate <code>{item.aggregate_id}</code></p><details><summary>Event #{item.sequence} · operation {item.operation_id}</summary><pre>{JSON.stringify(item.payload, null, 2)}</pre></details></div></li>)}</ol> : <EmptyState title="No activity events" body="The server returned an empty event collection. New canonical operations will appear here." />}</>
}

function Metric({ label, value, detail }: { label: string; value: number; detail: string }) { return <article className="metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article> }
function CardTitle({ title, subtitle }: { title: string; subtitle: string }) { return <header className="card-title"><h2>{title}</h2><p>{subtitle}</p></header> }
function LoadingState() { return <div className="loading-state"><span /><p>Loading canonical research records…</p></div> }
function asApiFailure(value: unknown) { return value instanceof ApiFailure ? value : new ApiFailure({ code: 'CLIENT_ERROR', message: value instanceof Error ? value.message : 'Unexpected client error', retryable: false, remediation: 'Check the submitted values and retry.' }) }
function capitalize(value: string) { return value.charAt(0).toUpperCase() + value.slice(1) }
function formatDate(value: string) { const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString() }
function sectionFromLocation(): Section { const value = window.location.hash.slice(1) as Section; return sections.some(section => section.id === value) ? value : 'overview' }

function canonicalSelection(selected: Selection, data: WorkspaceData): Selection {
  if (!selected) return null
  switch (selected.kind) {
    case 'problem': { const item = data.problems.find(item => item.id === selected.item.id); return item ? {kind: 'problem', item} : null }
    case 'experiment': { const item = data.experiments.find(item => item.id === selected.item.id); return item ? {kind: 'experiment', item} : null }
    case 'claim': { const item = data.claims.find(item => item.id === selected.item.id); return item ? {kind: 'claim', item} : null }
    case 'branch': { const item = data.branches.find(item => item.id === selected.item.id); return item ? {kind: 'branch', item} : null }
    case 'artifact': {
      const item = data.artifacts.find(item => item.id === selected.item.id)
      return item ? {kind: 'artifact', item: {...item, content: selected.item.content}} : null
    }
  }
}

function mergeCanonical(snapshot: WorkspaceData, current: WorkspaceData): WorkspaceData {
  const next = {...snapshot}
  const collections = ['campaigns', 'problems', 'experiments', 'branches', 'tasks', 'claims', 'artifacts', 'reviews', 'sessions', 'programs'] as const
  for (const collection of collections) {
    if (snapshot[collection] === current[collection]) continue
    const loaded = new Map(snapshot[collection].map(record => [record.id, record]))
    const newer = current[collection].filter(item => item.revision > (loaded.get(item.id)?.revision ?? item.revision))
    for (const record of newer) Object.assign(next, {[collection]: replaceRecord(next[collection], record)})
  }
  return next
}
