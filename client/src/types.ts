export type RunStatus =
  | 'draft'
  | 'preparing'
  | 'analyzing'
  | 'designing'
  | 'attacking'
  | 'revising'
  | 'verifying'
  | 'judging'
  | 'completed'
  | 'blocked'
  | 'failed'
  | 'cancelled'

export interface Agent {
  id: string
  name: string
  role: string
  short_name: string
  status: 'idle' | 'working' | 'waiting' | 'completed'
  current_task: string | null
  progress: number
  tone: string
}

export interface RunEvent {
  id: string
  sequence: number
  run_id: string
  type: string
  category: 'system' | 'collaboration' | 'attack' | 'revision' | 'gate'
  title: string
  summary: string
  agent_id: string | null
  severity: string
  payload: Record<string, unknown>
  created_at: string
}

export interface Defect {
  id: string
  title: string
  category: string
  severity: string
  status: string
  owner: string
}

export interface ScoreDimension {
  name: string
  score: number
  weight: number
}

export interface Run {
  id: string
  project_name: string
  title: string
  status: RunStatus
  stage: number
  stage_label: string
  progress: number
  agents: Agent[]
  defects: Defect[]
  scores: ScoreDimension[]
  total_score: number | null
  estimated_cost: number
  token_count: number
  created_at: string
  updated_at: string
}

export interface RunSnapshot {
  run: Run
  events: RunEvent[]
}
