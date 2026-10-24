import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'

describe('api cancellation', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('passes React Query cancellation through to fetch', async () => {
    const captured: { signal?: AbortSignal } = {}
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise((_resolve, reject) => {
      if (init?.signal) captured.signal = init.signal
      captured.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const request = client.fetchQuery({
      queryKey: ['cancel-me'],
      queryFn: ({ signal }) => api('/slow', { signal }),
    })

    await vi.waitFor(() => expect(captured.signal).toBeDefined())
    await client.cancelQueries({ queryKey: ['cancel-me'] })

    expect(captured.signal?.aborted).toBe(true)
    await expect(request).rejects.toBeTruthy()
  })
})
