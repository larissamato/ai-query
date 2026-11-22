import { Alert, Button, Card, Progress, Select, Space, Table } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { getEvaluationCases, runEvaluationCase } from '../api'
import type { EvaluationAttempt, EvaluationCatalog, EvaluationMode, Models } from '../types'
import { traceUrl } from './Processing'

const outcomeLabels: Record<EvaluationAttempt['outcome'], string> = {
  correct: 'Acerto',
  insufficient_data: 'Dados insuficientes',
  sql_rejected: 'SQL rejeitado',
  error: 'Falha operacional',
  classification_mismatch: 'Classificação divergente',
  result_mismatch: 'Resultado divergente',
  operator_mismatch: 'Construção SQL divergente',
}

function metrics(attempt: EvaluationAttempt) {
  const generation = attempt.stages.find((stage) => stage.name === 'generation')
  const execution = attempt.stages.find((stage) => stage.name === 'execution')
  const validation = attempt.stages.find((stage) => stage.name === 'validation')
  return {
    generation_ms: attempt.generation?.latency_ms ?? generation?.duration_ms ?? null,
    execution_ms: execution?.duration_ms ?? null,
    input_tokens: attempt.usage.input_tokens,
    output_tokens: attempt.usage.output_tokens,
    validation: validation?.status ?? null,
    validation_detail: validation?.detail ?? null,
  }
}

function exportRow(attempt: EvaluationAttempt) {
  return {
    ...attempt.case,
    dataset_sha256: attempt.dataset_sha256,
    snapshot_sha256: attempt.snapshot_sha256,
    mode: attempt.mode,
    reference_date: attempt.reference_date,
    seed_version: attempt.seed_version,
    model_digest: attempt.model_digest,
    generation_config: attempt.generation_config,
    insufficient_data_reason: attempt.insufficient_data_reason,
    model_requested: attempt.model_requested,
    model_returned: attempt.generation?.model ?? null,
    prompt_version: attempt.generation?.prompt_version ?? null,
    expected_result: attempt.expected_result,
    generated_sql: attempt.generation?.sql ?? null,
    actual_status: attempt.generation?.status ?? null,
    actual_result: attempt.result,
    outcome: attempt.outcome,
    http_status: attempt.http_status,
    latency_ms: attempt.latency_ms,
    trace_id: attempt.trace_id,
    stages: attempt.stages,
    ...metrics(attempt),
  }
}

function csvCell(value: unknown) {
  const raw = value == null ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  const safe = typeof value === 'string' && /^[\s\u0000-\u001f]*[=+\-@\t\r\n]/.test(raw) ? "'" + raw : raw
  return '"' + safe.replaceAll('"', '""') + '"'
}

