export type EvidenceStatus = 'pending' | 'approved' | 'rejected' | 'unavailable' | 'unqualified' | 'unknown' | string

export interface CoreRecord {
  id: string
  project_id: string
  revision: number
  created_at: string
}

export interface Campaign extends CoreRecord {
  title: string
  objective: string
  programs: Array<'quantum' | 'classical'>
}

export interface Problem extends CoreRecord {
  campaign_id: string
  title: string
  program: 'quantum' | 'classical'
  informal_statement: string
  formal_statement: string
  assumptions: string[]
  definitions: Record<string, unknown>
  source: string
  environment_digest: string
  target_theorem: string
  target_digest: string
  semantic_review: EvidenceStatus
  proof_status?: EvidenceStatus
  novelty_status?: EvidenceStatus
}

export interface ModelConfiguration {
  runtime: string
  model: string
  parameters: Record<string, unknown>
}

export interface ExperimentBudget {
  max_cost_usd: string
  max_concurrency: number
  max_runtime_seconds: number
}

export interface Experiment extends CoreRecord {
  campaign_id: string
  problem_id: string
  models: ModelConfiguration[]
  budget: ExperimentBudget
  policy: string
  mode: string
  status: string
  target_digest: string
}

export interface Branch extends CoreRecord {
  experiment_id: string
  title: string
  objective: string
  parent_id?: string | null
  relation: 'helper' | 'collaborator' | 'competing'
  checkpoint_id?: string | null
  status?: string
}

export interface Claim extends CoreRecord {
  experiment_id: string
  statement: string
  assumptions: string[]
  evidence: 'conjecture' | 'numerical' | 'conditional'
  artifact_id?: string | null
  proof_status?: EvidenceStatus
  semantic_review?: EvidenceStatus
  novelty_status?: EvidenceStatus
}

export interface Artifact extends CoreRecord {
  experiment_id?: string | null
  artifact_kind: string
  content?: string
  media_type: string
  provenance: Record<string, unknown>
  sha256: string
  size_bytes?: number
}

export interface Review extends CoreRecord {
  problem_id?: string
  scope?: string
  target_digest?: string
  decision: 'approved' | 'rejected'
  rationale: string
  reviewed_by?: string
}

export interface EventRecord {
  sequence: number
  kind: string
  aggregate_id: string
  operation_id: string
  payload: Record<string, unknown>
  created_at: string
}

export interface Program extends CoreRecord {
  name?: string
  title?: string
  status?: string
  [key: string]: unknown
}

export interface ServiceCheck {
  name: string
  status: EvidenceStatus
  detail: string
}

export interface Qualification {
  wave: string | number
  status: EvidenceStatus
  detail: string
}

export interface ServiceStatus {
  version: string
  mode: string
  checks: ServiceCheck[]
  qualifications: Qualification[]
}

export interface Ledger {
  max_cost_usd: string
  reserved_cost_usd: string
  spent_cost_usd: string
  active_workers: number
  max_concurrency: number
  uncertain_operations: number | string[]
}

export interface WorkspaceData {
  campaigns: Campaign[]
  problems: Problem[]
  experiments: Experiment[]
  branches: Branch[]
  tasks: CoreRecord[]
  claims: Claim[]
  artifacts: Artifact[]
  reviews: Review[]
  sessions: CoreRecord[]
  programs: Program[]
  events: EventRecord[]
  status: ServiceStatus | null
}

export const emptyWorkspace: WorkspaceData = {
  campaigns: [], problems: [], experiments: [], branches: [], tasks: [], claims: [],
  artifacts: [], reviews: [], sessions: [], programs: [], events: [], status: null,
}
