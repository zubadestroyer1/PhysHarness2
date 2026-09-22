import { useState, type FormEvent } from 'react'
import type { CampaignInput, ExperimentInput, ProblemInput } from './api'
import type { Campaign, Problem } from './types'

export function CampaignForm({ submit, busy }: { submit: (input: CampaignInput) => Promise<void>; busy: boolean }) {
  const [programs, setPrograms] = useState<Array<'quantum' | 'classical'>>(['quantum'])
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    void submit({ title: String(data.get('title')), objective: String(data.get('objective')), programs })
  }
  const toggle = (value: 'quantum' | 'classical') => setPrograms(current => current.includes(value) ? current.filter(item => item !== value) : [...current, value])
  return <form className="form" onSubmit={onSubmit}>
    <label>Campaign title<input name="title" required autoFocus /></label>
    <label>Research objective<textarea name="objective" rows={4} required /></label>
    <fieldset><legend>Programs</legend><label className="check"><input type="checkbox" checked={programs.includes('quantum')} onChange={() => toggle('quantum')} />Quantum information</label><label className="check"><input type="checkbox" checked={programs.includes('classical')} onChange={() => toggle('classical')} />Classical mathematical physics</label></fieldset>
    <button className="button button--primary" disabled={busy || !programs.length}>{busy ? 'Creating…' : 'Create campaign'}</button>
  </form>
}

export function ProblemForm({ campaigns, submit, busy }: { campaigns: Campaign[]; submit: (input: ProblemInput) => Promise<void>; busy: boolean }) {
  const [formError, setFormError] = useState('')
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    try {
      setFormError('')
      void submit({
        campaign_id: String(data.get('campaign_id')), title: String(data.get('title')),
        program: String(data.get('program')) as 'quantum' | 'classical',
        informal_statement: String(data.get('informal_statement')), formal_statement: String(data.get('formal_statement')),
        target_theorem: String(data.get('target_theorem')), assumptions: lines(data.get('assumptions')),
        definitions: parseDefinitions(data.get('definitions')), source: String(data.get('source')), environment_digest: String(data.get('environment_digest')),
      })
    } catch (error) { setFormError(error instanceof Error ? error.message : 'Definitions must be valid JSON.') }
  }
  return <form className="form form--two" onSubmit={onSubmit}>
    <label>Campaign<select name="campaign_id" required defaultValue={campaigns[0]?.id}>{campaigns.map(campaign => <option key={campaign.id} value={campaign.id}>{campaign.title}</option>)}</select></label>
    <label>Program<select name="program" defaultValue="quantum"><option value="quantum">Quantum</option><option value="classical">Classical</option></select></label>
    <label className="wide">Problem title<input name="title" required /></label>
    <label className="wide">Informal statement<textarea name="informal_statement" rows={3} required /></label>
    <label className="wide">Formal statement<textarea name="formal_statement" rows={3} required /></label>
    <label>Target theorem<input name="target_theorem" required /></label>
    <label>Environment digest<input name="environment_digest" pattern="[0-9a-f]{64}" minLength={64} maxLength={64} required /></label>
    <label className="wide">Assumptions <small>one per line</small><textarea name="assumptions" rows={3} /></label>
    <label className="wide">Definitions <small>JSON object</small><textarea name="definitions" rows={3} defaultValue="{}" /></label>
    <label className="wide">Source<textarea name="source" rows={3} required /></label>
    {formError && <p className="form-error wide" role="alert">{formError}</p>}
    <button className="button button--primary wide" disabled={busy}>{busy ? 'Submitting…' : 'Propose problem'}</button>
  </form>
}

