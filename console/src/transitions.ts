export type ExperimentAction = 'start' | 'pause' | 'resume' | 'cancel'

export function actionsFor(status: string): ExperimentAction[] {
  if (status === 'created') return ['start', 'cancel']
  if (status === 'queued' || status === 'running') return ['pause', 'cancel']
  if (status === 'paused' || status === 'blocked') return ['resume', 'cancel']
  return []
}
