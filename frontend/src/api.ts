import { stageNames } from './types'
import type { Models, QueryResponse, Schema, StageEvent, StreamResult } from './types'

function record(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null ? value as Record<string, unknown> : undefined
}

async function ensureSuccess(response: Response) {
  if (response.ok) return
  const payload: unknown = await response.json().catch(() => null)
  const detail = record(payload)?.detail
  throw new Error(typeof detail === 'string' ? detail : `A API respondeu com HTTP ${response.status}.`)
}

async function get<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  await ensureSuccess(response)
  return await response.json() as T
}

export const getSchema = (signal: AbortSignal) => get<Schema>('/api/schema', signal)
export const getModels = (signal: AbortSignal) => get<Models>('/api/models', signal)

function parseStage(value: unknown): StageEvent | undefined {
  const stage = record(value)
  if (!stage || typeof stage.trace_id !== 'string'
    || (stage.name !== 'query' && !stageNames.some((name) => name === stage.name))
    || (stage.status !== 'running' && stage.status !== 'ok' && stage.status !== 'failed')
    || (stage.duration_ms !== null && typeof stage.duration_ms !== 'number')
    || (stage.error !== null && typeof stage.error !== 'string')) return
  return stage as unknown as StageEvent
}

function parseResult(value: unknown): StreamResult {
  const envelope = record(value)
  const result = record(envelope?.response)
  if (!result || typeof envelope?.http_status !== 'number' || typeof result.trace_id !== 'string') {
    throw new Error('A consulta retornou uma resposta inválida.')
  }
  if (!Array.isArray(result.stages)) {
    throw new Error(typeof result.detail === 'string' ? result.detail : 'Resposta sem histórico de etapas.')
  }
  return { http_status: envelope.http_status, response: result as unknown as QueryResponse }
}

function parseFrame(frame: string) {
  const lines = frame.split(/\r?\n/)
  const name = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
  const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  return { name, data }
}

export async function streamQuery(
  question: string, model: string | undefined, signal: AbortSignal,
  onStage: (event: StageEvent) => void,
): Promise<StreamResult> {
  const response = await fetch('/api/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ question, model, include_prompt: true }),
    signal,
  })
  await ensureSuccess(response)
  if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error('A API não abriu o fluxo de eventos.')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        const { name, data } = parseFrame(frame)
        if (name === 'stage') {
          const event = parseStage(JSON.parse(data) as unknown)
          if (event) onStage(event)
        }
        if (name === 'result') return parseResult(JSON.parse(data) as unknown)
      }
    }
    throw new Error('O fluxo foi interrompido antes do resultado.')
  } finally {
    void reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