export function ExperimentForm({ campaigns, problems, submit, busy }: { campaigns: Campaign[]; problems: Problem[]; submit: (input: ExperimentInput) => Promise<void>; busy: boolean }) {
  const [campaignId, setCampaignId] = useState(campaigns[0]?.id ?? '')
  const [formError, setFormError] = useState('')
  const availableProblems = problems.filter(problem => !campaignId || problem.campaign_id === campaignId)
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    try {
      setFormError('')
      void submit({
        campaign_id: String(data.get('campaign_id')), problem_id: String(data.get('problem_id')),
        models: [{ runtime: String(data.get('runtime')), model: String(data.get('model')), parameters: parseObject(data.get('parameters')) }],
        budget: { max_cost_usd: String(data.get('max_cost_usd')), max_concurrency: Number(data.get('max_concurrency')), max_runtime_seconds: Number(data.get('max_runtime_seconds')) },
        policy: String(data.get('policy')), mode: String(data.get('mode')),
      })
    } catch (error) { setFormError(error instanceof Error ? error.message : 'Model parameters must be valid JSON.') }
  }
  return <form className="form form--two" onSubmit={onSubmit}>
    <label>Campaign<select name="campaign_id" required value={campaignId} onChange={event => setCampaignId(event.target.value)}>{campaigns.map(campaign => <option key={campaign.id} value={campaign.id}>{campaign.title}</option>)}</select></label>
    <label>Problem<select name="problem_id" required defaultValue=""><option value="" disabled>Select a problem</option>{availableProblems.map(problem => <option key={problem.id} value={problem.id}>{problem.title}</option>)}</select></label>
    <label>Runtime<input name="runtime" required placeholder="codex-sdk" /></label>
    <label>Model<input name="model" required placeholder="exact provider model id" /></label>
    <label className="wide">Model parameters <small>JSON object</small><textarea name="parameters" rows={3} defaultValue="{}" /></label>
    <label>Max cost (USD)<input name="max_cost_usd" inputMode="decimal" pattern="[0-9]+(\.[0-9]{1,8})?" defaultValue="10.00" required /></label>
    <label>Max concurrency<input name="max_concurrency" type="number" min="1" step="1" defaultValue="1" required /></label>
    <label>Duration limit (seconds)<input name="max_runtime_seconds" type="number" min="1" step="1" defaultValue="3600" required /></label>
    <label>Policy<input name="policy" defaultValue="independent" required /></label>
    <label>Mode<select name="mode" defaultValue="research"><option value="research">Research</option><option value="discovery">Discovery</option><option value="literature_assisted">Literature assisted</option><option value="replay">Replay</option></select></label>
    {formError && <p className="form-error wide" role="alert">{formError}</p>}
    <button className="button button--primary wide" disabled={busy}>{busy ? 'Creating…' : 'Create experiment'}</button>
  </form>
}

export function ReviewForm({ submit, busy }: { submit: (decision: 'approved' | 'rejected', rationale: string) => Promise<void>; busy: boolean }) {
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    void submit(String(data.get('decision')) as 'approved' | 'rejected', String(data.get('rationale')))
  }
  return <form className="form" onSubmit={onSubmit}>
    <label>Decision<select name="decision"><option value="approved">Approve target meaning</option><option value="rejected">Reject target meaning</option></select></label>
    <label>Rationale<textarea name="rationale" rows={5} required /></label>
    <p className="form-note">The server enforces reviewer privileges. This decision records semantic review; it does not assert proof or novelty.</p>
    <button className="button button--primary" disabled={busy}>{busy ? 'Recording…' : 'Record review'}</button>
  </form>
}

const lines = (value: FormDataEntryValue | null) => String(value ?? '').split('\n').map(item => item.trim()).filter(Boolean)
const parseObject = (value: FormDataEntryValue | null): Record<string, unknown> => {
  const text = String(value ?? '').trim()
  return text ? JSON.parse(text) as Record<string, unknown> : {}
}
const parseDefinitions = (value: FormDataEntryValue | null): Record<string, string> => {
  const parsed = parseObject(value)
  if (Object.values(parsed).some(item => typeof item !== 'string')) throw new Error('Definition values must be strings.')
  return parsed as Record<string, string>
}
