import type { ReactNode } from 'react'
import { actionsFor } from './transitions'
import type { ApiFailure } from './api'
import type { Artifact, Branch, Claim, Experiment, Ledger, Problem, Review, ServiceStatus } from './types'

export function StatusPill({ value }: { value?: string | null }) {
  const text = value || 'unavailable'
  const tone = ['approved', 'healthy', 'accepted', 'running', 'qualified'].includes(text.toLowerCase())
    ? 'positive'
    : ['rejected', 'failed', 'error', 'cancelled'].includes(text.toLowerCase()) ? 'negative' : 'caution'
  return <span className={`pill pill--${tone}`}>{text.charAt(0).toUpperCase() + text.slice(1)}</span>
}

export function ErrorBanner({ error, onRetry, title = 'Request failed' }: { error: ApiFailure; onRetry?: () => void; title?: string }) {
  return (
    <section className="error-banner" role="alert" aria-live="assertive">
      <div>
        <p className="eyebrow">{title}</p>
        <div className="error-title"><strong>{error.code}</strong><span>{error.message}</span></div>
        {error.remediation && <p>{error.remediation}</p>}
        <dl className="inline-meta">
          <div><dt>HTTP</dt><dd>{error.status || 'network'}</dd></div>
          <div><dt>Operation</dt><dd>{error.operationId || 'not supplied'}</dd></div>
          <div><dt>Retryable</dt><dd>{error.retryable ? 'yes' : 'no'}</dd></div>
        </dl>
      </div>
      {onRetry && <button className="button button--danger" onClick={onRetry}>Retry request</button>}
    </section>
  )
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-mark" aria-hidden="true" /><h3>{title}</h3><p>{body}</p>{action}</div>
}

export function StatusStrip({ status }: { status: ServiceStatus | null }) {
  if (!status) return <div className="status-strip"><span>Service status unavailable</span></div>
  return (
    <section className="status-strip" aria-label="Service and qualification status">
      <div className="status-heading"><span className="live-dot" />API {status.version}<small>{status.mode}</small></div>
      <div className="status-items">
        {status.checks.map(check => <div className="status-item" key={`check-${check.name}`}><StatusPill value={check.status} /><span>{check.name}</span><small>{check.detail}</small></div>)}
        {status.qualifications.map(item => <div className="status-item qualification" key={`qualification-${item.wave}`}><StatusPill value={item.status} /><span>{item.wave}</span><small>{item.detail}</small></div>)}
        {!status.checks.length && !status.qualifications.length && <span className="muted">No checks or qualification evidence reported.</span>}
      </div>
    </section>
  )
}

function EvidenceRow({ label, value, children }: { label: string; value?: string | null; children?: ReactNode }) {
  return <div className="evidence-row"><span>{label}</span><div>{children ?? <StatusPill value={value} />}</div></div>
}

export type Selection =
  | { kind: 'problem'; item: Problem }
  | { kind: 'experiment'; item: Experiment }
  | { kind: 'claim'; item: Claim }
  | { kind: 'artifact'; item: Artifact }
  | { kind: 'branch'; item: Branch }
  | null

