// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App as AntApp, ConfigProvider } from 'antd'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { chartData } from './components/ResultData'
import type { QueryResponse } from './types'

const trace = '01020304050607080102030405060708'
const question = 'Quantos pedidos foram registrados?'

const approved: QueryResponse = {
  trace_id: trace,
  stages: [{ name: 'validation', status: 'ok', duration_ms: 2, detail: null }],
  generation: {
    status: 'generated', sql: 'SELECT COUNT(*) FROM ecommerce.orders',
    explanation: 'Conta as linhas em ecommerce.orders.', assumptions: [],
    model: 'modelo-b', prompt_version: 'v1', latency_ms: 14, input_tokens: 50, output_tokens: 11,
  },
  result: { columns: ['total_de_pedidos'], rows: [[1000]], truncated: false },
  prompt: [{ role: 'system', content: 'Mensagem exata do sistema' }, { role: 'user', content: question }],
}

function sse(event: string, data: unknown) {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

function fixture(stream: () => Response, extra?: (url: string, request?: RequestInit) => Response) {
  const routes = vi.fn((url: string, request?: RequestInit) => {
    if (url === '/api/schema') return Promise.resolve(Response.json({
      schema_name: 'ecommerce',
      tables: [{ name: 'orders', columns: [{ name: 'order_id', data_type: 'integer', nullable: false }], primary_key: ['order_id'], foreign_keys: [] }],
    }))
    if (url === '/api/models') return Promise.resolve(Response.json({ models: ['modelo-a', 'modelo-b'], default: 'modelo-a' }))
    if (url === '/api/query/stream') return Promise.resolve(stream())
    if (extra) return Promise.resolve(extra(url, request))
    throw new Error('Rota inesperada')
  })
  vi.stubGlobal('fetch', routes)
  render(<ConfigProvider virtual={false}><AntApp><App /></AntApp></ConfigProvider>)
  return routes
}

beforeEach(() => {
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  })
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  vi.stubEnv('VITE_LANGFUSE_PROJECT_ID', 'projeto-local')
  vi.stubGlobal('matchMedia', vi.fn(() => ({
    matches: false, addListener: vi.fn(), removeListener: vi.fn(),
    addEventListener: vi.fn(), removeEventListener: vi.fn(),
  })))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

async function submit() {
  fireEvent.change(screen.getByLabelText('Pergunta em linguagem natural'), { target: { value: question } })
  const button = screen.getByRole('button', { name: /Executar consulta/ }) as HTMLButtonElement
  await waitFor(() => expect(button.disabled).toBe(false))
  fireEvent.click(button)
}

describe('AI Query Playground', () => {
  it('seleciona um modelo, atualiza a timeline antes do resultado e exibe SQL, prompt, tabela e trace', async () => {
    const controllers: ReadableStreamDefaultController<Uint8Array>[] = []
    const encoder = new TextEncoder()
    const routes = fixture(() => new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(sse('stage', {
          trace_id: trace, name: 'generation', status: 'running', duration_ms: null, error: null,
        })))
        controllers.push(controller)
      },
    }), { headers: { 'Content-Type': 'text/event-stream' } }))

    fireEvent.click(await screen.findByRole('button', { name: /orders/ }))
    expect(await screen.findByText('order_id')).toBeTruthy()
    const model = screen.getByRole('combobox', { name: 'Modelo' })
    fireEvent.mouseDown(model)
    fireEvent.click(await screen.findByRole('option', { name: 'modelo-b' }))
    await submit()
    expect(await screen.findByText('Em andamento')).toBeTruthy()
    const stream = controllers[0]
    if (!stream) throw new Error('O stream não foi iniciado.')
    stream.enqueue(encoder.encode(sse('result', { http_status: 200, response: approved })))
    stream.close()

    expect(await screen.findByText('1000')).toBeTruthy()
    expect(screen.getByText('SQL aprovado')).toBeTruthy()
    expect(screen.getByText('50')).toBeTruthy()
    expect(screen.getByRole('link', { name: /Langfuse/ }).getAttribute('href')).toContain(`/project/projeto-local/traces/${trace}`)
    fireEvent.click(screen.getByRole('tab', { name: /SQL gerado/ }))
    const sql = await screen.findByLabelText('SQL gerado, somente leitura')
    expect(sql.textContent).toBe(approved.generation?.sql)
    expect(sql.querySelector('.hljs-keyword')?.textContent).toBe('SELECT')
    fireEvent.click(screen.getByRole('tab', { name: /Prompt/ }))
    expect(screen.getByText('Mensagem exata do sistema')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: /Histórico/ }))
    expect(within(screen.getByRole('tabpanel', { name: /Histórico/ })).getByText(question)).toBeTruthy()
    const payload = routes.mock.calls.find(([url]) => url === '/api/query/stream') as unknown as [string, RequestInit]
    expect(JSON.parse(payload[1].body as string)).toMatchObject({ model: 'modelo-b', question })
  }, 15_000)

  it('insere um exemplo matemático editável e só envia a pergunta ao executar', async () => {
    const routes = fixture(() => new Response(sse('result', {
      http_status: 200, response: approved,
    }), { headers: { 'Content-Type': 'text/event-stream' } }))

    fireEvent.click(screen.getByText('Explorando a matemática por meio do SQL'))
    fireEvent.click(screen.getByRole('button', { name: 'XOR — Diferença simétrica' }))
    const example = screen.getByRole('button', { name: /mas não atendem às duas condições/ })
    fireEvent.click(example)
    const input = screen.getByLabelText<HTMLTextAreaElement>('Pergunta em linguagem natural')
    expect(input.value).toBe(example.textContent)
    expect(screen.getByText('Produtos com preço acima de R$ 500.')).toBeTruthy()
    expect(screen.getByText('Produtos da categoria Eletrônicos.')).toBeTruthy()
    expect(routes.mock.calls.some(([url]) => url === '/api/query/stream')).toBe(false)

    const edited = input.value.replace('R$ 500', 'R$ 300')
    fireEvent.change(input, { target: { value: edited } })
    const run = screen.getByRole<HTMLButtonElement>('button', { name: /Executar consulta/ })
    await waitFor(() => expect(run.disabled).toBe(false))
    fireEvent.click(run)
    expect(await screen.findByText('1000')).toBeTruthy()
    const request = routes.mock.calls.find(([url]) => url === '/api/query/stream')?.[1]
    expect(JSON.parse(request?.body as string)).toMatchObject({ question: edited })
  }, 15_000)

  it('exibe rejeição da política e permite tentar outra consulta', async () => {
    fixture(() => new Response(sse('result', {
      http_status: 422,
      response: { ...approved, result: null, stages: [
        { name: 'validation', status: 'failed', duration_ms: 1, detail: 'Tabela fora do catálogo autorizado.' },
        { name: 'execution', status: 'skipped', duration_ms: null, detail: null },
      ] },
    }), { headers: { 'Content-Type': 'text/event-stream' } }))
    await submit()
    expect(await screen.findByText('Tabela fora do catálogo autorizado.')).toBeTruthy()
    expect(screen.getByText('SQL rejeitado')).toBeTruthy()
    expect(screen.queryByText('1000')).toBeNull()
    expect((screen.getByRole('button', { name: /Executar consulta/ }) as HTMLButtonElement).disabled).toBe(false)
  })

  it('gera pontos somente para categorias únicas e valores numéricos completos', () => {
    expect(chartData({ columns: ['cidade', 'total'], rows: [['Curitiba', '3.20'], ['Belém', -2]], truncated: false }))
      .toEqual([{ label: 'Curitiba', value: 3.2, display: '3.20' }, { label: 'Belém', value: -2, display: '-2' }])
    expect(chartData({ columns: ['cidade', 'total'], rows: [['Curitiba', 3], ['Belém', 2]], truncated: true })).toBeUndefined()
    expect(chartData({ columns: ['cidade', 'total'], rows: [['Curitiba', 3], ['Curitiba', 2]], truncated: false })).toBeUndefined()
  })
})

