import { BranchesOutlined, CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, LinkOutlined, LoadingOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { stageNames } from '../types'
import type { Generation, StageName, TimelineState } from '../types'

const names: Record<StageName, string> = {
  catalog: 'Extração do schema', prompt: 'Construção do prompt', generation: 'Geração de SQL',
  validation: 'Validação SQL', execution: 'Execução no PostgreSQL', response: 'Montagem da resposta',
}

const labels = { running: 'Em andamento', ok: 'Concluída', failed: 'Falhou', skipped: 'Pulada', pending: 'Aguardando' }

export function formatDuration(value?: number | null) {
  if (value == null) return '—'
  const formatted = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 })
  return value >= 1000 ? `${formatted.format(value / 1000)} s` : `${formatted.format(value)} ms`
}

export function traceUrl(traceId: string | undefined) {
  const project: string | undefined = import.meta.env.VITE_LANGFUSE_PROJECT_ID
  if (!traceId || !project) return undefined
  try {
    const base = new URL(import.meta.env.VITE_LANGFUSE_URL || 'http://localhost:3000')
    if (base.protocol !== 'http:' && base.protocol !== 'https:') return undefined
    return new URL(`project/${encodeURIComponent(project)}/traces/${encodeURIComponent(traceId)}`, `${base.href.replace(/\/$/, '')}/`).href
  } catch {
    return undefined
  }
}

interface ProcessingProps {
  timeline: TimelineState
  complete: boolean
  duration: number | null
  generation?: Generation | null
  traceId?: string
}

function tokens(value?: number | null) {
  return value == null ? '—' : new Intl.NumberFormat('pt-BR').format(value)
}

export function Processing({ timeline, complete, duration, generation, traceId }: ProcessingProps) {
  const url = traceUrl(traceId)
  return (
    <aside className="processing" aria-label="Monitor de execução">
      <section className="panel timeline-panel">
        <div className="panel-heading">
          <h2><BranchesOutlined /> Processamento</h2>
        </div>
        <ol className="pipeline" aria-label="Timeline de processamento" aria-live="polite">
          {stageNames.map((name) => {
            const stage = timeline[name]
            const status = stage?.status ?? (complete ? 'skipped' : 'pending')
            return (
              <li key={name} className={`pipeline-stage ${status}`}>
                <span className="stage-indicator" aria-hidden>
                  {status === 'running' ? <LoadingOutlined /> : status === 'ok' ? <CheckCircleOutlined />
                    : status === 'failed' ? <CloseCircleOutlined /> : <span />}
                </span>
                <div><strong>{names[name]}</strong><small>{labels[status]}</small></div>
                <span className="stage-time">{formatDuration(stage?.duration_ms)}</span>
              </li>
            )
          })}
        </ol>
        {traceId && <div className="trace-footer">
          <code title={traceId}>Trace {traceId}</code>
          {url ? <Button type="link" href={url} target="_blank" rel="noopener noreferrer" icon={<LinkOutlined />}>Langfuse</Button>
            : <small>Configure o ID do projeto para abrir no Langfuse.</small>}
        </div>}
      </section>
      <section className="panel metrics-panel">
        <div className="panel-heading"><h2><ClockCircleOutlined /> Métricas</h2></div>
        <dl className="metrics">
          <div><dt>Latência total</dt><dd>{formatDuration(duration)}</dd></div>
          <div><dt>Latência do modelo</dt><dd>{formatDuration(generation?.latency_ms)}</dd></div>
          <div><dt>Tokens de entrada</dt><dd>{tokens(generation?.input_tokens)}</dd></div>
          <div><dt>Tokens de saída</dt><dd>{tokens(generation?.output_tokens)}</dd></div>
        </dl>
      </section>
    </aside>
  )
}
