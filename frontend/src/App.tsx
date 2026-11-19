import { CodeOutlined } from '@ant-design/icons'
import { Alert } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { getModels, getSchema, streamQuery } from './api'
import { Processing } from './components/Processing'
import { QueryInput } from './components/QueryInput'
import { QueryOutput } from './components/QueryOutput'
import { Workspace } from './components/Workspace'
import type { HistoryEntry, QueryResponse, TimelineState } from './types'

const historyKey = 'ai-query.history.v1'
const historyStatuses = ['ok', 'failed', 'ambiguous', 'unanswerable']

function readHistory(): HistoryEntry[] {
  try {
    const entries: unknown = JSON.parse(window.localStorage.getItem(historyKey) ?? '[]')
    if (!Array.isArray(entries)) return []
    return entries.filter((entry): entry is HistoryEntry => entry !== null && typeof entry === 'object'
      && typeof entry.traceId === 'string' && typeof entry.question === 'string' && typeof entry.model === 'string'
      && typeof entry.time === 'string' && historyStatuses.includes(entry.status)).slice(0, 20)
  } catch {
    return []
  }
}

function message(error: unknown) {
  if (error instanceof TypeError) return 'Não foi possível conectar à API.'
  return error instanceof Error ? error.message : 'Não foi possível concluir a operação.'
}

function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [revision, refresh] = useState(0)
  const [result, setResult] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true })
  useEffect(() => {
    const controller = new AbortController()
    void load(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ data, loading: false }) },
      (error: unknown) => { if (!controller.signal.aborted) setResult({ error: message(error), loading: false }) },
    )
    return () => controller.abort()
  }, [load, revision])
  return { ...result, retry: () => { setResult({ loading: true }); refresh((value) => value + 1) } }
}

export default function App() {
  const schema = useResource(getSchema)
  const models = useResource(getModels)
  const [question, setQuestion] = useState('')
  const [model, setModel] = useState<string>()
  const [running, setRunning] = useState(false)
  const [history, setHistory] = useState(readHistory)
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [error, setError] = useState<string>()
  const [timeline, setTimeline] = useState<TimelineState>({})
  const [duration, setDuration] = useState<number | null>(null)
  const [traceId, setTraceId] = useState<string>()
  const [completed, setCompleted] = useState(false)
  const controller = useRef<AbortController | null>(null)
  const selected = models.data?.models.find((item) => item === model)
    ?? models.data?.models.find((item) => item === models.data?.default)
    ?? models.data?.models[0]

  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => {
    try {
      window.localStorage.setItem(historyKey, JSON.stringify(history))
    } catch {
      // The current session still keeps its history if storage is unavailable.
    }
  }, [history])

  async function run() {
    const input = question.trim()
    if (!input || controller.current) return
    const request = new AbortController()
    controller.current = request
    setRunning(true)
    setResponse(null)
    setError(undefined)
    setTimeline({})
    setDuration(null)
    setTraceId(undefined)
    setCompleted(false)
    try {
      const result = await streamQuery(input, selected, request.signal, (event) => {
        if (request.signal.aborted) return
        setTraceId(event.trace_id)
        const { name } = event
        if (name === 'query') setDuration(event.duration_ms)
        else setTimeline((previous) => ({ ...previous, [name]: {
          status: event.status, duration_ms: event.duration_ms, detail: event.error,
        } }))
      })
      if (request.signal.aborted) return
      const body = result.response
      setResponse(body)
      setTraceId(body.trace_id)
      setTimeline((previous) => ({
        ...previous, ...Object.fromEntries(body.stages.map((stage) => [stage.name, stage])),
      }))
      if (result.http_status >= 400) setError(
        body.stages.find((stage) => stage.status === 'failed')?.detail || `Consulta interrompida (HTTP ${result.http_status}).`,
      )
      const status: HistoryEntry['status'] = result.http_status >= 400 ? 'failed'
        : body.generation?.status === 'ambiguous' || body.generation?.status === 'unanswerable' ? body.generation.status
          : 'ok'
      setHistory((previous) => [{
        traceId: body.trace_id, question: input, model: body.generation?.model || selected || 'Modelo padrão',
        time: new Date().toISOString(), status,
      }, ...previous].slice(0, 20))
    } catch (error) {
      if (!request.signal.aborted) {
        setError(message(error))
        setTimeline((previous) => Object.fromEntries(Object.entries(previous).map(([name, stage]) => [
          name, stage?.status === 'running' ? { ...stage, status: 'failed' } : stage,
        ])))
      }
    } finally {
      controller.current = null
      if (!request.signal.aborted) {
        setRunning(false)
        setCompleted(true)
      }
    }
  }

  return (
    <>
      <header className="topbar">
        <div className="brand"><span className="brand-mark"><CodeOutlined /></span><span>AI Query <strong>Playground</strong></span></div>
        <div className="connection" role="status">
          <i data-state={schema.data ? 'online' : schema.error ? 'offline' : 'pending'} />
          {schema.data ? 'PostgreSQL conectado' : schema.error ? 'Conexão indisponível' : 'Conectando ao PostgreSQL'}
        </div>
      </header>
      <main className="app-shell">
        <div className="page-heading">
          <h1>Query Playground</h1>
          <p>De linguagem natural a SQL. Acompanhe cada etapa da consulta.</p>
        </div>
        <div className="app-grid">
          <Workspace schema={schema.data} loading={schema.loading} error={schema.error} history={history}
            onRetry={schema.retry} onReuse={(item) => { setQuestion(item.question); setModel(item.model); document.getElementById('question')?.focus() }} />
          <div className="query-area">
            <QueryInput question={question} onQuestion={setQuestion} selected={selected} onModel={setModel}
              models={models.data} modelLoading={models.loading} modelError={models.error}
              onRetryModels={models.retry} running={running} onRun={() => void run()} />
            {error && <Alert type="error" showIcon title="Consulta interrompida" description={error} />}
            <QueryOutput response={response} running={running} />
          </div>
          <Processing timeline={timeline} complete={completed} duration={duration} generation={response?.generation} traceId={traceId} />
        </div>
      </main>
    </>
  )
}
