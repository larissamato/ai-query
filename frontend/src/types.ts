export const stageNames = ['catalog', 'prompt', 'generation', 'validation', 'execution', 'response'] as const
export type StageName = typeof stageNames[number]
export type StageStatus = 'running' | 'ok' | 'failed' | 'skipped'

export interface StageEvent {
  trace_id: string
  name: StageName | 'query'
  status: Exclude<StageStatus, 'skipped'>
  duration_ms: number | null
  error: string | null
}

interface QueryStage {
  name: StageName
  status: Exclude<StageStatus, 'running'>
  duration_ms: number | null
  detail: string | null
}

export type TimelineState = Partial<Record<StageName, {
  status: StageStatus
  duration_ms: number | null
  detail: string | null
}>>

export interface PromptMessage {
  role: 'system' | 'user'
  content: string
}

export interface Generation {
  sql: string | null
  explanation: string
  assumptions: string[]
  status: 'generated' | 'ambiguous' | 'unanswerable'
  model: string
  prompt_version: string
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
}

export type Cell = null | string | number | boolean | Cell[] | { [key: string]: Cell }

export interface QueryResult {
  columns: string[]
  rows: Cell[][]
  truncated: boolean
}

export interface QueryResponse {
  trace_id: string
  stages: QueryStage[]
  generation: Generation | null
  result: QueryResult | null
  prompt: PromptMessage[] | null
}

export interface StreamResult {
  http_status: number
  response: QueryResponse
}

export interface Schema {
  schema_name: string
  tables: {
    name: string
    columns: { name: string; data_type: string; nullable: boolean }[]
    primary_key: string[]
    foreign_keys: {
      name: string
      columns: string[]
      referenced_schema: string
      referenced_table: string
      referenced_columns: string[]
    }[]
  }[]
}

export interface Models {
  models: string[]
  default: string
}

export interface HistoryEntry {
  traceId: string
  question: string
  model: string
  time: string
  status: 'ok' | 'failed' | 'ambiguous' | 'unanswerable'
}