export function EvidencePanel({ selection, ledger, ledgerError, reviews, onReview, onExport, onTransition, busy = false }: {
  selection: Selection
  busy?: boolean
  ledger: Ledger | null
  ledgerError: ApiFailure | null
  reviews: Review[]
  onReview: (problem: Problem) => void
  onExport: (experiment: Experiment) => void
  onTransition?: (experiment: Experiment, action: 'start' | 'pause' | 'resume' | 'cancel') => void
}) {
  return (
    <aside className="detail-panel" aria-label="Evidence detail">
      <div className="panel-heading"><p className="eyebrow">Selected record</p><h2>Evidence detail</h2></div>
      {!selection && <EmptyState title="Select a record" body="Inspect a problem, claim, experiment, branch, or artifact without collapsing distinct evidence states." />}
      {selection?.kind === 'problem' && <>
        <DetailHeader title={selection.item.title} subtitle={`${selection.item.program} problem · revision ${selection.item.revision}`} />
        <div className="evidence-grid">
          <EvidenceRow label="Semantic review" value={selection.item.semantic_review} />
          <EvidenceRow label="Formal proof" value={selection.item.proof_status ?? 'not reported'} />
          <EvidenceRow label="Novelty review" value={selection.item.novelty_status ?? 'not reported'} />
          <EvidenceRow label="Assumptions"><TagList items={selection.item.assumptions} empty="None recorded" /></EvidenceRow>
        </div>
        <DetailBlock label="Informal statement" value={selection.item.informal_statement} />
        <DetailBlock label="Formal target" value={selection.item.formal_statement || selection.item.target_theorem} mono />
        <DetailBlock label="Source" value={selection.item.source} />
        <DetailBlock label="Environment digest" value={selection.item.environment_digest} mono />
        <DetailBlock label="Target digest" value={selection.item.target_digest} mono />
        <h3 className="subhead">Recorded target reviews</h3>
        {reviews.filter(review => review.problem_id === selection.item.id).length ? reviews.filter(review => review.problem_id === selection.item.id).map(review => <div className="review-card" key={review.id}><StatusPill value={review.decision} /><p>{review.rationale}</p><small>{review.reviewed_by ? `Reviewer ${review.reviewed_by}` : 'Reviewer identity not returned'} · {review.created_at}</small></div>) : <p className="muted">No review decision returned for this target.</p>}
        <button className="button button--secondary full" onClick={() => onReview(selection.item)}>Review target meaning</button>
      </>}
      {selection?.kind === 'claim' && <>
        <DetailHeader title="Scientific claim" subtitle={`revision ${selection.item.revision}`} />
        <blockquote>{selection.item.statement}</blockquote>
        <div className="evidence-grid">
          <EvidenceRow label="Claim evidence" value={selection.item.evidence} />
          <EvidenceRow label="Formal proof" value={selection.item.proof_status ?? 'not reported'} />
          <EvidenceRow label="Semantic review" value={selection.item.semantic_review ?? 'not reported'} />
          <EvidenceRow label="Novelty review" value={selection.item.novelty_status ?? 'not reported'} />
          <EvidenceRow label="Assumptions"><TagList items={selection.item.assumptions} empty="None recorded" /></EvidenceRow>
        </div>
        <DetailBlock label="Artifact" value={selection.item.artifact_id || 'No artifact attached'} mono />
      </>}
      {selection?.kind === 'experiment' && <>
        <DetailHeader title={`Experiment ${selection.item.id.slice(0, 8)}`} subtitle={`${selection.item.status} · revision ${selection.item.revision}`} />
        <div className="evidence-grid">
          <EvidenceRow label="Execution status" value={selection.item.status} />
          <EvidenceRow label="Formal proof" value="not implied" />
        </div>
        <DetailBlock label="Target digest" value={selection.item.target_digest} mono />
        <DetailBlock label="Policy / mode" value={`${selection.item.policy} / ${selection.item.mode}`} />
        <h3 className="subhead">Exact model configuration</h3>
        {selection.item.models.length ? selection.item.models.map((model, index) => <div className="model-card" key={`${model.runtime}-${model.model}-${index}`}><strong>{model.model}</strong><span>{model.runtime}</span><code>{JSON.stringify(model.parameters)}</code></div>) : <p className="muted">No model configuration returned.</p>}
        <h3 className="subhead">Resource ledger</h3>
        {ledger && <dl className="ledger">
          <div><dt>Spent</dt><dd>${ledger.spent_cost_usd}</dd></div><div><dt>Reserved</dt><dd>${ledger.reserved_cost_usd}</dd></div>
          <div><dt>Maximum</dt><dd>${ledger.max_cost_usd}</dd></div><div><dt>Active workers</dt><dd>{String(ledger.active_workers)}</dd></div>
          <div><dt>Concurrency</dt><dd>{String(ledger.max_concurrency)}</dd></div><div><dt>Uncertain ops</dt><dd>{Array.isArray(ledger.uncertain_operations) ? ledger.uncertain_operations.length : String(ledger.uncertain_operations)}</dd></div>
        </dl>}
        {ledgerError && <ErrorBanner error={ledgerError} title="Ledger unavailable" />}
        {!ledger && !ledgerError && <p className="muted">Loading server ledger…</p>}
        <div className="transition-row detail-transitions">{actionsFor(selection.item.status).map(action => <button key={action} className={action === 'cancel' ? 'button button--danger' : 'button button--secondary'} disabled={busy} aria-label={`${action} experiment`} onClick={() => onTransition?.(selection.item, action)}>{action.charAt(0).toUpperCase() + action.slice(1)}</button>)}</div>
        <button className="button button--secondary full" onClick={() => onExport(selection.item)}>Export reproducibility manifest</button>
      </>}
      {selection?.kind === 'artifact' && <>
        <DetailHeader title={selection.item.artifact_kind} subtitle={selection.item.media_type} />
        <DetailBlock label="SHA-256" value={selection.item.sha256} mono />
        <DetailBlock label="Experiment" value={selection.item.experiment_id || 'Unscoped'} mono />
        <DetailBlock label="Provenance" value={JSON.stringify(selection.item.provenance, null, 2)} mono />
        <DetailBlock label="Stored source / log" value={selection.item.content ?? 'Loading artifact content from the service…'} mono />
      </>}
      {selection?.kind === 'branch' && <>
        <DetailHeader title={selection.item.title} subtitle={`${selection.item.relation} branch`} />
        <DetailBlock label="Objective" value={selection.item.objective} />
        <DetailBlock label="Parent" value={selection.item.parent_id || 'Root branch'} mono />
        <DetailBlock label="Checkpoint" value={selection.item.checkpoint_id || 'No checkpoint'} mono />
        <div className="evidence-grid"><EvidenceRow label="Branch status" value={selection.item.status ?? 'not reported'} /><EvidenceRow label="Formal proof" value="not implied" /></div>
      </>}
    </aside>
  )
}

function DetailHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="detail-header"><h3>{title}</h3><p>{subtitle}</p></header>
}

function DetailBlock({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="detail-block"><span>{label}</span><p className={mono ? 'mono' : ''}>{value}</p></div>
}

function TagList({ items, empty }: { items: string[]; empty: string }) {
  return items.length ? <div className="tag-list">{items.map(item => <span key={item}>{item}</span>)}</div> : <span className="muted">{empty}</span>
}

export function Modal({ title, description, children, onClose }: { title: string; description: string; children: ReactNode; onClose: () => void }) {
  return <div className="modal-backdrop" role="presentation" onMouseDown={event => { if (event.currentTarget === event.target) onClose() }}>
    <section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <header><div><p className="eyebrow">Create canonical record</p><h2 id="modal-title">{title}</h2><p>{description}</p></div><button className="icon-button" aria-label="Close dialog" onClick={onClose}>×</button></header>
      {children}
    </section>
  </div>
}