it('executa uma categoria da avaliação, compara modelos e exibe os detalhes da tentativa', async () => {
  const caseData = {
    id: 'agg-01', category: 'Agregações', complexity: 'básica', concept: 'Cardinalidade',
    question, reference_sql: approved.generation?.sql, expected_status: 'generated',
  }
  const evaluated = vi.fn()
  const fetchEvaluation = (url: string, request?: RequestInit) => {
    if (url === '/api/evaluation/cases') return Response.json({
      cases: [caseData], dataset_sha256: 'dataset',
      scientific: { reference_date: '2025-01-01', seed_version: 'ecommerce-v1', snapshot_sha256: 'snapshot' },
    })
    if (url === '/api/evaluation/cases/agg-01/run') {
      const { model, mode } = JSON.parse(request?.body as string)
      evaluated(model, mode)
      const correct = model === 'modelo-a'
      return Response.json({
        ...approved,
        trace_id: correct ? trace : '02020304050607080102030405060708',
        case: caseData,
        dataset_sha256: 'dataset', snapshot_sha256: 'snapshot', mode,
        expected_result: approved.result, outcome: correct ? 'correct' : 'result_mismatch',
        latency_ms: 15, http_status: 200, model_requested: model,
        usage: { input_tokens: 50, output_tokens: 11 },
      })
    }
    throw new Error('Rota de avaliação inesperada.')
  }
  fixture(() => new Response(), fetchEvaluation)
  fireEvent.click(screen.getByRole('button', { name: 'Avaliação Experimental' }))
  expect(await screen.findByText('1 perguntas')).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Categoria' }))
  fireEvent.click(await screen.findByRole('option', { name: 'Agregações' }))
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Modelos' }))
  fireEvent.click(await screen.findByRole('option', { name: 'modelo-b' }))
  fireEvent.click(screen.getByRole('button', { name: 'Executar categoria' }))

  expect(await screen.findByText('Resultado divergente')).toBeTruthy()
  expect(evaluated.mock.calls).toEqual([['modelo-a', 'dynamic'], ['modelo-b', 'dynamic']])
  expect(screen.getByText('100.0%')).toBeTruthy()
  expect(screen.getByText('0.0%')).toBeTruthy()
  expect((screen.getByRole('button', { name: 'CSV' }) as HTMLButtonElement).disabled).toBe(false)
  expect((screen.getByRole('button', { name: 'JSON' }) as HTMLButtonElement).disabled).toBe(false)
  const [expand] = screen.getAllByRole('button', { name: 'Expand row' })
  if (!expand) throw new Error('A tentativa não pode ser expandida.')
  fireEvent.click(expand)
  expect(await screen.findByText(/Cardinalidade · básica · Validação/)).toBeTruthy()
  expect(screen.getByRole('link', { name: trace }).getAttribute('href')).toContain(trace)

  const createObjectURL = vi.fn(() => 'blob:avaliacao')
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = createObjectURL
    static revokeObjectURL = vi.fn()
  })
  const download = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  try {
    fireEvent.click(screen.getByRole('button', { name: 'CSV' }))
    fireEvent.click(screen.getByRole('button', { name: 'JSON' }))
    expect(createObjectURL.mock.calls).toEqual([[expect.any(Blob)], [expect.any(Blob)]])
    expect(download.mock.instances.map((anchor) => (anchor as HTMLAnchorElement).download))
      .toEqual(['avaliacao-experimental.csv', 'avaliacao-experimental.json'])
  } finally {
    download.mockRestore()
  }
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Modo de avaliação' }))
  fireEvent.click(await screen.findByRole('option', { name: 'Científica — snapshot controlado' }))
  expect(await screen.findByText('Data de referência 2025-01-01 · Seed ecommerce-v1')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: 'Executar categoria' }))
  expect(await screen.findByText('Resultado divergente')).toBeTruthy()
  expect(evaluated.mock.calls.slice(2)).toEqual([['modelo-a', 'scientific'], ['modelo-b', 'scientific']])
}, 20_000)
