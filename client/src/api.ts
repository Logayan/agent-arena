import type { RunSnapshot } from './types'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body.detail ?? '请求失败')
  }
  return response.json() as Promise<T>
}

export const api = {
  getDemo: () => request<RunSnapshot>('/api/demo'),
  createDemo: () => request<RunSnapshot>('/api/demo', { method: 'POST' }),
  getRun: (runId: string) => request<RunSnapshot>(`/api/runs/${runId}`),
  startRun: (runId: string) =>
    request<RunSnapshot>(`/api/runs/${runId}/start`, { method: 'POST' }),
  cancelRun: (runId: string) =>
    request<RunSnapshot>(`/api/runs/${runId}/cancel`, { method: 'POST' }),
  eventUrl: (runId: string, sequence: number) =>
    `${API_BASE}/api/runs/${runId}/events?after_sequence=${sequence}`,
}
