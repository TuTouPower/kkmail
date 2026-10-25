// @vitest-environment jsdom
import { createElement, useEffect } from 'react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useScopeSync } from './use_scope_sync'
import { useMailStore } from '../store/mailStore'
import { cleanup, render, waitFor } from '../test/render'
import { clearDiagnosticLogs, getDiagnosticLogs } from '../lib/diagnostics'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function completeDelta(id = 'req-1') {
  return json({
    id, mode: 'delta', trigger: 'manual', state: 'complete', target_count: 1,
    queued_count: 0, running_count: 0, completed_count: 1, failed_count: 0,
    created_at: '2026-10-26T00:00:00Z', errors: [],
  }, 202)
}

interface FetchCall { url: string; method: string; headers: Headers; body: unknown }
let calls: FetchCall[] = []
let hookApi: ReturnType<typeof useScopeSync> | null = null

function Harness() {
  const api = useScopeSync(true)
  useEffect(() => { hookApi = api })
  return null
}

function deltaCalls() {
  return calls.filter((c) => c.url.endsWith('/api/mail/sync/delta'))
}
function activityCalls() {
  return calls.filter((c) => c.url.endsWith('/api/mail/sync/activity'))
}

beforeEach(() => {
  calls = []
  hookApi = null
  clearDiagnosticLogs()
})

afterEach(() => {
  cleanup()
  clearDiagnosticLogs()
})

describe('useScopeSync (p053/R01)', () => {
  it('sends delta sync through the unified client with the CSRF header', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))

    // The navigation auto-trigger fires on mount via the unified client.
    await waitFor(() => expect(deltaCalls()).toHaveLength(1))
    expect(deltaCalls()[0].headers.get('X-CSRF-Token')).toBe('tok-abc')
    expect(deltaCalls()[0].body).toMatchObject({ folder_role: 'inbox', trigger: 'navigation' })
    await waitFor(() => expect(hookApi?.isSyncing).toBe(false))
    expect(hookApi?.lastError).toBeNull()
  })

  it('renders an object-shaped error detail readably, never "[object Object]"', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) {
        return json({ detail: [{ loc: ['body', 'folder_role'], msg: 'folder_role 不合法', type: 'value_error' }] }, 422)
      }
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))

    await waitFor(() => expect(hookApi?.lastError).toBe('folder_role 不合法'))
    expect(hookApi?.lastError).not.toContain('[object Object]')
    expect(hookApi?.isSyncing).toBe(false)
  })

  it('heartbeat posts activity via the unified client only while visible, and failures go to diagnostics not the banner', async () => {
    vi.useFakeTimers()
    useMailStore.setState({ view: { type: 'account', accountId: 'acc-1', email: 'a@x.test' } })
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
      const u = String(url)
      calls.push({
        url: u,
        method: init.method || 'GET',
        headers: new Headers(init.headers),
        body: init.body ? JSON.parse(String(init.body)) : null,
      })
      if (u.endsWith('/api/auth/me')) return json({ csrf_token: 'tok-abc', via: 'session' })
      if (u.endsWith('/api/mail/sync/delta')) return completeDelta()
      if (u.endsWith('/api/mail/sync/activity')) return json({ detail: 'heartbeat boom' }, 500)
      return json({ detail: 'unexpected' }, 404)
    }))

    await render(createElement(Harness))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(activityCalls()).toHaveLength(0)

    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(activityCalls()).toHaveLength(1)
    expect(activityCalls()[0].headers.get('X-CSRF-Token')).toBe('tok-abc')
    expect(activityCalls()[0].body).toEqual({ account_ids: ['acc-1'] })

    // The failed heartbeat must not become a repeating user-facing error…
    expect(hookApi?.lastError).toBeNull()
    // …but must land in the sanitized diagnostics channel.
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(getDiagnosticLogs().some((entry) => entry.message === '活动心跳上报失败')).toBe(true)

    // Hidden page: no further heartbeats.
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    await act(async () => { await vi.advanceTimersByTimeAsync(40_000) })
    expect(activityCalls()).toHaveLength(1)
    vi.useRealTimers()
  })
})
