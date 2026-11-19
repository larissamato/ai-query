import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamQuery } from './api'

const trace = '01020304050607080102030405060708'

describe('SSE de consultas', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lê quadros fragmentados e preserva caracteres UTF-8', async () => {
    const stage = { trace_id: trace, name: 'generation', status: 'running', duration_ms: null, error: null }
    const result = {
      http_status: 422,
      response: { trace_id: trace, stages: [], generation: null, result: null, prompt: [{ role: 'user', content: 'São Paulo' }] },
    }
    const encoded = new TextEncoder().encode(
      `event: stage\r\ndata: ${JSON.stringify(stage)}\r\n\r\n: keep alive\r\n\r\nevent: result\r\ndata: ${JSON.stringify(result)}\r\n\r\n`,
    )
    const fetcher = vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(controller) {
        for (const byte of encoded) controller.enqueue(Uint8Array.of(byte))
        controller.close()
      },
    }), { headers: { 'Content-Type': 'text/event-stream' } }))
    vi.stubGlobal('fetch', fetcher)

    const onStage = vi.fn()
    expect(await streamQuery('São Paulo', 'modelo-local', new AbortController().signal, onStage)).toEqual(result)
    expect(onStage).toHaveBeenCalledExactlyOnceWith(stage)
    expect(JSON.parse(fetcher.mock.calls[0]?.[1].body as string)).toEqual({
      question: 'São Paulo', model: 'modelo-local', include_prompt: true,
    })
  })

  it('distingue stream interrompido e erro HTTP antes do SSE', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(': ping\n\n', { headers: { 'Content-Type': 'text/event-stream' } }))
      .mockResolvedValueOnce(Response.json({ detail: 'Modelo indisponível.' }, { status: 503 }))
    vi.stubGlobal('fetch', fetcher)
    const signal = new AbortController().signal
    await expect(streamQuery('Pergunta', undefined, signal, vi.fn())).rejects.toThrow('interrompido')
    await expect(streamQuery('Pergunta', undefined, signal, vi.fn())).rejects.toThrow('Modelo indisponível.')
  })
})