function download(format: 'csv' | 'json', attempts: EvaluationAttempt[]) {
  const rows = attempts.map(exportRow)
  const headers = Array.from(new Set(rows.flatMap(Object.keys)))
  const csv = [headers.map(csvCell).join(','), ...rows.map((row) => headers
    .map((header) => csvCell((row as Record<string, unknown>)[header])).join(','))].join('\r\n')
  const body = format === 'json' ? JSON.stringify(rows, null, 2) : '\uFEFF' + csv
  const mime = format === 'json' ? 'application/json' : 'text/csv;charset=utf-8'
  const url = URL.createObjectURL(new Blob([body], { type: mime }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `avaliacao-experimental.${format}`
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Falha na avaliação.'
}

function AttemptDetails({ attempt }: { attempt: EvaluationAttempt }) {
  const data = exportRow(attempt)
  const trace = traceUrl(attempt.trace_id)
  return <div className="evaluation-details">
    <p><strong>{attempt.case.question}</strong></p>
    <p>{attempt.case.concept} · {attempt.case.complexity} · Validação {data.validation ?? 'indisponível'}</p>
    <p>Trace Langfuse {trace ? <a href={trace} target="_blank" rel="noreferrer">{attempt.trace_id}</a> : <code>{attempt.trace_id}</code>}</p>
    <p>Hash dos dados <code>{attempt.snapshot_sha256}</code></p>
    <p>Hash das perguntas <code>{attempt.dataset_sha256}</code></p>
    {attempt.reference_date && <p>Data de referência {attempt.reference_date} · Seed {attempt.seed_version}</p>}
    {attempt.model_digest && <p>Hash do modelo <code>{attempt.model_digest}</code></p>}
    {attempt.generation_config && <p>Configuração da geração <code>{JSON.stringify(attempt.generation_config)}</code></p>}
    {attempt.insufficient_data_reason && <Alert type="warning" showIcon title={attempt.insufficient_data_reason} />}
    {data.operator && <p>Construção exigida <code>{data.operator}</code></p>}
    <p>Geração {data.generation_ms ?? '—'} ms · Execução {data.execution_ms ?? '—'} ms · Tokens {data.input_tokens ?? '—'} entrada / {data.output_tokens ?? '—'} saída</p>
    {attempt.stages.filter((stage) => stage.detail).map((stage) => <p key={stage.name}>{stage.detail}</p>)}
    <div className="evaluation-comparison">
      <section><h3>Referência</h3><pre>{data.reference_sql ?? data.expected_status}</pre><pre>{data.expected_result ? JSON.stringify(data.expected_result, null, 2) : '—'}</pre></section>
      <section><h3>Modelo</h3><pre>{data.generated_sql ?? data.actual_status ?? '—'}</pre><pre>{data.actual_result ? JSON.stringify(data.actual_result, null, 2) : '—'}</pre></section>
    </div>
  </div>
}

export function Evaluation({ models, modelError, retryModels }: { models?: Models; modelError?: string; retryModels: () => void }) {
  const [catalog, setCatalog] = useState<EvaluationCatalog>()
  const [catalogError, setCatalogError] = useState<string>()
  const [revision, reload] = useState(0)
  const [mode, setMode] = useState<EvaluationMode>('dynamic')
  const [category, setCategory] = useState<string>()
  const [caseId, setCaseId] = useState<string>()
  const [selected, setSelected] = useState<string[]>()
  const [attempts, setAttempts] = useState<EvaluationAttempt[]>([])
  const [error, setError] = useState<string>()
  const [progress, setProgress] = useState<{ completed: number; total: number }>()
  const controller = useRef<AbortController | null>(null)

  useEffect(() => {
    const request = new AbortController()
    void getEvaluationCases(request.signal).then(
      (result) => { if (!request.signal.aborted) setCatalog(result) },
      (reason: unknown) => { if (!request.signal.aborted) setCatalogError(errorText(reason)) },
    )
    return () => request.abort()
  }, [revision])
  useEffect(() => () => controller.current?.abort(), [])

  const categories = Array.from(new Set(catalog?.cases.map((item) => item.category)))
  const cases = catalog?.cases.filter((item) => item.category === category) ?? []
  const modelNames = (selected ?? (models ? [models.default] : [])).filter((model) => models?.models.includes(model))
  const visible = attempts.filter((attempt) => attempt.mode === mode
    && (!category || attempt.case.category === category) && (!caseId || attempt.case.id === caseId))
  const groups = new Map<string, { model: string; snapshot: string; rows: EvaluationAttempt[] }>()
  for (const attempt of visible) {
    const key = JSON.stringify([attempt.model_requested, attempt.snapshot_sha256])
    const group = groups.get(key)
    if (group) group.rows.push(attempt)
    else groups.set(key, { model: attempt.model_requested, snapshot: attempt.snapshot_sha256, rows: [attempt] })
  }
  const summaries = Array.from(groups, ([key, { model, snapshot, rows }]) => {
    const correct = rows.filter((attempt) => attempt.outcome === 'correct').length
    const insufficient = rows.filter((attempt) => attempt.outcome === 'insufficient_data').length
    const graded = rows.length - insufficient
    return {
      key, model, snapshot,
      total: rows.length, insufficient, errors: graded - correct, rate: graded ? 100 * correct / graded : null,
      latency: rows.reduce((total, attempt) => total + attempt.latency_ms, 0) / rows.length,
    }
  })

  async function run(scope: typeof cases) {
    if (!scope.length || !modelNames.length || controller.current) return
    const request = new AbortController()
    controller.current = request
    const total = scope.length * modelNames.length
    let completed = 0
    setProgress({ total, completed })
    setError(undefined)
    try {
      for (const item of scope) {
        for (const model of modelNames) {
          const attempt = await runEvaluationCase(item.id, model, mode, request.signal)
          setAttempts((previous) => [...previous, attempt])
          setProgress({ total, completed: ++completed })
        }
      }
    } catch (reason) {
      if (!request.signal.aborted) setError(errorText(reason))
    } finally {
      controller.current = null
      if (!request.signal.aborted) setProgress(undefined)
    }
  }

  return <main className="app-shell evaluation-page">
    <div className="page-heading">
      <h1>Avaliação Experimental</h1>
      {catalog && <p>{catalog.cases.length} perguntas</p>}
    </div>
    <Card title="Execução" loading={!catalog && !catalogError}>
      {catalogError && <Alert type="error" title={catalogError} action={<Button onClick={() => { setCatalogError(undefined); reload(revision + 1) }}>Tentar novamente</Button>} />}
      {modelError && <Alert type="error" title={modelError} action={<Button onClick={retryModels}>Atualizar modelos</Button>} />}
      <label>Modo de avaliação <Select aria-label="Modo de avaliação" value={mode} disabled={!!progress}
        onChange={(value) => { setMode(value); setError(undefined) }} options={[
          { value: 'dynamic', label: 'Dinâmica — banco atual' },
          { value: 'scientific', label: 'Científica — snapshot controlado', disabled: !catalog?.scientific },
        ]} /></label>
      {mode === 'dynamic'
        ? <p>Executa a referência e o SQL do modelo sobre a mesma visão dos dados atuais. Cada tentativa registra o hash dos dados usados.</p>
        : catalog?.scientific && <div>
          <p>Verifica o hash dos dados antes de comparar com as referências versionadas.</p>
          <p>Data de referência {catalog.scientific.reference_date} · Seed {catalog.scientific.seed_version}</p>
          <p>Hash esperado <code>{catalog.scientific.snapshot_sha256}</code></p>
        </div>}
      <div className="evaluation-controls">
        <label>Categoria<Select aria-label="Categoria" value={category} disabled={!!progress} allowClear
          options={categories.map((value) => ({ value }))} onChange={(value) => { setCategory(value); setCaseId(undefined) }} /></label>
        <label>Pergunta<Select aria-label="Pergunta" value={caseId} disabled={!category || !!progress} allowClear
          options={cases.map((item) => ({ value: item.id, label: item.question }))} onChange={setCaseId} /></label>
        <label>Modelos<Select aria-label="Modelos" mode="multiple" value={modelNames} disabled={!!progress}
          options={models?.models.map((value) => ({ value }))} onChange={setSelected} /></label>
      </div>
      <Space wrap>
        <Button type="primary" disabled={!caseId || !modelNames.length || !!progress}
          onClick={() => void run(cases.filter((item) => item.id === caseId))}>Executar pergunta</Button>
        <Button disabled={!category || !modelNames.length || !!progress} onClick={() => {
          setCaseId(undefined)
          void run(cases)
        }}>Executar categoria</Button>
      </Space>
      {progress && <Progress percent={Math.round(100 * progress.completed / progress.total)}
        format={() => `${progress.completed}/${progress.total}`} />}
      {error && <Alert type="error" showIcon title={error} />}
    </Card>
    <Card title="Comparação de modelos">
      <Table rowKey="key" pagination={false} dataSource={summaries} scroll={{ x: 530 }} columns={[
        { title: 'Modelo', dataIndex: 'model' },
        { title: 'Dataset', dataIndex: 'snapshot', render: (value: string) => <code title={value}>{value.slice(0, 12)}</code> },
        { title: 'Tentativas', dataIndex: 'total' },
        { title: 'Acerto', dataIndex: 'rate', render: (value: number | null) => value === null ? '—' : `${value.toFixed(1)}%` },
        { title: 'Dados insuficientes', dataIndex: 'insufficient' },
        { title: 'Erros', dataIndex: 'errors' },
        { title: 'Latência total média', dataIndex: 'latency', render: (value: number) => `${value.toFixed(1)} ms` },
      ]} />
    </Card>
    <Card title="Tentativas" extra={<Space wrap>
      <Button disabled={!visible.length} onClick={() => download('csv', visible)}>CSV</Button>
      <Button disabled={!visible.length} onClick={() => download('json', visible)}>JSON</Button>
    </Space>}>
      <Table rowKey="trace_id" dataSource={visible} scroll={{ x: 650 }} pagination={{ pageSize: 10 }}
        expandable={{ expandedRowRender: (attempt) => <AttemptDetails attempt={attempt} /> }} columns={[
          { title: 'Caso', render: (_, attempt) => attempt.case.id },
          { title: 'Modelo', dataIndex: 'model_requested' },
          { title: 'Resultado', dataIndex: 'outcome', render: (outcome: EvaluationAttempt['outcome']) => outcomeLabels[outcome] },
          { title: 'Latência total', dataIndex: 'latency_ms', render: (value: number) => `${value} ms` },
        ]} />
    </Card>
  </main>
}
