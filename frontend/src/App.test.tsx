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

function fixture(stream: () => Response) {
  const routes = vi.fn((url: string) => {
    if (url === '/api/schema') return Promise.resolve(Response.json({
      schema_name: 'ecommerce',
      tables: [{ name: 'orders', columns: [{ name: 'order_id', data_type: 'integer', nullable: false }], primary_key: ['order_id'], foreign_keys: [] }],
    }))
    if (url === '/api/models') return Promise.resolve(Response.json({ models: ['modelo-a', 'modelo-b'], default: 'modelo-a' }))
    if (url === '/api/query/stream') return Promise.resolve(stream())
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
